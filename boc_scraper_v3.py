"""
中国银行外汇牌价历史抓取 - v3 最终版
基于真实抓包: CaptchaServlet 返回 base64 文本 + Token 响应头
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

# ============== 配置 ==============
BASE        = "https://srh.bankofchina.com"
PAGE_URL    = f"{BASE}/search/whpj/search_cn.jsp"
CAPTCHA_URL = f"{BASE}/search/whpj/CaptchaServlet.jsp"

START_DATE  = date(2026, 5, 19)
END_DATE    = date(2026, 5, 19)
TARGET_HOUR = 10
OUTPUT_FILE = "boc_usd_cny.csv"

MAX_RETRIES = 8        # 单日最多重试(主要应对 OCR 失败)
MAX_PAGES   = 30       # 单日最多翻页
PAGE_SIZE   = 20       # 每页条数(暂定 20, 翻页参数实测后微调)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("boc.log", encoding="utf-8"),
              logging.StreamHandler()],
)
log = logging.getLogger(__name__)

ocr = ddddocr.DdddOcr(show_ad=False)


# ============== HTTP ==============
def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": PAGE_URL,
        "Origin": BASE,
    })
    s.get(PAGE_URL, timeout=15)   # 拿初始 JSESSIONID
    return s


def get_captcha(session: requests.Session) -> tuple[bytes, str]:
    """
    取验证码图片和 JWT.
    响应体 = base64 文本 (PNG)
    响应头 Token = JWT
    """
    r = session.get(CAPTCHA_URL, timeout=10)
    r.raise_for_status()
    body = r.text.strip()
    token = r.headers.get("Token") or r.headers.get("token")
    if not token:
        raise RuntimeError(f"响应头没有 Token. 全部头: {dict(r.headers)}")
    img_bytes = base64.b64decode(body)
    return img_bytes, token


def submit_query(session, d: date, captcha: str, token: str, first: int = 1) -> str:
    form = {
        "searchDate": d.strftime("%Y-%m-%d"),
        "pjname":     "美元",
        "head":       "head_620.js",
        "bottom":     "bottom_591.js",
        "first":      str(first),
        "token":      token,
        "captcha":    captcha,
    }
    r = session.post(PAGE_URL, data=form, timeout=15)
    r.encoding = "utf-8"
    return r.text


# ============== 解析 ==============
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


def parse_t(s: str):
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try: return datetime.strptime(s, fmt)
        except ValueError: pass
    return None


def captcha_failed(html: str) -> bool:
    return any(k in html for k in
               ("验证码错误", "验证码不正确", "验证码失效", "请重新输入"))


# ============== 单日抓取 ==============
def fetch_one_day(session, d: date) -> dict | None:
    log.info(f"=== {d} ===")
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            img_bytes, token = get_captcha(session)
        except Exception as e:
            log.warning(f"  #{attempt} 取验证码失败: {e}")
            time.sleep(1)
            continue

        captcha = ocr.classification(img_bytes).strip()
        captcha = re.sub(r"[^A-Za-z0-9]", "", captcha)
        if not (3 <= len(captcha) <= 6):
            log.info(f"  #{attempt} OCR={captcha!r} 太短/长, 跳过")
            continue
        log.info(f"  #{attempt} OCR={captcha}")

        # 翻页
        all_rows = []
        for page in range(1, MAX_PAGES + 1):
            # ★ 翻页参数公式(待实测确认): first = (page-1)*PAGE_SIZE + 1
            #   若实测发现 first 应为页码本身, 把下一行改成 first_val = page
            first_val = (page - 1) * PAGE_SIZE + 1
            html = submit_query(session, d, captcha, token, first=first_val)

            if captcha_failed(html):
                log.info(f"  #{attempt} 验证码错")
                break

            page_rows = parse_table(html)
            if not page_rows:
                if page == 1:
                    log.warning("  第 1 页没数据, 可能是验证码错或日期无效")
                break

            log.info(f"    第 {page} 页 {len(page_rows)} 条 "
                     f"({page_rows[0]['发布时间']} → {page_rows[-1]['发布时间']})")
            all_rows.extend(page_rows)

            # 早停: 本页最后一条已 < 10:00
            last_t = parse_t(page_rows[-1]["发布时间"])
            if last_t and last_t.date() == d and last_t.hour < TARGET_HOUR:
                break

            # 早停: 翻页参数失效(返回的内容跟上一页一样)
            if (page > 1 and len(all_rows) >= 2 * len(page_rows)
                and page_rows[0] == all_rows[-2 * len(page_rows)]):
                log.warning("    分页参数似乎无效, 停止翻页")
                break

        if not all_rows:
            continue

        # 挑 ≥10:00 最早一条
        cands = []
        for r in all_rows:
            t = parse_t(r["发布时间"])
            if t and t.date() == d and t.hour >= TARGET_HOUR:
                cands.append((t, r))

        if not cands:
            log.warning(f"  {d} 当天 10:00 后无记录(可能节假日或翻页未到位)")
            return None

        cands.sort(key=lambda x: x[0])
        log.info(f"  ✓ {cands[0][0]} 折算价={cands[0][1]['中行折算价']}")
        return cands[0][1]

    log.error(f"  ✗ {d} 重试 {MAX_RETRIES} 次后放弃")
    return None


# ============== 主流程 ==============
def load_done() -> set[str]:
    p = Path(OUTPUT_FILE)
    if not p.exists():
        return set()
    return set(pd.read_csv(p)["查询日期"].astype(str))


def append_row(row: dict):
    df = pd.DataFrame([row])
    header = not Path(OUTPUT_FILE).exists()
    df.to_csv(OUTPUT_FILE, mode="a", index=False, header=header,
              encoding="utf-8-sig")


def main():
    done = load_done()
    log.info(f"已抓 {len(done)} 天, 范围 {START_DATE} → {END_DATE}")

    session = make_session()
    cur = START_DATE
    while cur <= END_DATE:
        ds = cur.strftime("%Y-%m-%d")
        if ds in done:
            cur += timedelta(days=1); continue

        try:
            rec = fetch_one_day(session, cur)
            if rec:
                rec["查询日期"] = ds
                append_row(rec)
        except Exception as e:
            log.exception(f"{ds} 顶层异常: {e}")

        time.sleep(random.uniform(0.8, 1.8))
        cur += timedelta(days=1)


if __name__ == "__main__":
    main()
