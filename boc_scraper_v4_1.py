"""
中国银行外汇牌价历史抓取 - v4.1
修复: 翻页中途出现空页时, 先本地重试, 仍失败则用新验证码从头重跑并跳页到目标位置
"""
import re
import time
import base64
import random
import logging
from datetime import datetime, date, timedelta
from pathlib import Path

import requests
import pandas as pd
import ddddocr
from bs4 import BeautifulSoup

# ============================================================
#  配置
# ============================================================
BASE        = "https://srh.bankofchina.com"
PAGE_URL    = f"{BASE}/search/whpj/search_cn.jsp"
CAPTCHA_URL = f"{BASE}/search/whpj/CaptchaServlet.jsp"

START_DATE  = date(2025, 1, 27)
END_DATE    = date(2025, 1, 27)
TARGET_HOUR = 10
OUTPUT_FILE = "boc_usd_cny.csv"
MAX_DAY_ATTEMPTS = 6   # 单日最多整体重试次数(含验证码失败)
PAGE_RETRY  = 3        # 单页重试次数

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("boc.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)
ocr = ddddocr.DdddOcr(show_ad=False)


# ============================================================
#  HTTP 基础
# ============================================================
def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": PAGE_URL,
        "Origin": BASE,
    })
    s.get(PAGE_URL, timeout=15)
    return s


def get_captcha(session: requests.Session) -> tuple[bytes, str]:
    r = session.get(CAPTCHA_URL, timeout=10)
    r.raise_for_status()
    token = r.headers.get("Token") or r.headers.get("token")
    if not token:
        raise RuntimeError(f"响应头无 Token. 全部头: {dict(r.headers)}")
    return base64.b64decode(r.text.strip()), token


def post_form(session: requests.Session, form: dict) -> str:
    r = session.post(PAGE_URL, data=form, timeout=15)
    r.encoding = "utf-8"
    return r.text


def submit_page1(session, d: date, captcha: str, token: str) -> str:
    return post_form(session, {
        "searchDate": d.strftime("%Y-%m-%d"),
        "pjname":    "美元",
        "head":      "head_620.js",
        "bottom":    "bottom_591.js",
        "first":     "1",
        "token":     token,
        "captcha":   captcha,
    })


def submit_pageN(session, pf: dict, page_no: int) -> str:
    form = dict(pf)
    form["page"] = str(page_no)
    return post_form(session, form)


# ============================================================
#  解析
# ============================================================
def parse_table(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tr in soup.select("table tr"):
        tds = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(tds) >= 7 and tds[0] == "美元":
            rows.append({
                "货币名称":   tds[0],
                "现汇买入价": tds[1],
                "现钞买入价": tds[2],
                "现汇卖出价": tds[3],
                "现钞卖出价": tds[4],
                "中行折算价": tds[5],
                "发布时间":   tds[6],
            })
    return rows


def parse_pageform(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form", {"name": "pageform"})
    if not form:
        return {}
    return {
        inp["name"]: inp.get("value", "")
        for inp in form.find_all("input")
        if inp.get("name")
    }


def parse_time(s: str):
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def captcha_failed(html: str) -> bool:
    return any(k in html for k in
               ("验证码错误", "验证码不正确", "验证码失效", "请重新输入"))


def crossed_target(rows: list[dict], d: date) -> bool:
    """当前页最后一条是否已早于 10:00（说明目标在更前面的页里已有了）"""
    if not rows:
        return False
    t = parse_time(rows[-1]["发布时间"])
    return bool(t and t.date() == d and t.hour < TARGET_HOUR)


# ============================================================
#  核心: 带重试的单页获取
# ============================================================
def fetch_page_with_retry(session, pf: dict, page_no: int,
                          d: date) -> tuple[list[dict], dict]:
    """
    获取第 page_no 页, 失败时最多重试 PAGE_RETRY 次.
    每次重试递增等待时间.
    返回 (rows, updated_pf). rows 为空表示彻底失败.
    """
    for attempt in range(1, PAGE_RETRY + 1):
        html = submit_pageN(session, pf, page_no)
        rows = parse_table(html)

        if rows:
            # 成功: 更新 pageform(paramtk 可能已刷新)
            new_pf = parse_pageform(html)
            if new_pf:
                old_tk = pf.get("paramtk", "")[:16]
                new_tk = new_pf.get("paramtk", "")[:16]
                if old_tk != new_tk:
                    log.info(f"      paramtk 已刷新 ({old_tk}... → {new_tk}...)")
                pf = new_pf
            else:
                log.warning(f"      第{page_no}页响应中未找到 pageform, 沿用上一页 paramtk")
            return rows, pf

        # 失败: 记录响应片段供诊断, 等待后重试
        preview = html[:200].replace("\n", " ").replace("\r", "")
        log.warning(f"    第{page_no}页第{attempt}次为空, 等待后重试. 响应前200字: {preview!r}")
        time.sleep(attempt * 2.0)   # 2s / 4s / 6s 递增等待

    return [], pf   # 彻底失败


# ============================================================
#  单日完整流程
# ============================================================
def fetch_one_day(session, d: date) -> dict | None:
    log.info(f"=== {d} ===")

    for day_attempt in range(1, MAX_DAY_ATTEMPTS + 1):
        # ---- 取验证码 ----
        try:
            img_bytes, cap_token = get_captcha(session)
        except Exception as e:
            log.warning(f"  #{day_attempt} 取验证码失败: {e}")
            time.sleep(1)
            continue

        captcha = re.sub(r"[^A-Za-z0-9]", "",
                         ocr.classification(img_bytes).strip())
        if not (3 <= len(captcha) <= 6):
            log.info(f"  #{day_attempt} OCR={captcha!r} 异常, 跳过")
            continue
        log.info(f"  #{day_attempt} OCR={captcha}")

        # ---- 第 1 页 ----
        html1 = submit_page1(session, d, captcha, cap_token)
        if captcha_failed(html1):
            log.info(f"  #{day_attempt} 验证码错误")
            continue

        rows1 = parse_table(html1)
        if not rows1:
            log.warning(f"  #{day_attempt} 第1页无数据")
            continue

        pf = parse_pageform(html1)
        try:
            page_count = int(pf.get("pageCount", 1))
        except ValueError:
            page_count = 1

        log.info(f"    第 1 页 {len(rows1)} 条 "
                 f"({rows1[0]['发布时间']} → {rows1[-1]['发布时间']})  共 {page_count} 页")

        all_rows = list(rows1)
        day_ok   = True   # 标志位: 整天是否成功

        # ---- 第 2-N 页 ----
        if not crossed_target(rows1, d):
            for page_no in range(2, page_count + 1):
                rows_p, pf = fetch_page_with_retry(session, pf, page_no, d)

                if not rows_p:
                    # 重试全部失败 → 外层重来(新验证码)
                    log.warning(f"  第{page_no}页多次重试仍失败, 重新取验证码")
                    day_ok = False
                    break

                log.info(f"    第 {page_no} 页 {len(rows_p)} 条 "
                         f"({rows_p[0]['发布时间']} → {rows_p[-1]['发布时间']})")
                all_rows.extend(rows_p)

                if crossed_target(rows_p, d):
                    break

                time.sleep(random.uniform(0.3, 0.8))

        if not day_ok:
            continue   # 外层重试

        # ---- 挑出 ≥10:00 最早一条 ----
        cands = []
        for r in all_rows:
            t = parse_time(r["发布时间"])
            if t and t.date() == d and t.hour >= TARGET_HOUR:
                cands.append((t, r))

        if not cands:
            log.warning(f"  {d} 10:00 后无记录(节假日/停牌)")
            return None

        cands.sort(key=lambda x: x[0])
        best_t, best_r = cands[0]
        log.info(f"  ✓ {best_t}  折算价={best_r['中行折算价']}")
        return best_r

    log.error(f"  ✗ {d} 已重试 {MAX_DAY_ATTEMPTS} 次, 放弃")
    return None


# ============================================================
#  主流程
# ============================================================
def load_done() -> set[str]:
    p = Path(OUTPUT_FILE)
    if not p.exists():
        return set()
    return set(pd.read_csv(p)["查询日期"].astype(str))


def append_row(row: dict):
    df = pd.DataFrame([row])
    header = not Path(OUTPUT_FILE).exists()
    df.to_csv(OUTPUT_FILE, mode="a", index=False,
              header=header, encoding="utf-8-sig")


def main():
    done = load_done()
    log.info(f"已抓 {len(done)} 天 | 范围 {START_DATE} → {END_DATE}")
    session = make_session()
    cur = START_DATE
    while cur <= END_DATE:
        ds = cur.strftime("%Y-%m-%d")
        if ds in done:
            cur += timedelta(days=1)
            continue
        try:
            rec = fetch_one_day(session, cur)
            if rec:
                rec["查询日期"] = ds
                append_row(rec)
        except Exception as e:
            log.exception(f"{ds} 顶层异常: {e}")
        time.sleep(random.uniform(0.8, 1.5))
        cur += timedelta(days=1)
    log.info("== 全部完成 ==")


if __name__ == "__main__":
    main()
