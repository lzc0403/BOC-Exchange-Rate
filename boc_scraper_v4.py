"""
中国银行外汇牌价历史抓取 - v4 最终版
机制已完全确认:
  第 1 页: POST 搜索表单 (searchDate/pjname/first=1/captcha/token)
  第 2-N 页: POST pageform (page=N/pageCount/paramtk/token, 无需重新输验证码)
  数据时间倒序(最新在前), 找到第一条 <10:00 的记录即可停止翻页
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

START_DATE  = date(2025, 1, 1)
END_DATE    = date.today()
TARGET_HOUR = 10          # 抓 10:00 之后最早一条
OUTPUT_FILE = "boc_usd_cny.csv"
MAX_RETRIES = 8           # 单日验证码最多重试

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
#  HTTP
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
    """
    返回 (验证码图片bytes, captcha_token_JWT)
    CaptchaServlet 响应: body=base64文本, 响应头 Token=JWT
    """
    r = session.get(CAPTCHA_URL, timeout=10)
    r.raise_for_status()
    token = r.headers.get("Token") or r.headers.get("token")
    if not token:
        raise RuntimeError(f"响应头无 Token 字段. 全部头: {dict(r.headers)}")
    img_bytes = base64.b64decode(r.text.strip())
    return img_bytes, token


# ============================================================
#  表单提交
# ============================================================
def post(session: requests.Session, form: dict) -> str:
    r = session.post(PAGE_URL, data=form, timeout=15)
    r.encoding = "utf-8"
    return r.text


def submit_page1(session, d: date, captcha: str, token: str) -> str:
    """第 1 页: 携带验证码文本"""
    return post(session, {
        "searchDate": d.strftime("%Y-%m-%d"),
        "pjname":    "美元",
        "head":      "head_620.js",
        "bottom":    "bottom_591.js",
        "first":     "1",
        "token":     token,
        "captcha":   captcha,
    })


def submit_pageN(session, pageform: dict, page_no: int) -> str:
    """第 2-N 页: 使用 pageform 字段, 无需重输验证码"""
    form = dict(pageform)
    form["page"] = str(page_no)
    return post(session, form)


# ============================================================
#  解析
# ============================================================
def parse_table(html: str) -> list[dict]:
    """解析当前页所有美元数据行"""
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
    """
    从 HTML 中提取 pageform 的所有字段.
    服务端在第 1 页响应里注入了 paramtk / pageCount 等字段.
    """
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


# ============================================================
#  核心: 单日抓取
# ============================================================
def fetch_one_day(session, d: date) -> dict | None:
    log.info(f"=== {d} ===")

    for attempt in range(1, MAX_RETRIES + 1):
        # 1. 取验证码
        try:
            img_bytes, cap_token = get_captcha(session)
        except Exception as e:
            log.warning(f"  #{attempt} 取验证码失败: {e}")
            time.sleep(1)
            continue

        captcha = ocr.classification(img_bytes).strip()
        captcha = re.sub(r"[^A-Za-z0-9]", "", captcha)
        if not (3 <= len(captcha) <= 6):
            log.info(f"  #{attempt} OCR={captcha!r} 长度异常, 跳过")
            continue
        log.info(f"  #{attempt} OCR={captcha}")

        # 2. 提交第 1 页
        html1 = submit_page1(session, d, captcha, cap_token)
        if captcha_failed(html1):
            log.info(f"  #{attempt} 验证码错误, 重试")
            continue

        rows1 = parse_table(html1)
        if not rows1:
            log.warning(f"  #{attempt} 第 1 页无数据, 可能验证码失败或日期无效")
            continue

        # 3. 拿 pageform(含 paramtk / pageCount / token 等)
        pf = parse_pageform(html1)
        try:
            page_count = int(pf.get("pageCount", 1))
        except ValueError:
            page_count = 1

        log.info(f"    第 1 页 {len(rows1)} 条 "
                 f"({rows1[0]['发布时间']} → {rows1[-1]['发布时间']})  "
                 f"共 {page_count} 页")

        all_rows = list(rows1)

        # 4. 判断第 1 页是否已越过 10:00
        def crossed_target(rows):
            """当页最后一条是否已经早于 10:00"""
            if not rows:
                return False
            t = parse_time(rows[-1]["发布时间"])
            return t and t.date() == d and t.hour < TARGET_HOUR

        # 5. 翻页(第 2-N 页)
        if not crossed_target(rows1):
            for page_no in range(2, page_count + 1):
                html_p = submit_pageN(session, pf, page_no)
                rows_p = parse_table(html_p)
                if not rows_p:
                    log.warning(f"    第 {page_no} 页无数据, 停止")
                    break

                log.info(f"    第 {page_no} 页 {len(rows_p)} 条 "
                         f"({rows_p[0]['发布时间']} → {rows_p[-1]['发布时间']})")
                all_rows.extend(rows_p)

                # 更新 pageform(服务端可能在每页里刷新 paramtk)
                new_pf = parse_pageform(html_p)
                if new_pf:
                    pf = new_pf

                if crossed_target(rows_p):
                    break

                time.sleep(random.uniform(0.3, 0.7))

        # 6. 从所有行里挑出 ≥10:00 最早一条
        cands = []
        for r in all_rows:
            t = parse_time(r["发布时间"])
            if t and t.date() == d and t.hour >= TARGET_HOUR:
                cands.append((t, r))

        if not cands:
            log.warning(f"  {d} 10:00 后无记录(节假日或停牌)")
            return None

        cands.sort(key=lambda x: x[0])
        best_t, best_r = cands[0]
        log.info(f"  ✓ {best_t}  折算价={best_r['中行折算价']}")
        return best_r

    log.error(f"  ✗ {d} 重试 {MAX_RETRIES} 次后放弃")
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

        # 每天查询间随机等待, 避免被封
        time.sleep(random.uniform(0.8, 1.5))
        cur += timedelta(days=1)

    log.info("== 全部完成 ==")


if __name__ == "__main__":
    main()
