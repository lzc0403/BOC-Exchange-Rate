r"""
中国银行外汇牌价 - 连接测试 / 数据校验 / 缺失日期补全工具
================================================================================
独立验证程序，配合 boc_scraper_v6.1.py（v6.2 打码平台版）使用。

背景：
  项目因 Geetest v4 挡死旧 ddddocr，停更约 45 天（数据冻结在 2026-06-24）。
  v6.1 的 main() 仅抓「今天+昨天」且为 DAILY_MODE 专用，历史补全已被禁用。
  本工具用于在「配置好打码平台 Key」后：
    1) 验证能否从目标数据源（中行 JSON 接口）获取真实数据；
    2) 自动补齐最近因故障缺失的历史数据，保证连续完整；
    3) 对每条抓取记录做严格字段校验，杜绝脏数据入库。

设计要点（省成本核心）：
  - 连接测试阶段解出 gt 后，整个 backfill 跨币种、跨日期复用，仅当捕获
    BocCaptchaError（验证码失效）时才重新求解一次，符合「每天只过一次码」。
  - 复用 boc_scraper_v6.1 的 solve_geetest / query_day / parse_response /
    select_daily_record / append_row / load_done 等，不重写任何抓取逻辑。
  - 无 Key 时安全降级：连接测试返回 FAIL，但仍能算出缺失缺口，便于预览。

注意：本工具为「验证 + 补全」专用，不发送邮件（邮件由日常 CI send_daily_emails 负责）。
"""

import argparse
import importlib.util
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

# ============================================================
#  复用 boc_scraper_v6.1（文件名含点号，需用 importlib 按路径加载）
# ============================================================
_THIS_DIR = Path(__file__).resolve().parent
_SCRAPER_PATH = _THIS_DIR / "boc_scraper_v6.1.py"

_spec = importlib.util.spec_from_file_location("boc_scraper_v61", str(_SCRAPER_PATH))
scraper = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scraper)

# 直接复用既有实现（不重写）
solve_geetest = scraper.solve_geetest
query_day = scraper.query_day
parse_response = scraper.parse_response
select_daily_record = scraper.select_daily_record
append_row = scraper.append_row
load_done = scraper.load_done
fetch_history_page = scraper.fetch_history_page
extract_captcha_id = scraper.extract_captcha_id
make_session = scraper.make_session
parse_time = scraper.parse_time
HISTORY_PAGE_URL = scraper.HISTORY_PAGE_URL
CURRENCIES = scraper.CURRENCIES
BocCaptchaError = scraper.BocCaptchaError
GEETEST_CAPTCHA_ID = scraper.GEETEST_CAPTCHA_ID
_has_captcha_key = scraper._has_captcha_key
CAPTCHA_PROVIDER = scraper.CAPTCHA_PROVIDER
CAPSOLVER_API_KEY = scraper.CAPSOLVER_API_KEY
TWOCAPTCHA_API_KEY = scraper.TWOCAPTCHA_API_KEY
log = scraper.log

# ============================================================
#  本工具常量
# ============================================================
# 中行接口查询日期格式（与 BOC 页面 queryParams 一致）。
# 已知风险点：若实测取不到数，可改 "%Y/%m/%d" 再试（先不改代码，仅注释说明）。
DATE_FMT = "%Y-%m-%d"

# 停更起点：数据冻结在 2026-06-24，缺口自次日 2026-06-25 起。
# 缺失检测一律不早于该日，避免港币等「无根目录 CSV」时被误判需从 2023 补几千行。
OUTAGE_START = date(2026, 6, 25)

# 价格字段校验正则：允许小数，如 688.8 / 691.72 / 696.46
PRICE_RE = re.compile(r"^\d+(\.\d+)?$")

PRICE_FIELDS = ("现汇买入价", "现钞买入价", "现汇卖出价", "现钞卖出价", "中行折算价")


# ============================================================
#  工具函数
# ============================================================
def say(msg: str = "") -> None:
    """print 与 log.info 双输出，保证控制台与日志一致。"""
    print(msg)
    log.info(msg)


def _is_date_str(s: str) -> bool:
    """判断字符串是否为 YYYY-MM-DD 形式的日期。"""
    try:
        date.fromisoformat(str(s))
        return True
    except (ValueError, TypeError):
        return False


def _resolve_captcha_id() -> str:
    """解析 Geetest captcha_id：GET 检索页提取；失败则用常量兜底。"""
    try:
        html = fetch_history_page()
        cid = extract_captcha_id(html)
        if cid:
            log.info(f"从检索页提取 captcha_id = {cid}")
            return cid
    except Exception as e:  # noqa: BLE001 - 连接失败时降级，不阻塞后续流程
        log.warning(f"获取检索页/提取 captcha_id 失败，使用兜底常量: {e}")
    return GEETEST_CAPTCHA_ID


def read_last_row(path: str) -> dict | None:
    """读取 CSV 最后一行（用于报告展示最近一条记录的折算价样例）。"""
    p = Path(path)
    if not p.exists():
        return None
    try:
        df = pd.read_csv(p)
        if df.empty:
            return None
        return df.iloc[-1].to_dict()
    except Exception:  # noqa: BLE001
        return None


# ============================================================
#  Step 1: 连接测试
# ============================================================
def test_connection(session, captcha_id: str, pageurl: str) -> tuple[bool, dict | None, str | None, str]:
    """
    验证能否从目标数据源获取真实数据。

    返回 (ok, gt, token, message)：
      - ok=False 且原因为「未配置 Key」时：gt/token 为 None，提示本地 set 或走 CI；
      - ok=True：gt 为解出的验证码四字段，token 为接口响应头 Token（可复用于后续请求）；
      - 任何异常都被捕获，返回 (False, None, None, 原因)。

    本函数会实际联网（过验证码 + POST 接口），仅在已配置打码平台 Key 时执行。
    """
    if not _has_captcha_key():
        return (
            False,
            None,
            None,
            "未配置打码平台 Key（CAPSOLVER_API_KEY），无法联网验证；请本地 set 或走 CI",
        )

    try:
        # 1) 过验证码：验证打码平台连通且可解
        gt = solve_geetest(captcha_id, pageurl)
        # 2) 探测当日美元数据：验证接口可取数
        today = date.today()
        data_list, token = query_day(session, today, "美元", gt)
        # 3) 解析 + 选样：验证响应能被正确解析出有效记录
        rows = parse_response(data_list, "美元", today)
        rec = select_daily_record(rows, today)
        if rec is None or len(rows) < 1:
            return (
                False,
                None,
                None,
                f"连接成功，但无法解析出有效美元记录（可能 {today} 尚未发布牌价）",
            )
        return (True, gt, token, "连接正常，成功获取真实数据")
    except Exception as e:  # noqa: BLE001 - 连接测试须对一切异常优雅降级
        return (False, None, None, f"{type(e).__name__}: {e}")


# ============================================================
#  数据校验（单条记录）
# ============================================================
def validate_record(rec: dict, currency: str, d: date) -> tuple[bool, str]:
    r"""
    严格校验一条抓取记录是否可入库。

    校验项：
      ① 货币名称 == currency；
      ② 五个价格字段均非空且为可解析数值（正则 ^\d+(\.\d+)?$）；
      ③ 发布时间可解析且日期 == d；
      ④ 查询日期 == d.strftime("%Y-%m-%d")。

    返回 (True, "") 或 (False, "具体原因")。
    """
    if rec.get("货币名称") != currency:
        return (False, f"货币名称不匹配: 期望'{currency}' 实际'{rec.get('货币名称')}'")

    for field in PRICE_FIELDS:
        val = rec.get(field, "")
        if val is None or str(val).strip() == "":
            return (False, f"{field}为空")
        if not PRICE_RE.match(str(val).strip()):
            return (False, f"{field}非有效数字: '{val}'")

    pt = parse_time(rec.get("发布时间", ""))
    if pt is None:
        return (False, f"发布时间解析失败: '{rec.get('发布时间')}'")
    if pt.date() != d:
        return (False, f"发布时间日期不符: {pt.date()} != {d}")

    if rec.get("查询日期") != d.strftime(DATE_FMT):
        return (False, f"查询日期不符: '{rec.get('查询日期')}' != {d.strftime(DATE_FMT)}")

    return (True, "")


# ============================================================
#  Step 2: 缺失日期检测
# ============================================================
def find_missing_dates(
    currency: str,
    output_file: str,
    usd_last_date: date,
    end_date: date,
    max_days: int = 60,
) -> list[date]:
    """
    计算某币种在 [start, end_date] 内、缺失（未抓取）的日期列表。

    start 取值规则：
      - 若文件存在且已有数据：start = max(最大已存在日期 + 1天, OUTAGE_START)；
      - 若文件不存在（如港币根目录 CSV 缺失）：start = max(OUTAGE_START, usd_last_date + 1天)。
        以 usd_last_date 作参考，保证不会从 2023 一路补成几千行。

    生成 start..end_date 序列，过滤已有日期后，取「最近的 max_days 天」（默认 60，
    覆盖本次 45 天缺口），返回排序后的缺失日期列表。
    """
    existing = load_done(output_file)

    if existing:
        # 已有数据：从最大已存在日期的次日开始，且不得早于停更起点
        max_existing = max(
            (date.fromisoformat(s) for s in existing if _is_date_str(s)),
            default=None,
        )
        if max_existing is not None:
            start = max(max_existing + timedelta(days=1), OUTAGE_START)
        else:
            start = OUTAGE_START
    else:
        # 文件不存在：以停更起点为界，并以美元最后有效日期作参考
        start = max(OUTAGE_START, usd_last_date + timedelta(days=1))

    # 生成序列并过滤掉已存在日期
    missing: list[date] = []
    d = start
    while d <= end_date:
        if d.strftime(DATE_FMT) not in existing:
            missing.append(d)
        d += timedelta(days=1)

    # 取最近的 max_days 天
    recent = missing[-max_days:] if max_days and max_days > 0 else missing
    return sorted(recent)


# ============================================================
#  Step 3: 缺失日期补全
# ============================================================
def backfill(
    session,
    gt_ref: dict,
    token_ref: dict,
    missing_by_currency: dict[str, list[date]],
    max_attempts: int = 2,
) -> dict:
    """
    对缺失日期执行真实补全（联网写库）。

    gt_ref / token_ref 为可变容器（如 {"gt":..., "token":...}），用于跨日期/跨币种
    复用验证码解，仅在 BocCaptchaError 时就地重置 gt 并重解一次。

    重试策略（每币种每日期，按旧→新顺序）：
      - 最多 max_attempts 次尝试：query_day → parse_response → select_daily_record
        → validate_record → append_row；
      - 捕获 BocCaptchaError：重置 gt_ref["gt"]=None 并重解一次后重试；
      - 捕获其他 Exception（超时/网络/校验失败）：复用同一 gt 直接重试（不重解）；
      - 成功记 filled；两次都失败记 failed（带原因）；
      - select_daily_record 返回 None（当日尚未发布牌价）属正常，跳过不计失败。

    返回 {"filled": {币种: [日期...]}, "failed": {币种: [(日期, 原因)...]},
          "skipped": {币种: [日期...]}, "sample": 首条成功记录 或 None}。
    """
    # captcha_id 仅用于（首次/重解）过验证码；一次性解析，避免重复联网
    captcha_id = _resolve_captcha_id()
    pageurl = HISTORY_PAGE_URL

    filled: dict[str, list[date]] = {}
    failed: dict[str, list[tuple[date, str]]] = {}
    skipped: dict[str, list[date]] = {}
    sample: dict | None = None

    for currency, dates in missing_by_currency.items():
        output_file = CURRENCIES[currency]
        filled.setdefault(currency, [])
        failed.setdefault(currency, [])
        skipped.setdefault(currency, [])

        for d in sorted(dates):
            ds = d.strftime(DATE_FMT)
            last_reason = "未知原因"
            ok = False

            for attempt in range(1, max_attempts + 1):
                try:
                    # gt 失效/未解时就地求解；成功后跨日期复用，省去重复计费
                    if gt_ref.get("gt") is None:
                        gt_ref["gt"] = solve_geetest(captcha_id, pageurl)

                    data_list, tok = query_day(
                        session, d, currency, gt_ref["gt"], token_ref.get("token")
                    )
                    token_ref["token"] = tok

                    rows = parse_response(data_list, currency, d)
                    rec = select_daily_record(rows, d)
                    if rec is None:
                        # 当日尚未发布牌价：正常情况，跳过（不重试、不计失败）
                        log.info(f"  [{ds}/{currency}] 当日尚未发布牌价，跳过（不重试、不计失败）")
                        skipped[currency].append(d)
                        break

                    valid, reason = validate_record(rec, currency, d)
                    if not valid:
                        raise ValueError(f"校验失败: {reason}")

                    rec.pop("_t", None)
                    append_row(rec, output_file)
                    log.info(
                        f"  ✓ 已补齐 {output_file} | {ds} {currency} "
                        f"{rec['发布时间']} 折算价={rec['中行折算价']}"
                    )
                    if sample is None:
                        sample = dict(rec)
                    ok = True
                    break

                except BocCaptchaError as e:
                    # 验证码失效：重置 gt，下一次尝试将重新求解
                    log.warning(f"  [{ds}/{currency}] 第{attempt}次 验证码失效: {e}")
                    gt_ref["gt"] = None
                    last_reason = f"验证码失效: {e}"
                    continue
                except Exception as e:  # noqa: BLE001 - 超时/网络/校验失败，复用 gt 重试
                    log.warning(
                        f"  [{ds}/{currency}] 第{attempt}次 异常(超时/网络/校验): {e}"
                    )
                    last_reason = f"{type(e).__name__}: {e}"
                    continue

            if d in skipped.get(currency, []):
                pass  # 已计入 skipped
            elif ok:
                filled[currency].append(d)
            else:
                failed[currency].append((d, last_reason))

    return {"filled": filled, "failed": failed, "skipped": skipped, "sample": sample}


# ============================================================
#  Step 4 + 主流程
# ============================================================
def _print_missing(currency: str, missing: list[date]) -> None:
    if not missing:
        say(f"  · {currency}: 无缺失（数据连续）")
        return
    say(
        f"  · {currency}: 缺失 {len(missing)} 天，"
        f"范围 {missing[0].strftime(DATE_FMT)} ~ {missing[-1].strftime(DATE_FMT)}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="BOC 汇率连接测试 + 数据校验 + 缺失日期补全工具"
    )
    parser.add_argument(
        "--max-days", type=int, default=60,
        help="补全窗口最大天数（默认 60，覆盖本次约 45 天缺口）",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="即便有 Key 也只检测/预览，不写入 CSV",
    )
    parser.add_argument(
        "--no-email", action="store_true",
        help="预留开关（本工具本身不发送邮件，由日常 CI 负责）",
    )
    args = parser.parse_args()

    # ----- 横幅 -----
    say("=" * 64)
    say("中国银行外汇牌价 · 连接测试 / 数据校验 / 缺失补全")
    say(f"运行日期: {date.today()}  | 打码供应商: {CAPTCHA_PROVIDER} | dry-run: {args.dry_run}")
    say("=" * 64)

    # ----- Step 1: 连接测试 -----
    say("")
    say("【Step 1/4】连接测试")
    # 现场从检索页提取真实 captcha_id（提取失败才退回常量），避免写死常量过期导致 CapSolver 报 not captcha
    captcha_id = _resolve_captcha_id()
    session = make_session()
    conn_ok, gt, token, conn_msg = test_connection(session, captcha_id, HISTORY_PAGE_URL)
    if conn_ok:
        say(f"  ✓ 连接测试通过 — {conn_msg}")
    else:
        say(f"  ✗ 连接测试未通过 — {conn_msg}")

    # ----- Step 2: 缺失检测 -----
    say("")
    say("【Step 2/4】缺失日期检测")
    usd_done = load_done(CURRENCIES["美元"])
    usd_last_date = max(
        (date.fromisoformat(s) for s in usd_done if _is_date_str(s)),
        default=OUTAGE_START - timedelta(days=1),
    )
    today = date.today()
    usd_missing = find_missing_dates(
        "美元", CURRENCIES["美元"], usd_last_date, today, args.max_days
    )
    hkd_missing = find_missing_dates(
        "港币", CURRENCIES["港币"], usd_last_date, today, args.max_days
    )
    missing_by_currency = {"美元": usd_missing, "港币": hkd_missing}
    _print_missing("美元", usd_missing)
    _print_missing("港币", hkd_missing)
    say(f"  （美元最后有效日期: {usd_last_date.strftime(DATE_FMT)}；"
        f"停更起点: {OUTAGE_START.strftime(DATE_FMT)}）")

    # ----- Step 3: 补全 -----
    say("")
    say("【Step 3/4】缺失日期补全")
    result: dict = {"filled": {}, "failed": {}, "skipped": {}, "sample": None}
    if conn_ok and not args.dry_run:
        gt_ref = {"gt": gt, "token": token}
        token_ref = {"token": token}
        say("  连接正常，开始执行真实补全（复用已解 gt，跨币种/跨日期复用）...")
        result = backfill(session, gt_ref, token_ref, missing_by_currency)
    else:
        reason = "dry-run 模式" if args.dry_run else "未通过连接测试（无 Key）"
        say(f"  跳过真实补全：{reason}。设置 Key 后重跑以执行真实补全。")

    # ----- Step 4: 报告 -----
    say("")
    say("【Step 4/4】执行报告")
    say(f"  · 连接状态      : {'OK' if conn_ok else 'FAIL'}（{conn_msg}）")

    sample = result.get("sample")
    if sample:
        say(
            f"  · 校验样例      : {sample.get('查询日期')} {sample.get('货币名称')} "
            f"折算价={sample.get('中行折算价')} 发布时间={sample.get('发布时间')}"
        )
    else:
        last_usd = read_last_row(CURRENCIES["美元"])
        if last_usd:
            say(
                f"  · 现有最近样例  : {last_usd.get('查询日期')} {last_usd.get('货币名称')} "
                f"折算价={last_usd.get('中行折算价')}（未执行新补全）"
            )

    total_missing = len(usd_missing) + len(hkd_missing)
    total_filled = sum(len(v) for v in result.get("filled", {}).values())
    total_failed = sum(len(v) for v in result.get("failed", {}).values())
    total_skipped = sum(len(v) for v in result.get("skipped", {}).values())
    for currency in ("美元", "港币"):
        f = len(result.get("filled", {}).get(currency, []))
        fl = len(result.get("failed", {}).get(currency, []))
        sk = len(result.get("skipped", {}).get(currency, []))
        m = len(missing_by_currency.get(currency, []))
        say(f"  · {currency:<4}: 缺失 {m:>3} 天 | 已补 {f:>3} 天 | 跳过 {sk:>3} 天 | 失败 {fl:>3} 天")

    if total_failed:
        say("  · 失败明细:")
        for currency, items in result.get("failed", {}).items():
            for d, reason in items:
                say(f"      - {currency} {d.strftime(DATE_FMT)}: {reason}")

    # ----- TL;DR -----
    say("")
    say("-" * 64)
    if conn_ok and not args.dry_run:
        tldr = (
            f"TL;DR: 连接正常；检测到缺失 {total_missing} 天，"
            f"本次成功补齐 {total_filled} 天，跳过 {total_skipped} 天（当日无牌价），"
            f"失败 {total_failed} 天。"
        )
    else:
        skip_reason = "dry-run 预览" if args.dry_run else "无 Key"
        tldr = (
            f"TL;DR: 连接测试={'OK' if conn_ok else 'FAIL'}，检测到缺失 {total_missing} 天"
            f"（{skip_reason}，未执行真实补全）。配置 CAPSOLVER_API_KEY 后重跑即可补齐。"
        )
    say(tldr)
    say("=" * 64)


if __name__ == "__main__":
    main()
