"""
中国银行外汇牌价历史抓取 - v6.2 (Geetest v4 + 打码平台)

=====================================================================
  根因与修复说明（为什么 v6.1 停更、v6.2 改了什么）
=====================================================================
  v6.1 的抓取链路：GET/POST 旧接口
      https://srh.bankofchina.com/search/whpj/search_cn.jsp
  该接口已于 2026 年前后下线，现直接返回 404；同时中行历史牌价检索页
      https://www.boc.cn/sourcedb/whpjSearch/index.html
  升级为 Geetest v4 行为验证码。原代码用的 ddddocr 只能识别图片字符码，
  对行为验证码完全无效 → 每日抓取返回空结果 → “无数据变更，跳过提交”，
  导致 GitHub Actions 全绿但实际零产出，网站数据冻结。

  v6.2 改为：
    1. 用打码平台（CapSolver 主 / 2Captcha 备）自动过 Geetest v4；
    2. 带着 4 个 gt4 字段，POST 中行新的历史检索 JSON 接口取数：
         POST https://srh.bankofchina.com/tsearch/v1/searchExchange/
              searchMultipleExchangeByXian
       请求体：{"reqHeader":{},"reqBody":{"pjrq":日期,"pjname":币种,
              "lotNumber","captchaOutput","passToken","genTime",
              "pageSize":"1000","page":"1"}}
       响应体：respBody.respStatus=="00" 时 respBody.data[] 为记录数组，
             字段 cname_hbmc(货币名称)/hmrj2/cmrj2/mcj2/cmcj2/zhzjj2/
             pjtime(发布时间)。respStatus=="02" 表示验证码未过/失效。
    3. 严格保留原 CSV 列顺序与每日“取≥10:00最早一条”的选样/去重契约。

  说明：中行历史接口现已改为“按当日查询”（pjrq 传指定日期只返回该日记录），
  因此“补全模式(DAILY_MODE=false)”无法再批量回填历史日期，v6.2 在该模式下
  仅记录 warning 并退出，绝不删除已有数据。每日模式(DAILY_MODE=true)为常态用途。

=====================================================================
  本地测试（无需 Key 也可验证大部分逻辑）
=====================================================================
  set CAPSOLVER_API_KEY=xxx        # 打码平台 Key（无 Key 时脚本会安全跳过）
  set DAILY_MODE=true
  python boc_scraper_v6.1.py
  无 Key 时：抓取检索页 → 提取 captcha_id → 检测到无 Key → 打印明确警告并退出，
  不写入、不报错。有 Key 时：过验证码 → POST → 解析当日数据 → 追加 CSV。
  纯逻辑（解析/选样/去重/多币种）见同目录 test_scraper_logic.py。
"""
import os
import re
import time
import json
import random
import logging
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime, date, timedelta
from pathlib import Path

import requests
import pandas as pd
from dotenv import load_dotenv

# ============================================================
#  配置（支持环境变量覆盖）
# ============================================================
# 默认全量范围：2023-01-01 ~ 昨天（仅用于说明；补全模式当前已禁用）
DEFAULT_START = date(2023, 1, 1)

# 环境变量 DAILY_MODE=true 时，仅抓取当天（常态 CICD 用法）
is_daily = os.getenv("DAILY_MODE", "").lower() in ("true", "1", "yes")
if is_daily:
    START_DATE = date.today()
    END_DATE = date.today()
else:
    START_DATE = DEFAULT_START
    END_DATE = date.today() - timedelta(days=1)

TARGET_HOUR = 10          # 优先抓每天 10:00 之后最早一条

# 多币种配置：币种中文名 → 输出文件名（契约，勿改）
CURRENCIES = {
    "美元": "boc_usd_cny.csv",
    "港币": "boc_hkd_cny.csv",
}

# 打码平台供应商：capsolver（默认主用） / twocaptcha（备用）
CAPTCHA_PROVIDER = os.getenv("CAPTCHA_PROVIDER", "capsolver").lower()
CAPSOLVER_API_KEY = os.getenv("CAPSOLVER_API_KEY", "")
TWOCAPTCHA_API_KEY = os.getenv("TWOCAPTCHA_API_KEY", "")

# 中行历史牌价检索页（用来取 captcha_id 与建立会话 cookie）
HISTORY_PAGE_URL = "https://www.boc.cn/sourcedb/whpjSearch/index.html"
# 历史检索 JSON 接口（实际取数目标，替代已 404 的 search_cn.jsp）
SEARCH_API_URL = "https://srh.bankofchina.com/tsearch/v1/searchExchange/searchMultipleExchangeByXian"
# 兜底 captcha_id（运行时优先从页面动态提取；此处为离线兜底值）
GEETEST_CAPTCHA_ID = "a4d5e32ec03f74bf0425916cabe1c5a9"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# 每个币种查询最大尝试次数：第 1 次为正常执行，仅当失败时才重试 1 次（共 2 次）。
# 不做无意义的频繁轮询，以节省打码平台(CapSolver)按次计费成本。
MAX_ATTEMPTS_PER_CURRENCY = 2

# JSON 响应字段 → CSV 列 的映射（respBody.data[].xxx）
FIELD_MAP = {
    "货币名称": "cname_hbmc",
    "现汇买入价": "hmrj2",
    "现钞买入价": "cmrj2",
    "现汇卖出价": "mcj2",
    "现钞卖出价": "cmcj2",
    "中行折算价": "zhzjj2",
    "发布时间": "pjtime",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("boc.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


class BocCaptchaError(Exception):
    """接口返回验证码未通过/失效时抛出，用于触发重新求解。"""


# ============================================================
#  会话管理（建立中行站点 cookie）
# ============================================================
def make_session() -> requests.Session:
    """建立与中行站点的会话（主要用于拿到检索页 Set-Cookie）。"""
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": HISTORY_PAGE_URL,
    })
    try:
        s.get(HISTORY_PAGE_URL, timeout=15)
    except Exception as e:
        log.warning(f"会话初始化警告: {e}")
    return s


# ============================================================
#  检索页 / captcha_id 提取
# ============================================================
def fetch_history_page() -> str:
    """GET 历史检索页，返回 HTML 文本。"""
    r = requests.get(HISTORY_PAGE_URL, headers={"User-Agent": UA}, timeout=20)
    r.raise_for_status()
    r.encoding = "utf-8"
    return r.text


def extract_captcha_id(html: str) -> str | None:
    """
    从检索页 HTML 提取 Geetest v4 的静态 captcha_id。
    页面形如：var captchaId = "a4d5e32ec03f74bf0425916cabe1c5a9"
    也兜底匹配 gt4 load 脚本中的 captcha_id 参数。
    """
    if not html:
        return None
    # 主匹配：var captchaId = "...."
    m = re.search(r'captchaId\s*=\s*["\']([0-9a-fA-F]{16,})["\']', html)
    if m:
        return m.group(1)
    # 兜底：captcha_id= 或 "captcha_id":"...."
    m2 = re.search(r'captcha_id["\']?\s*[:=]\s*["\']([0-9a-fA-F]{16,})["\']', html)
    return m2.group(1) if m2 else None


# ============================================================
#  打码平台：Geetest v4 解题（CapSolver 主 / 2Captcha 备）
# ============================================================
def _has_captcha_key() -> bool:
    if CAPTCHA_PROVIDER == "twocaptcha":
        return bool(TWOCAPTCHA_API_KEY)
    return bool(CAPSOLVER_API_KEY)


def _solve_capsolver(captcha_id: str, pageurl: str) -> dict:
    """调用 CapSolver 解 Geetest v4，返回标准 4 字段（snake_case）。"""
    if not CAPSOLVER_API_KEY:
        raise RuntimeError("CAPSOLVER_API_KEY 未配置")
    import capsolver  # 延迟导入，避免无 Key / 离线时硬依赖
    capsolver.api_key = CAPSOLVER_API_KEY
    # CapSolver 对 Geetest V4 的任务类型固定为 GeeTestTaskProxyLess
    # （不带 "V4" 字样；V4 通过 captchaId 参数本身区分，而非 type 字符串）。
    # 注意：type 写错会被 API 拒绝；字段名必须是驼峰 captchaId（非 captcha_id）。
    # BOC 的 Geetest 脚本/API 都在子域 immvs.igtb.bankofchina.com，
    # 显式指定 geetestApiServerSubdomain 帮助 CapSolver 定位验证码。
    solution = capsolver.solve({
        "type": "GeeTestTaskProxyLess",
        "websiteURL": pageurl,
        "captchaId": captcha_id,
        "geetestApiServerSubdomain": "immvs.igtb.bankofchina.com",
    })
    # CapSolver 返回标准 Geetest v4 字段（snake_case）
    return {
        "lot_number": solution["lot_number"],
        "pass_token": solution["pass_token"],
        "gen_time": solution["gen_time"],
        "captcha_output": solution["captcha_output"],
    }


def _solve_twocaptcha(captcha_id: str, pageurl: str) -> dict:
    """调用 2Captcha 解 Geetest v4，返回标准 4 字段（snake_case）。

    注：2captcha-python 的 geetest_v4 参数名为 url（非 pageurl）。
    """
    if not TWOCAPTCHA_API_KEY:
        raise RuntimeError("TWOCAPTCHA_API_KEY 未配置")
    from twocaptcha import TwoCaptcha  # 延迟导入
    solver = TwoCaptcha(TWOCAPTCHA_API_KEY)
    solution = solver.geetest_v4(captcha_id=captcha_id, url=pageurl)
    return {
        "lot_number": solution["lot_number"],
        "pass_token": solution["pass_token"],
        "gen_time": solution["gen_time"],
        "captcha_output": solution["captcha_output"],
    }


def solve_geetest(captcha_id: str, pageurl: str) -> dict:
    """
    解 Geetest v4 验证码，返回标准 4 字段（snake_case）。
    供应商由 CAPTCHA_PROVIDER 切换（默认 capsolver）。
    """
    if CAPTCHA_PROVIDER == "twocaptcha":
        return _solve_twocaptcha(captcha_id, pageurl)
    return _solve_capsolver(captcha_id, pageurl)


# ============================================================
#  POST 历史检索接口 + 解析
# ============================================================
def query_day(
    session: requests.Session,
    d: date,
    currency: str,
    gt: dict,
    token: str | None = None,
) -> tuple[list, str | None]:
    """
    携带 gt4 四字段，按日期查询某币种当日全部快照。
    返回 (respBody.data 列表, 响应头 Token(用于后续请求))。
    验证码未过/失效时抛 BocCaptchaError。
    """
    # 中行接口使用 camelCase 参数名（与页面 queryParams 一致），
    # 由打码平台返回的 snake_case 标准字段映射而来。
    req_body = {
        "pjrq": d.strftime("%Y-%m-%d"),   # 查询日期
        "pjname": currency,               # 币种中文名
        "lotNumber": gt["lot_number"],
        "captchaOutput": gt["captcha_output"],
        "passToken": gt["pass_token"],
        "genTime": gt["gen_time"],
        "pageSize": "1000",
        "page": "1",
    }
    payload = {"reqHeader": {}, "reqBody": req_body}
    headers = {"User-Agent": UA, "content-type": "application/json"}
    if token:
        headers["Token"] = token

    r = session.post(SEARCH_API_URL, json=payload, headers=headers, timeout=30)
    r.encoding = "utf-8"
    try:
        j = r.json()
    except ValueError:
        raise RuntimeError(f"接口未返回 JSON（HTTP {r.status_code}）")

    rb = j.get("respBody", {})
    status = rb.get("respStatus")
    if status != "00" or "data" not in rb:
        err = rb.get("errMsg", "") or j.get("respHeader", {}).get("respStatus", "")
        raise BocCaptchaError(f"接口返回非00状态: respStatus={status} err={err}")

    # 捕获响应头 Token，供同一会话后续请求复用（页面行为一致）
    new_token = r.headers.get("Token") or token
    return rb["data"], new_token


def parse_time(s: str):
    """解析发布时间字符串（支持 2026/08/07 10:32:15 与 2026-08-07 10:32:15）。"""
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def parse_response(data_list: list, currency: str, d: date) -> list[dict]:
    """
    把接口返回的 data[] 解析为本系统行结构（按表头/字段映射提取）。
    只保留：货币名称匹配 且 发布日期 == 查询日期 的记录。
    """
    rows = []
    for item in data_list:
        if item.get(FIELD_MAP["货币名称"]) != currency:
            continue
        pjtime = item.get(FIELD_MAP["发布时间"], "") or ""
        t = parse_time(pjtime)
        if t is None:
            continue
        if t.date() != d:
            # 防御：接口偶发返回非目标日期（如跨日边界），严格过滤
            continue
        row = {
            "货币名称": item.get(FIELD_MAP["货币名称"], ""),
            "现汇买入价": item.get(FIELD_MAP["现汇买入价"], "") or "",
            "现钞买入价": item.get(FIELD_MAP["现钞买入价"], "") or "",
            "现汇卖出价": item.get(FIELD_MAP["现汇卖出价"], "") or "",
            "现钞卖出价": item.get(FIELD_MAP["现钞卖出价"], "") or "",
            "中行折算价": item.get(FIELD_MAP["中行折算价"], "") or "",
            "发布时间": pjtime,
            "查询日期": d.strftime("%Y-%m-%d"),
            "_t": t,  # 内部排序用，写出前剔除
        }
        rows.append(row)
    return rows


def select_daily_record(rows: list[dict], d: date) -> dict | None:
    """
    从当日全部快照中选出“每天≈10点那一条”：
      策略A：取 >= 10:00 的最早一条（优先）；
      策略B：若当日尚无 >=10:00 的快照（如节假日清晨牌价），取最新的一条兜底。
    返回选中的行（已剔除内部字段 _t）；无记录返回 None。
    """
    if not rows:
        return None
    rows_sorted = sorted(rows, key=lambda x: x["_t"])
    after_10 = [r for r in rows_sorted if r["_t"].hour >= TARGET_HOUR]
    if after_10:
        best = after_10[0]
        log.info(f"  ✓ {best['发布时间']} (策略A: 10点后首条) 折算价={best['中行折算价']}")
        return best
    # 策略B：兜底取当天最新一条
    best = rows_sorted[-1]
    log.info(f"  ✓ {best['发布时间']} (策略B: 10点前独家兜底) 折算价={best['中行折算价']}")
    return best


# ============================================================
#  CSV 读写 / 去重（契约：列顺序、utf-8-sig、按查询日期去重）
# ============================================================
# CSV 列顺序契约（写入/校验/读取共用；勿改，前端与邮箱附件依赖此顺序）
CSV_COLUMNS = ["货币名称", "现汇买入价", "现钞买入价", "现汇卖出价",
               "现钞卖出价", "中行折算价", "发布时间", "查询日期"]
# 必填价格字段：查询日 + 五个价格字段，写入前校验（fail-closed，不写坏数据）
REQUIRED_FIELDS = ("现汇买入价", "现钞买入价", "现汇卖出价", "现钞卖出价", "中行折算价")
# 价格字段合法格式：非负数字（可含 1 位以上小数），如 688.8 / 691.72 / 673.0
_PRICE_RE = re.compile(r"^\d+(\.\d+)?$")


class CsvCorruptError(Exception):
    """CSV 文件损坏（无法解析/列缺失/日期列不可用）时的哨兵异常。

    由 load_done 在损坏场景抛出，调用方（scrape_today 等）据此中止或告警，
    绝不允许静默当作“无任何历史数据”而触发灾难性重复补全。
    """


def _is_iso_query_date(s: str) -> bool:
    """判断字符串是否为合法 YYYY-MM-DD 查询日期。

    用于 load_done 的纵深防御：截断恰好落在日期值中间时 pandas 会把
    半截字符串当普通值（如 "2026-08-10" → "2026"），不产生 NaN，此函数
    可将该形态识别为损坏。
    """
    try:
        date.fromisoformat(str(s).strip())
        return True
    except (ValueError, TypeError):
        return False


def load_done(output_file: str) -> set[str]:
    """读取已有 CSV，返回已记录的 查询日期 集合（用于按天去重）。

    行为契约（既有调用/测试兼容）：
      - 文件不存在        → 返回空集合 set()；
      - 文件正常可解析    → 返回 set(查询日期列)，Date 型统一转 str；
      - 文件存在但损坏    → log.error 明确告警并抛出 CsvCorruptError，
                            由调用方决定中止/告警（不允许静默当作无数据）。

    注意：正常路径返回类型保持 set[str]，异常路径为 CsvCorruptError。
    """
    p = Path(output_file)
    if not p.exists():
        return set()
    try:
        df = pd.read_csv(p)
        if "查询日期" not in df.columns:
            raise KeyError("CSV 缺少必需列: 查询日期")
        # 损坏绝不静默当空：仅表头（无数据行）或 查询日期列存在 NaN
        # （行宽<表头 / 尾部截断 / 日期为空 均会落到 NaN）→ 抛 CsvCorruptError
        if df.empty:
            raise ValueError("CSV 仅表头、无任何数据行（疑似被截断/清空）")
        if df["查询日期"].isna().any():
            n_nan = int(df["查询日期"].isna().sum())
            raise ValueError(f"CSV 查询日期列含 {n_nan} 个 NaN（疑似行宽不一致/尾部截断）")
        # 纵深防御：查询日期必须是合法 YYYY-MM-DD（截断恰好落在日期值中间时
        # pandas 会当字符串而非 NaN，如 "2026-08-10" → "2026"）→ 仍判损坏
        ds_series = df["查询日期"].astype(str)
        bad_dates = [s for s in ds_series if not _is_iso_query_date(s)]
        if bad_dates:
            raise ValueError(
                f"CSV 查询日期列含 {len(bad_dates)} 个非法格式（疑似尾部截断）: "
                f"{sorted(set(bad_dates))[:5]}{'...' if len(set(bad_dates)) > 5 else ''}"
            )
        return set(ds_series)
    except CsvCorruptError:
        raise
    except Exception as e:
        # 损坏绝不静默当空集：明确告警后抛出，调用链据此中止/告警
        log.error("CSV 损坏，拒绝按空集处理: %s (%s: %s)",
                  output_file, type(e).__name__, e)
        raise CsvCorruptError(
            f"CSV 文件损坏，拒绝按空集处理: {output_file} ({type(e).__name__}: {e})"
        ) from e


def _validate_row(row: dict) -> tuple[bool, str]:
    r"""写前校验一条待写记录（fail-closed：非法数据拒绝写入，不写坏数据）。

    校验项：
      ① 必需列齐全且非空：五种价格字段 + 查询日期（货币名称/发布时间可选填）；
      ② 价格字段必须是合法数值（正则 ^\d+(\.\d+)?$，且不得为负）。
    返回 (True, "") 或 (False, "具体原因")。
    """
    if not isinstance(row, dict):
        return (False, f"row 非 dict: {type(row).__name__}")
    if not str(row.get("查询日期", "")).strip():
        return (False, "查询日期为空")
    for f in REQUIRED_FIELDS:
        v = row.get(f)
        if v is None or str(v).strip() == "":
            return (False, f"必填字段 {f} 为空")
        sv = str(v).strip()
        if not _PRICE_RE.match(sv):
            return (False, f"{f} 非合法数值: '{sv}'")
    return (True, "")


def _append_row_atomic(row: dict, output_file: str) -> bool:
    """原子写实现：读回现有 DataFrame → pd.concat → 写同目录 *.tmp → os.replace。

    进程在中途崩溃/被 kill 时，目标文件要么是旧完整版本、要么是新完整版本，
    绝不出现半行/乱码/BOM 错位的中间态。保持既有列顺序与 utf-8-sig 编码契约。
    返回 True 表示写入成功；False 表示校验失败被拒绝（不抛异常打断调用方）。
    """
    path = Path(output_file)
    # 文件不存在 → 新建（带表头）；文件已存在 → 读回现有 DataFrame 后整体重写
    if path.exists():
        try:
            old_df = pd.read_csv(path)
        except Exception as e:
            # 目标文件已损坏：拒绝叠加，先抛给调用方（fail-closed，不写坏数据）
            log.error("写入前发现目标 CSV 已损坏，拒绝继续写入: %s (%s: %s)",
                      output_file, type(e).__name__, e)
            raise CsvCorruptError(
                f"目标 CSV 已损坏，拒绝继续写入: {output_file} ({type(e).__name__}: {e})"
            ) from e
        # 必需列族缺失（截断/乱码/半行）即视为损坏：拒绝叠加，防止把坏数据当“历史遗留”
        missing = [c for c in CSV_COLUMNS if c not in old_df.columns]
        if missing:
            log.error("写入前发现目标 CSV 缺少必需列，拒绝继续写入: %s 缺 %s",
                      output_file, missing)
            raise CsvCorruptError(
                f"目标 CSV 缺少必需列，拒绝继续写入: {output_file} 缺 {missing}"
            )
        # 合法文件仅按契约列顺序重排（不增删列、不补空列）
        old_df = old_df[CSV_COLUMNS]
    else:
        old_df = pd.DataFrame(columns=CSV_COLUMNS)

    new_df = pd.DataFrame([row])[CSV_COLUMNS]
    combined = pd.concat([old_df, new_df], ignore_index=True)

    # 同目录临时文件 + os.replace 原子替换（跨平台；编辑器重启保留旧文件完整）
    tmp = path.with_name(path.name + ".tmp")
    try:
        combined.to_csv(tmp, index=False, encoding="utf-8-sig")
        os.replace(tmp, path)
    except Exception:
        # 写临时文件失败：清理残留 tmp，避免下次写入读到半成品
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise
    # 写成功后清理可能残留的旧 tmp（正常情况下 os.replace 已消费掉）
    try:
        if tmp.exists():
            tmp.unlink()
    except OSError:
        pass
    return True


def append_row(row: dict, output_file: str) -> bool:
    """追加一行（原子写，utf-8-sig，兼容 Excel/前端）。

    写前做 fail-closed 前置校验：必填字段（查询日期 + 五个价格字段）非空、
    价格可解析为数值；非法则 log.warning 并拒绝写入，返回 False。
    写入成功返回 True；目标文件已损坏时抛 CsvCorruptError（不覆盖坏数据）。
    """
    # 写出前剔除内部字段
    row = {k: v for k, v in row.items() if k != "_t"}
    valid, reason = _validate_row(row)
    if not valid:
        log.warning("append_row 拒绝写入（数据非法）: %s | row=%s", reason, row)
        return False
    return _append_row_atomic(row, output_file)


# ============================================================
#  单日完整流程（打码 + 多币种）
# ============================================================
def scrape_today():
    """
    每日模式：抓取今天 + 昨天（补充前一天防漏抓）的美元/港币牌价并追加到各自 CSV。
    每个币种单次执行、失败仅重试一次（最多 2 次），获取不到即放弃，次日再补抓前一天。
    打码平台 Key 缺失时安全跳过（不写入、不报错）。
    """
    if not is_daily:
        log.warning("补全(backfill)模式：中行历史接口已改为按当日查询，"
                    "无法批量回填历史日期；保留现有数据并退出（不删除任何数据）。")
        return

    if not _has_captcha_key():
        log.error("未配置打码平台 API Key（CAPSOLVER_API_KEY 或 TWOCAPTCHA_API_KEY），"
                  "无法过 Geetest v4，今日跳过。配置 Key 后重新运行。")
        return

    # 1) 取检索页，提取 captcha_id 并建立会话
    try:
        html = fetch_history_page()
    except Exception as e:
        log.error(f"无法获取历史检索页: {e}")
        return
    captcha_id = extract_captcha_id(html) or GEETEST_CAPTCHA_ID
    log.info(f"Geetest captcha_id = {captcha_id}")
    pageurl = HISTORY_PAGE_URL

    session = make_session()

    # 抓取日期范围：今天 + 昨天（补充前一天，防漏抓；昨天已写过会被去重跳过）。
    # 若“当天出问题→停→第二天再执行”，次日运行会抓 [昨天=今天, 今天=明天]，自然补回失败那天。
    BACKFILL_DAYS = 1
    target_dates = [date.today() - timedelta(days=BACKFILL_DAYS), date.today()]

    # gt4 解(gt) 仅首次或失效后求解一次，成功后跨币种、跨日期复用，避免无谓计费。
    gt: dict | None = None
    token: str | None = None
    for d in target_dates:
        ds = d.strftime("%Y-%m-%d")

        # 2) 去重：已写入该日期的币种直接跳过（幂等，防重复/补抓前一天）
        try:
            done = {c: load_done(f) for c, f in CURRENCIES.items()}
        except CsvCorruptError as e:
            # 损坏绝不静默当作“无历史数据”：中止本次运行，等待人工修复/告警
            log.error("CSV 损坏，本次抓取中止（拒绝按空集处理触发重复补全）: %s", e)
            return
        pending = {c: f for c, f in CURRENCIES.items() if ds not in done[c]}
        if not pending:
            log.info(f"{ds} 所有币种已存在记录，跳过")
            continue
        log.info(f"待抓取 {ds} 币种: {list(pending.keys())}")

        # 3) 每个币种独立查询：单次执行，仅当本次调用出错时才重试一次（最多 2 次）。
        for currency, output_file in pending.items():
            ok = False
            for attempt in range(1, MAX_ATTEMPTS_PER_CURRENCY + 1):  # 1 或 2
                try:
                    if gt is None:
                        gt = solve_geetest(captcha_id, pageurl)
                    data_list, token = query_day(session, d, currency, gt, token)
                    rows = parse_response(data_list, currency, d)
                    rec = select_daily_record(rows, d)
                except BocCaptchaError as e:
                    log.warning(f"  [{ds}/{currency}] 第{attempt}次 验证码失效: {e}")
                    gt = None  # 失效，下次尝试将重新求解
                    continue   # 进入下一次 attempt（已达上限则自动跳出）
                except Exception as e:
                    log.warning(f"  [{ds}/{currency}] 第{attempt}次 查询异常(超时/网络/解析): {e}")
                    # 注：Geetest v4 每天只过一次，gt 仍有效，不重置、直接复用重试 POST
                    continue

                if rec is None:
                    # 当日尚未发布牌价：属正常情况，非错误，不重试以免浪费成本
                    log.warning(f"  [{ds}/{currency}] 当日尚未发布牌价，本次跳过（不重试）")
                    ok = True
                    break
                rec.pop("_t", None)
                try:
                    appended = append_row(rec, output_file)
                except CsvCorruptError as e:
                    # 目标 CSV 已损坏：中止本次运行，等待人工修复（fail-closed）
                    log.error("CSV 损坏，本次抓取中止: %s", e)
                    return
                if not appended:
                    # 前置校验拒绝写入（必填缺失/价格非法）：不计入 done，
                    # 下次运行仍会重试该日，绝不把坏数据标记为“已完成”
                    log.error(f"  [{ds}/{currency}] 记录未通过写前校验，拒绝写入且不计入已完成")
                    ok = False
                    break
                done[currency].add(ds)
                log.info(f"  ✓ 已写入 {output_file} | {ds} {currency} {rec['发布时间']} 折算价={rec['中行折算价']}")
                ok = True
                break
            if not ok:
                log.error(f"  [{ds}/{currency}] 连续 {MAX_ATTEMPTS_PER_CURRENCY} 次失败，放弃该日该币种（次日将补抓前一天）")

    log.info(f"== 抓取结束 ==")


# ============================================================
#  主流程
# ============================================================
def main():
    log.info("=" * 60)
    log.info("中国银行外汇牌价抓取 v6.2 (Geetest v4 + 打码平台)")
    log.info(f"模式: {'每日' if is_daily else '补全(已禁用)'} | 运行日期: {date.today()}")
    log.info(f"打码供应商: {CAPTCHA_PROVIDER}")
    log.info("=" * 60)

    scrape_today()

    # 发送邮件通知（多币种 CSV 附件，沿用 send_daily_emails.py 约定）
    send_email_notification()


def send_email_notification():
    """发送邮件通知（多币种）"""
    try:
        # 加载环境变量
        load_dotenv()

        smtp_server = os.getenv('SMTP_SERVER')
        smtp_port = int(os.getenv('SMTP_PORT', '587'))
        sender_email = os.getenv('SENDER_EMAIL')
        sender_password = os.getenv('SENDER_PASSWORD')
        recipient_email = os.getenv('RECIPIENT_EMAIL')

        if not all([smtp_server, sender_email, sender_password, recipient_email]):
            log.warning("邮件配置不完整，跳过邮件发送")
            return

        # 读取各币种最新数据
        summaries = []
        for currency, output_file in CURRENCIES.items():
            if Path(output_file).exists():
                df = pd.read_csv(output_file)
                latest = df.tail(3).to_string(index=False)
                summaries.append(f"【{currency}】({len(df)} 条)\n{latest}")
            else:
                summaries.append(f"【{currency}】暂无数据")

        # 创建邮件内容
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = recipient_email
        msg['Subject'] = f"中国银行外汇牌价数据更新 - {datetime.now().strftime('%Y-%m-%d %H:%M')}"

        body = f"""
中国银行外汇牌价数据抓取完成！

运行时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

{chr(10).join(summaries)}

请查看附件获取完整数据。
        """
        msg.attach(MIMEText(body, 'plain', 'utf-8'))

        # 添加所有CSV文件作为附件
        for currency, output_file in CURRENCIES.items():
            if Path(output_file).exists():
                with open(output_file, 'rb') as attachment:
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(attachment.read())
                encoders.encode_base64(part)
                part.add_header(
                    'Content-Disposition',
                    f'attachment; filename= {output_file}'
                )
                msg.attach(part)

        # 发送邮件
        context = ssl.create_default_context()
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls(context=context)
            server.login(sender_email, sender_password)
            server.send_message(msg)

        log.info(f"邮件发送成功，收件人：{recipient_email}")

    except Exception as e:
        log.error(f"邮件发送失败: {e}")


if __name__ == "__main__":
    main()
