"""
中国银行外汇牌价历史抓取 - v5.1 修复版
修复翻页参数失效、优化节假日判定、防止有效数据被误跳过
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
START_DATE  = date(2025, 1, 1)
END_DATE    = date.today()
TARGET_HOUR = 10          # 抓每天 10:00 之后最早一条
OUTPUT_FILE = "boc_usd_cny.csv"

MAX_DAY_ATTEMPTS = 8      # 单日最大重试次数
PAGE_RETRY       = 3      # 单页最大重试次数
SESSION_REFRESH  = 50     # 缩短刷新周期，防 Session 频繁过期

BASE        = "https://srh.bankofchina.com"
PAGE_URL    = f"{BASE}/search/whpj/search_cn.jsp"
CAPTCHA_URL = f"{BASE}/search/whpj/CaptchaServlet.jsp"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

SERVER_ERRORS = ("系统繁忙", "请重新输入", "重新登录", "session",
                 "验证码错误", "验证码不正确", "验证码失效")

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
#  Session 管理
# ============================================================
def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": PAGE_URL,
        "Origin": BASE,
    })
    try:
        s.get(PAGE_URL, timeout=15)
    except Exception as e:
        log.warning(f"Session 初始化警告: {e}")
    return s


# ============================================================
#  验证码
# ============================================================
def get_captcha(session: requests.Session) -> tuple[bytes, str]:
    r = session.get(CAPTCHA_URL, timeout=10)
    r.raise_for_status()
    token = r.headers.get("Token") or r.headers.get("token")
    if not token:
        raise RuntimeError(f"响应头无 Token")
    return base64.b64decode(r.text.strip()), token


# ============================================================
#  表单提交
# ============================================================
def post_form(session: requests.Session, form: dict) -> str:
    r = session.post(PAGE_URL, data=form, timeout=20)
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
#  HTML 解析
# ============================================================
def parse_table(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    # 兼容中行可能存在的两种经典表格类名
    table = soup.find("table", class_="BOC_main publish") or soup.find("table")
    if not table:
        return []
    
    for tr in table.find_all("tr"):
        tds = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(tds) >= 7 and "美元" in tds[0]:
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


def has_server_error(html: str) -> bool:
    return any(k in html for k in SERVER_ERRORS)


def crossed_target(rows: list[dict], d: date) -> bool:
    if not rows:
        return False
    t = parse_time(rows[-1]["发布时间"])
    return bool(t and t.date() == d and t.hour < TARGET_HOUR)


# ============================================================
#  带重试的单页获取
# ============================================================
def fetch_page_with_retry(
    session, pf: dict, page_no: int, d: date
) -> tuple[list[dict], dict]:
    for attempt in range(1, PAGE_RETRY + 1):
        try:
            html = submit_pageN(session, pf, page_no)
        except Exception as e:
            log.warning(f"    第{page_no}页第{attempt}次网络异常: {e}")
            time.sleep(attempt * 2.0)
            continue

        if has_server_error(html) and not parse_table(html):
            log.warning(f"    第{page_no}页第{attempt}次服务端错误提示")
            time.sleep(attempt * 1.5)
            continue

        rows = parse_table(html)
        if rows:
            new_pf = parse_pageform(html)
            if new_pf:
                # 修复核心：只更新核心控制流参数，不破坏原有表单基本盘
                pf.update({k: v for k, v in new_pf.items() if k in ["paramtk", "pageCount"]})
            return rows, pf

        preview = re.sub(r"\s+", " ", html[:100])
        log.warning(f"    第{page_no}页第{attempt}次空响应. 预览: {preview!r}")
        time.sleep(attempt * 2.0)

    return [], pf


# ============================================================
#  单日完整流程
# ============================================================
def fetch_one_day(session, d: date) -> dict | None:
    log.info(f"=== {d} ===")

    for day_attempt in range(1, MAX_DAY_ATTEMPTS + 1):
        try:
            img_bytes, cap_token = get_captcha(session)
        except Exception as e:
            log.warning(f"  #{day_attempt} 取验证码失败: {e}")
            time.sleep(2)
            continue

        captcha = re.sub(r"[^A-Za-z0-9]", "", ocr.classification(img_bytes).strip())
        if not (3 <= len(captcha) <= 6):
            continue

        try:
            html1 = submit_page1(session, d, captcha, cap_token)
        except Exception as e:
            log.warning(f"  #{day_attempt} 第1页网络异常: {e}")
            time.sleep(2)
            continue

        if has_server_error(html1) and not parse_table(html1):
            continue

        rows1 = parse_table(html1)
        if not rows1:
            # 节假日快速判定：如果返回的内容里明确说没有记录，重试2次都这样就确认为节假日
            if "继往开来" in html1 or "暂无记录" in html1 or "无记录" in html1:
                if day_attempt >= 2:
                    log.info(f"  {d} 确认为无数据日(节假日/停牌)")
                    return None
            log.warning(f"  #{day_attempt} 第1页无数据，尝试重试")
            continue

        pf = parse_pageform(html1)
        try:
            page_count = int(pf.get("pageCount", 1))
        except ValueError:
            page_count = 1

        log.info(f"    第 1 页 {len(rows1)} 条 共 {page_count} 页")
        all_rows = list(rows1)
        day_ok = True

        # 翻页逻辑
        if not crossed_target(rows1, d):
            for page_no in range(2, page_count + 1):
                rows_p, pf = fetch_page_with_retry(session, pf, page_no, d)

                if not rows_p:
                    log.warning(f"  第{page_no}页翻页失败")
                    day_ok = False
                    break

                all_rows.extend(rows_p)
                if crossed_target(rows_p, d):
                    break

                time.sleep(random.uniform(0.4, 0.8))

        # 修复核心：即使翻页中途有失败(day_ok=False)，但如果当前已经抓到的数据里有满足要求的，
        # 就不应该废弃整天，允许其向下筛选。
        cands = [(parse_time(r["发布时间"]), r) for r in all_rows]
        cands = [(t, r) for t, r in cands if t and t.date() == d and t.hour >= TARGET_HOUR]

        if cands:
            cands.sort(key=lambda x: x[0])
            best_t, best_r = cands[0]
            log.info(f"  ✓ {best_t}  折算价={best_r['中行折算价']}")
            return best_r
        
        if not day_ok:
            log.info(f"  #{day_attempt} 翻页未完成且无目标数据，重头尝试本交易日")
            continue

        log.warning(f"  {d} 当天无 10:00 后数据")
        return None

    log.error(f"  ✗ {d} 已达最大重试次数，跳过")
    return None


# ============================================================
#  主流程
# ============================================================
def load_done() -> set[str]:
    p = Path(OUTPUT_FILE)
    if not p.exists():
        return set()
    try:
        df = pd.read_csv(p)
        return set(df["查询日期"].astype(str))
    except Exception:
        return set()


def append_row(row: dict):
    df = pd.DataFrame([row])
    header = not Path(OUTPUT_FILE).exists()
    df.to_csv(OUTPUT_FILE, mode="a", index=False, header=header, encoding="utf-8-sig")


def main():
    done = load_done()
    all_dates = [START_DATE + timedelta(days=i) for i in range((END_DATE - START_DATE).days + 1)]
    pending = [d for d in all_dates if d.strftime("%Y-%m-%d") not in done]

    log.info(f"总范围: {START_DATE} → {END_DATE} | 已有: {len(done)} 天 | 待补抓: {len(pending)} 天")

    session = make_session()
    processed = 0

    for d in pending:
        ds = d.strftime("%Y-%m-%d")

        if processed > 0 and processed % SESSION_REFRESH == 0:
            log.info(f"--- 定期重置 Session (已处理 {processed} 天) ---")
            session = make_session()

        try:
            rec = fetch_one_day(session, d)
            if rec:
                rec["查询日期"] = ds
                append_row(rec)
            else:
                # 即使是确定无数据的节假日，也写入一条空档或写一条日志记录，防止下次重复抓取
                # 这里选择不写入CSV，让它留在pending里，或者您可以通过建立一个"休市记录"防止反复踩坑。
                pass
        except Exception as e:
            log.exception(f"{ds} 遇到突发异常: {e}")
            session = make_session()

        processed += 1
        if processed % 10 == 0:
            log.info(f">>> 补抓进度: {processed}/{len(pending)} ({processed/len(pending)*100:.1f}%) <<<")

        time.sleep(random.uniform(0.6, 1.2))

    log.info(f"== 运行结束 ==")


if __name__ == "__main__":
    main()