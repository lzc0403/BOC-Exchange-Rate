"""
中国银行外汇牌价抓取 - Playwright 版（应对 Geetest V4 bind 模式）
================================================================================
为什么需要这个版本？
  原 boc_scraper_v6.1.py 用 CapSolver 凭 websiteURL + captchaId 自动解题，
  但 BOC 的 Geetest V4 是 product:"bind" 模式，initGeetest() 只在点击"查询"
  按钮后才执行（见线上页面 JS）。CapSolver 机器人访问裸 URL 时页面上没有
  验证码控件 → 报 -50103 not captcha，无法自动解题。

本版做法（唯一能稳定拿到 token 的路线）：
  1. 用 Playwright 打开 BOC 历史检索页（origin = boc.cn，Geetest 接受）；
  2. 填日期 + 选币种 + 点击"查询" → 验证码初始化并弹出；
  3. 尝试用 CapSolver 自动解题（对 BOC 大概率仍失败，优雅降级）；
     失败则【人工在浏览器里拖一次滑块】完成验证；
  4. 监听 BOC 前端发出的 searchMultipleExchangeByXian 请求，
     从其请求体截获 4 个 token（lotNumber/captchaOutput/passToken/genTime）；
  5. 复用这套 token，直接用 requests 把全部缺失日期 × 币种补全写库。

token 复用依据：Geetest V4 的 validate token 在同一会话/短时间内对多次
API 调用有效，符合 BOC 前端"解一次、多次查询"的行为。

依赖：pip install playwright && playwright install chromium
用法：
  # 自动优先（CapSolver 可用时全自动；否则停在人工验证步骤等你拖滑块）
  python boc_scraper_pw.py
  # 强制人工验证（跳过 CapSolver 尝试）
  FORCE_MANUAL=1 python boc_scraper_pw.py
  # 指定结束日期（系统时钟不可信/回拨、或在 CI 中固定缺口窗口时必填）
  END_DATE=2026-08-20 python boc_scraper_pw.py
"""
import os
import sys
import json
import re
import importlib.util
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
import pandas as pd

# ============================================================
#  复用 boc_scraper_v6.1 的解析 / 写库 / 选样逻辑（不重写）
# ============================================================
_THIS = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("boc_v61", str(_THIS / "boc_scraper_v6.1.py"))
boc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(boc)

parse_response = boc.parse_response
select_daily_record = boc.select_daily_record
append_row = boc.append_row
load_done = boc.load_done
CURRENCIES = boc.CURRENCIES
HISTORY_PAGE_URL = boc.HISTORY_PAGE_URL
SEARCH_API_URL = boc.SEARCH_API_URL
CAPTCHA_PROVIDER = boc.CAPTCHA_PROVIDER
CAPSOLVER_API_KEY = boc.CAPSOLVER_API_KEY
TWOCAPTCHA_API_KEY = boc.TWOCAPTCHA_API_KEY
log = boc.log

# ============================================================
#  常量
# ============================================================
DATE_FMT = "%Y-%m-%d"
OUTAGE_START = date(2026, 6, 25)  # 缺口起点（与 verify_and_backfill 一致）
FORCE_MANUAL = os.getenv("FORCE_MANUAL", "") in ("1", "true", "yes")

PRICE_RE = re.compile(r"^\d+(\.\d+)?$")
PRICE_FIELDS = ("现汇买入价", "现钞买入价", "现汇卖出价", "现钞卖出价", "中行折算价")


# ============================================================
#  Step 0: 缺失日期检测（与 verify_and_backfill 同口径）
# ============================================================
def _is_date_str(s):
    try:
        date.fromisoformat(str(s));
        return True
    except (ValueError, TypeError):
        return False


def find_missing(currency, output_file, usd_last, end_date, max_days=60):
    existing = load_done(output_file)
    if existing:
        max_ex = max((date.fromisoformat(s) for s in existing if _is_date_str(s)), default=None)
        start = max(max_ex + timedelta(days=1), OUTAGE_START) if max_ex else OUTAGE_START
    else:
        start = max(OUTAGE_START, usd_last + timedelta(days=1))
    if end_date < start:
        return []  # 结束日期早于数据起点（常见于系统时钟回拨），无缺口
    missing = []
    d = start
    while d <= end_date:
        if d.strftime(DATE_FMT) not in existing:
            missing.append(d)
        d += timedelta(days=1)
    return sorted(missing[-max_days:])


# ============================================================
#  Step 1: 用 CapSolver 尝试自动解题（对 BOC 大概率失败，优雅降级）
# ============================================================
def try_capsolver_auto(captcha_id, page_url):
    """尝试 CapSolver 自动解题。成功返回 token dict，失败返回 None。"""
    if not CAPSOLVER_API_KEY or FORCE_MANUAL:
        return None
    try:
        import capsolver
        capsolver.api_key = CAPSOLVER_API_KEY
        sol = capsolver.solve({
            "type": "GeeTestTaskProxyLess",
            "websiteURL": page_url,
            "captchaId": captcha_id,
            "geetestApiServerSubdomain": "immvs.igtb.bankofchina.com",
        })
        tok = {
            "lotNumber": sol["lot_number"],
            "captchaOutput": sol["captcha_output"],
            "passToken": sol["pass_token"],
            "genTime": str(sol["gen_time"]),
        }
        log.info("CapSolver 自动解题成功")
        return tok
    except Exception as e:  # noqa: BLE001
        log.warning(f"CapSolver 自动解题失败（将退回人工验证）: {type(e).__name__}: {e}")
        return None


# ============================================================
#  Step 2: Playwright 驱动页面，获取 token（自动失败则人工）
# ============================================================
def acquire_tokens(dates, currencies):
    """
    打开 BOC 页面，初始化验证码，获取可用于 searchMultipleExchangeByXian 的 token。
    返回 token dict；若全程失败返回 None。
    """
    from playwright.sync_api import sync_playwright

    # 先尝试 CapSolver 自动（仅当你配置且未强制人工）
    # 注：BOC 的 bind 模式 CapSolver 通常 -50103，这里只是尽最大努力
    captcha_id = boc.GEETEST_CAPTCHA_ID
    auto = try_capsolver_auto(captcha_id, HISTORY_PAGE_URL)
    if auto:
        return auto

    # ---- 人工验证路径 ----
    log.info("启动 Playwright，请在弹出的浏览器中手动完成 Geetest 验证（拖一次滑块）...")
    captured = {}

    def _on_request(request):
        # 拦截 BOC 前端发出的检索请求，从请求体截获 4 个 token
        if SEARCH_API_URL.split("//")[-1] in request.url and request.method == "POST":
            try:
                body = json.loads(request.post_data or "{}")
                rb = body.get("reqBody", {})
                if all(k in rb for k in ("lotNumber", "captchaOutput", "passToken", "genTime")):
                    captured.update({
                        "lotNumber": rb["lotNumber"],
                        "captchaOutput": rb["captchaOutput"],
                        "passToken": rb["passToken"],
                        "genTime": rb["genTime"],
                    })
                    log.info("已截获 Geetest token（人工验证成功）")
            except Exception:
                pass

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # 人工需可见窗口
        page = browser.new_page()
        page.on("request", _on_request)
        page.goto(HISTORY_PAGE_URL, wait_until="load", timeout=60000)

        # 填第一个日期 + 第一个币种，点查询以初始化并弹出验证码
        first_date = dates[0]
        first_cur = list(currencies.keys())[0]
        page.fill("#searchTime", first_date.strftime("%Y-%m-%d"))
        page.select_option("#pjname", first_cur)
        page.click("#searchbtn")

        # 等待用户完成验证：监听请求截获 token 后自动继续，最长等 5 分钟
        import time
        deadline = time.time() + 300
        while not captured and time.time() < deadline:
            time.sleep(1)
        if not captured:
            log.warning("5 分钟内未截获 token，验证可能未完成（请确认滑块已拖完）")
        browser.close()

    return captured or None


# ============================================================
#  Step 3: 用 token 直接补全所有缺失日期（requests，复用 token）
# ============================================================
def backfill_with_token(token, missing_by_currency, session):
    filled, failed, skipped = {}, {}, {}
    for currency, dates in missing_by_currency.items():
        filled.setdefault(currency, [])
        failed.setdefault(currency, [])
        skipped.setdefault(currency, [])
        for d in dates:
            ok = False
            try:
                req_body = {
                    "pjrq": d.strftime(DATE_FMT),
                    "pjname": currency,
                    "lotNumber": token["lotNumber"],
                    "captchaOutput": token["captchaOutput"],
                    "passToken": token["passToken"],
                    "genTime": token["genTime"],
                    "pageSize": "1000",
                    "page": "1",
                }
                payload = {"reqHeader": {}, "reqBody": req_body}
                r = session.post(SEARCH_API_URL, json=payload,
                                 headers={"content-type": "application/json"}, timeout=30)
                r.encoding = "utf-8"
                j = r.json()
                rb = j.get("respBody", {})
                if rb.get("respStatus") != "00":
                    raise RuntimeError(f"接口返回 {rb.get('respStatus')}（token 可能过期，请重跑）")
                data = rb.get("data", [])
                rows = parse_response(data, currency, d)
                rec = select_daily_record(rows, d)
                if rec is None:
                    skipped[currency].append(d)
                    continue
                # 校验
                for f in PRICE_FIELDS:
                    v = str(rec.get(f, "")).strip()
                    if not v or not PRICE_RE.match(v):
                        raise ValueError(f"{f} 校验失败: {v}")
                rec.pop("_t", None)
                append_row(rec, CURRENCIES[currency])
                filled[currency].append(d)
                ok = True
            except Exception as e:  # noqa: BLE001
                log.warning(f"  [{d.strftime(DATE_FMT)}/{currency}] 失败: {e}")
                failed[currency].append((d, str(e)))
            if ok:
                log.info(f"  ✓ 补齐 {currency} {d.strftime(DATE_FMT)} 折算价={rec['中行折算价'] if ok else '?'}")
    return {"filled": filled, "failed": failed, "skipped": skipped}


# ============================================================
#  主流程
# ============================================================
def _parse_end_date():
    """结束日期：优先用 END_DATE 环境变量（ISO 日期），否则取系统今天。
    注：部分沙箱/容器系统时钟回拨到数据之前，会导致'缺失=0'的假象，
    此时请显式传入 END_DATE=YYYY-MM-DD。"""
    s = os.getenv("END_DATE", "").strip()
    if s:
        try:
            return date.fromisoformat(s)
        except ValueError:
            log.warning(f"END_DATE 解析失败({s})，回退到系统今天")
    return date.today()


def main():
    end_date = _parse_end_date()
    today = end_date
    usd_done = load_done(CURRENCIES["美元"])
    usd_last = max((date.fromisoformat(s) for s in usd_done if _is_date_str(s)),
                   default=OUTAGE_START - timedelta(days=1))
    missing_by_currency = {
        c: find_missing(c, f, usd_last, today)
        for c, f in CURRENCIES.items()
    }
    total_missing = sum(len(v) for v in missing_by_currency.values())
    log.info(f"检测到缺失: 美元 {len(missing_by_currency['美元'])} 天, "
             f"港币 {len(missing_by_currency['港币'])} 天（共 {total_missing} 天）")
    if total_missing == 0:
        log.info("无缺失，无需补全")
        return

    log.info("=" * 60)
    log.info("中国银行外汇牌价 · Playwright 补全（Geetest V4 bind 模式）")
    log.info(f"运行日期: {today} | CapSolver自动: {'关' if FORCE_MANUAL or not CAPSOLVER_API_KEY else '开'}")
    log.info("=" * 60)

    token = acquire_tokens(
        [d for d in missing_by_currency["美元"]], CURRENCIES
    )
    if not token:
        log.error("未能获取 Geetest token（CapSolver 失败且未人工验证），退出。")
        return

    session = boc.make_session()
    result = backfill_with_token(token, missing_by_currency, session)

    # 报告
    for c in CURRENCIES:
        f = len(result["filled"].get(c, []))
        fl = len(result["failed"].get(c, []))
        sk = len(result["skipped"].get(c, []))
        log.info(f"  · {c}: 已补 {f} | 跳过 {sk} | 失败 {fl}")
    log.info("== 补全结束 ==")


if __name__ == "__main__":
    main()
