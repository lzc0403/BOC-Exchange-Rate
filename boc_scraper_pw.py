"""
中国银行外汇牌价抓取 - Playwright 版（应对 Geetest V4 bind 模式，自动拖滑块）
================================================================================
为什么需要这个版本？
  原 boc_scraper_v6.1.py 用 CapSolver 凭 websiteURL + captchaId 自动解题，
  但 BOC 的 Geetest V4 是 product:"bind" 模式，initGeetest() 只在点击"查询"
  按钮后才执行（见线上页面 JS）。CapSolver 机器人访问裸 URL 时页面上没有
  验证码控件 → 报 -50103 not captcha，无法自动解题。

本版做法（已实测可行的全自动路线）：
  1. 用 Playwright 打开 BOC 历史检索页；
  2. 对每个缺失日期：填日期 + 选币种 + 点击"查询" → 验证码初始化并弹出；
  3. 自动分析滑块缺口图片（fullbg 与 bg 做差，最亮列即缺口 x）+
     模拟人类轨迹把滑块拖到缺口；
  4. 前端验证成功后**自动发出** searchMultipleExchangeByXian 检索请求；
  5. 本脚本拦截该响应，解析并把当日汇率写库。

注意（重要）：BOC 的 Geetest token 是单次/单参数绑定的，不能复用——
所以必须让前端对每个日期真实验证+真实发请求，再拦截响应写库，
而不能截一次 token 后自己批量发请求（会返回 respStatus=02）。

依赖：pip install playwright opencv-python-headless numpy pandas && playwright install chromium
用法：
  python boc_scraper_pw.py
  END_DATE=2026-08-09 python boc_scraper_pw.py   # 系统时钟不可信时必填
"""
import os
import json
import re
import importlib.util
from datetime import date, timedelta
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
log = boc.log

# ============================================================
#  常量
# ============================================================
DATE_FMT = "%Y-%m-%d"
OUTAGE_START = date(2026, 6, 25)  # 缺口起点（与 verify_and_backfill 一致）
PRICE_RE = re.compile(r"^\d+(\.\d+)?$")
PRICE_FIELDS = ("现汇买入价", "现钞买入价", "现汇卖出价", "现钞卖出价", "中行折算价")


# ============================================================
#  Step 0: 缺失日期检测（与 verify_and_backfill 同口径）
# ============================================================
def _is_date_str(s):
    try:
        date.fromisoformat(str(s))
        return True
    except (ValueError, TypeError):
        return False


def find_missing(currency, output_file, usd_last, end_date, max_days=60):
    existing = load_done(output_file)
    existing_set = set(existing) if existing else set()
    # 注意：必须从 OUTAGE_START 起全量比对 existing，而不能只从"最新日期+1"开始——
    # 历史补抓可能乱序写入（如先写了 08-01/08-05/08-06），若只扫最新日期之后，
    # 会漏掉最新日期之前的空洞（08-02/03/04）。
    start = OUTAGE_START
    if end_date < start:
        return []  # 结束日期早于数据起点（常见于系统时钟回拨），无缺口
    missing = []
    d = start
    while d <= end_date:
        if d.strftime(DATE_FMT) not in existing_set:
            missing.append(d)
        d += timedelta(days=1)
    return sorted(missing[-max_days:])


# ============================================================
#  Step 1+2: Playwright 逐日期自动验证 + 拦截响应写库
# ============================================================
def acquire_and_backfill(dates_by_currency):
    """打开 BOC 页面，对每个缺失日期自动拖滑块验证；前端验证成功后自动
    发出检索请求，本函数拦截响应写库。全程无需人工、无需 CapSolver。"""
    from playwright.sync_api import sync_playwright
    import cv2, numpy as np, time, random

    _img_urls = {}
    _written = {}
    _cur = {}

    def _on_request(request):
        u = request.url
        if "assests/20/slide/" in u:
            if "fullbg" in u:
                _img_urls["fullbg"] = u
                log.info(f"  [req] fullbg 已捕获")
            elif "/bg/" in u:
                _img_urls["bg"] = u
                log.info(f"  [req] bg 已捕获")
            elif "/slice/" in u:
                _img_urls["slice"] = u
                log.info(f"  [req] slice 已捕获")

    def _on_response(response):
        u = response.url
        if "searchMultipleExchangeByXian" not in u:
            return
        cur = _cur.get("currency")
        d = _cur.get("date")
        if not cur or not d:
            return
        key = (cur, d.strftime(DATE_FMT))
        if key in _written:
            return
        try:
            j = response.json()
        except Exception:
            return
        rb = j.get("respBody", {})
        if rb.get("respStatus") != "00":
            return
        data = rb.get("data", [])
        rows = parse_response(data, cur, d)
        rec = select_daily_record(rows, d)
        if rec is None:
            log.warning(f"  [{d.strftime(DATE_FMT)}/{cur}] 响应无匹配记录，跳过")
            return
        for f in PRICE_FIELDS:
            v = str(rec.get(f, "")).strip()
            if not v or not PRICE_RE.match(v):
                log.warning(f"  [{d.strftime(DATE_FMT)}/{cur}] {f} 校验失败: {v}")
                return
        rec.pop("_t", None)
        append_row(rec, CURRENCIES[cur])
        _written[key] = True
        log.info(f"  ✓ 补齐 {cur} {d.strftime(DATE_FMT)} 折算价={rec.get('中行折算价', '?')}")

    def _compute_gap_x():
        """返回 (拖动原始距离, 图片宽度)。
        标定结论（_calib.py 14 轮）：直接用缺口 argmax/中心拖必被拒（偏右~40px），
        正确公式 = 缺口中心(ncenter) − 拼图块图形中心(scenter≈39.5)。"""
        full = cv2.imread(str(_THIS / "_pw_fullbg.png"))
        bg = cv2.imread(str(_THIS / "_pw_bg.png"))
        sl = cv2.imread(str(_THIS / "_pw_slice.png"))
        if full is None or bg is None or full.shape != bg.shape:
            return None, None
        diff = cv2.absdiff(full, bg)
        dg = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
        th = max(40.0, dg.mean() * 2.2)
        ys, xs = np.where(dg > th)
        if len(xs) == 0:
            return None, None
        ncenter = (int(xs.min()) + int(xs.max())) / 2.0
        # 拼图块图形中心（80x80 元素内）：优先用 alpha/深色掩码，退化用 40.0
        scenter = 40.0
        if sl is not None:
            if sl.shape[2] == 4:
                a = sl[:, :, 3]
                sy, sx = np.where(a > 128)
                if len(sx):
                    scenter = (int(sx.min()) + int(sx.max())) / 2.0
            else:
                g = cv2.cvtColor(sl, cv2.COLOR_BGR2GRAY)
                sy, sx = np.where(g < 200)
                if len(sx):
                    scenter = (int(sx.min()) + int(sx.max())) / 2.0
        dist_raw = ncenter - scenter
        return dist_raw, full.shape[1]  # 拖动原始距离、图片宽度

    def _img_track_width(page):
        for sel in (".geetest_bg", ".geetest_canvas_bg", ".geetest_widget"):
            el = page.locator(sel)
            if el.count():
                wb = el.first.bounding_box()
                if wb and wb["width"] > 0:
                    return wb["width"]
        return 300.0

    def _get_gap_x(timeout=120):
        # BOC Geetest 为 bind 模式：点查询后才开始加载整套 SDK（gt4.js→挑战→图片），
        # 首次冷加载实测要 25~40s，故等待窗口必须给足（默认 120 次 × 0.5s = 60s）。
        for _ in range(timeout):
            if "fullbg" in _img_urls and "bg" in _img_urls and "slice" in _img_urls:
                break
            time.sleep(0.5)
        else:
            return None, None
        try:
            r1 = requests.get(_img_urls["fullbg"], timeout=20)
            open(str(_THIS / "_pw_fullbg.png"), "wb").write(r1.content)
            r2 = requests.get(_img_urls["bg"], timeout=20)
            open(str(_THIS / "_pw_bg.png"), "wb").write(r2.content)
            r3 = requests.get(_img_urls["slice"], timeout=20)
            open(str(_THIS / "_pw_slice.png"), "wb").write(r3.content)
        except Exception:
            return None, None
        return _compute_gap_x()

    def _drag_natural(page, box, dist):
        """更拟人：缓起-加速-缓停 (ease-in-out / smoothstep) + 微超调 + 回拉精确位。
        Geetest 风控对纯 ease-out + 均匀停顿的模式识别率较高，加入超调回拉显著降低拒绝率。
        """
        sx = box["x"] + box["width"] / 2
        sy = box["y"] + box["height"] / 2
        page.mouse.move(sx, sy)
        page.mouse.down()
        overshoot = random.uniform(2.0, 5.5)
        target = sx + dist + overshoot
        steps = 70

        def ease_io(t):
            return t * t * (3 - 2 * t)

        for i in range(1, steps + 1):
            t = i / steps
            x = sx + (target - sx) * ease_io(t)
            y = sy + random.uniform(-1.8, 1.8)
            page.mouse.move(x, y)
            if random.random() < 0.22:
                time.sleep(random.uniform(0.05, 0.14))
            time.sleep(random.uniform(0.008, 0.020))
        time.sleep(random.uniform(0.05, 0.12))
        page.mouse.move(sx + dist, sy + random.uniform(-1.0, 1.0))
        time.sleep(random.uniform(0.08, 0.18))
        page.mouse.up()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        page = browser.new_page()
        page.on("request", _on_request)
        page.on("response", _on_response)
        page.goto(HISTORY_PAGE_URL, wait_until="load", timeout=60000)
        page.wait_for_timeout(2000)  # 等 Geetest bind 脚本就绪，否则首次点击不初始化
        log.info("页面与 Geetest bind 就绪")

        total = sum(len(v) for v in dates_by_currency.values())
        done = 0
        for currency, dates in dates_by_currency.items():
            for d in dates:
                _cur = {"currency": currency, "date": d}
                key = (currency, d.strftime(DATE_FMT))
                # 每个日期重新加载页面，保证 Geetest 处于干净的 bind 初始态，
                # 避免上一次验证成功的动画/状态污染下一次初始化（实测首日后会失败）。
                page.goto(HISTORY_PAGE_URL, wait_until="load", timeout=60000)
                page.wait_for_timeout(2000)
                _img_urls.clear()
                page.evaluate(
                    "(dd) => { $('#searchTime').val(dd); $('#searchTime').trigger('change'); $('#searchTime').blur(); }",
                    d.strftime(DATE_FMT))
                page.select_option("#pjname", currency)
                # Geetest bind 容器会盖住 #searchbtn 吞掉命中检测，必须用 force 直接派发
                # 受信任的点击事件，否则验证码不初始化（且上一日期的 ghost 浮层也会拦截）。
                try:
                    page.locator("#searchbtn").click(force=True, timeout=15000)
                except Exception as e:
                    log.error(f"  点击查询按钮失败: {e}")
                    continue
                log.info(f"→ {currency} {d.strftime(DATE_FMT)}：初始化验证码并自动拖")
                page.wait_for_timeout(500)
                last_bg = None
                max_attempts = 8
                for attempt in range(max_attempts):
                    if _written.get(key):
                        break
                    if attempt > 0:
                        # 重试：整页重驱（刷新+设日期+点查询），保证干净 Geetest 初始态。
                        # 不用 .geetest_refresh：它不可靠且会打断在途的验证/搜索请求。
                        page.goto(HISTORY_PAGE_URL, wait_until="load", timeout=60000)
                        page.wait_for_timeout(2000)
                        _img_urls.clear()
                        page.evaluate(
                            "(dd) => { $('#searchTime').val(dd); $('#searchTime').trigger('change'); $('#searchTime').blur(); }",
                            d.strftime(DATE_FMT))
                        page.select_option("#pjname", currency)
                        try:
                            page.locator("#searchbtn").click(force=True, timeout=15000)
                        except Exception as e:
                            log.error(f"  重试点击查询按钮失败: {e}")
                            continue
                    # 等验证码面板出现（SDK 冷加载慢，首次可到 30~40s）
                    panel_ok = False
                    for _ in range(90):
                        try:
                            if page.locator(".geetest_box_slide_button").bounding_box(timeout=800):
                                panel_ok = True
                                break
                        except Exception:
                            pass
                        time.sleep(0.5)
                    if not panel_ok:
                        log.error("  验证码面板未出现")
                        time.sleep(2)
                        continue
                    gx, img_w = _get_gap_x(timeout=90)
                    if gx is not None and img_w:
                        log.info(f"    [try{attempt}] 缺口 x={gx} img_w={img_w}")
                    if gx is None or not img_w:
                        log.error("  未捕获滑块图片，无法计算缺口")
                        time.sleep(2)
                        continue
                    if _img_urls.get("bg") == last_bg:
                        gx += random.choice([-7, -5, -3, 3, 5, 7])
                    last_bg = _img_urls.get("bg")
                    try:
                        btn = page.locator(".geetest_box_slide_button")
                        box = btn.bounding_box(timeout=8000)
                    except Exception:
                        box = None
                    if box is None:
                        time.sleep(3)
                        if _written.get(key):
                            break
                        continue
                    try:
                        tb = page.locator(".geetest_box_button").bounding_box(timeout=8000)
                        track_w = tb["width"] if tb else 302.0
                    except Exception:
                        track_w = 302.0
                    # 裁剪到合法拖动范围：argmax 可能因噪点落到 [0,300] 之外（如 239），
                    # 而最大可拖 = track_w - button_w ≈ 221，超出会被轨道卡住 → 失败。
                    button_w = box["width"]
                    max_drag = track_w - button_w - 4
                    dist = gx * (track_w / float(img_w))
                    dist = max(8.0, min(dist, max_drag))
                    start_x = box["x"]
                    _drag_natural(page, box, dist)
                    # 拖完后轮询：①写库成功 → 收工；②按钮复位回起点 → 验证失败，重试；
                    # ③按钮消失（成功动画）→ 继续等响应（实测响应可慢至 60~75s）。
                    waited = 0
                    while waited < 75 and not _written.get(key):
                        time.sleep(1)
                        waited += 1
                        try:
                            nb = page.locator(".geetest_box_slide_button").bounding_box(timeout=600)
                            if nb is None:
                                continue
                            if abs(nb["x"] - start_x) < 2:
                                log.info(f"    [try{attempt}] 验证失败（滑块复位）")
                                break
                        except Exception:
                            pass
                    if _written.get(key):
                        break
                if _written.get(key):
                    done += 1
                    log.info(f"  ✓ 完成 ({done}/{total})")
                else:
                    log.error(f"  ✗ 失败：{currency} {d.strftime(DATE_FMT)}")
        browser.close()
        log.info(f"== 补全结束：成功 {done}/{total} ==")
        return done, total


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


def _check_data_integrity(end_date):
    """校验今日数据是否成功写入所有币种。返回 (all_ok, missing_info)。

    在补全流程结束后（或无缺失直接跳过补全时）统一调用，确保每次运行
    都校验今日数据是否在位；缺失时通过 alert_notifier 发送告警邮件。
    """
    from alert_notifier import send_alert

    missing_currencies = []
    today_str = end_date.strftime(DATE_FMT)
    for currency, output_file in CURRENCIES.items():
        try:
            done = load_done(output_file)
            if today_str not in done:
                missing_currencies.append((currency, output_file))
        except Exception as e:
            log.error(f"校验 {currency} 数据时异常: {e}")
            missing_currencies.append((currency, output_file))

    if missing_currencies:
        details = "\n".join(
            f"  - {c} ({f}): 今日数据缺失" for c, f in missing_currencies
        )
        subject = f"[告警] BOC抓取数据缺失 - {end_date.strftime('%Y-%m-%d')}"
        body = (
            f"中国银行外汇牌价抓取告警\n\n"
            f"日期: {end_date.strftime('%Y-%m-%d')}\n"
            f"缺失币种:\n{details}\n\n"
            f"请检查 GitHub Actions 运行日志: "
            f"https://github.com/{os.getenv('GITHUB_REPOSITORY', 'lzc0403/BOC-Exchange-Rate')}/actions\n\n"
            f"此邮件为自动告警，仅在数据异常时发送。"
        )
        send_alert(subject, body)
        log.error("数据完整性校验失败，缺失币种: %s",
                  [c for c, _ in missing_currencies])
        return False, missing_currencies

    log.info("数据完整性校验通过：所有币种今日数据均在位")
    return True, []


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
        _check_data_integrity(end_date)
        return

    log.info("=" * 60)
    log.info("中国银行外汇牌价 · Playwright 自动补全（Geetest V4 bind 模式）")
    log.info(f"运行日期: {today}")
    log.info("=" * 60)

    done, total = acquire_and_backfill(missing_by_currency)
    log.info(f"== 总结：成功 {done}/{total} ==")

    _check_data_integrity(end_date)


if __name__ == "__main__":
    main()
