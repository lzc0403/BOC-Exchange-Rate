"""
中国银行外汇牌价历史抓取 - v5.6 终极修正版
1. 【彻底修复】还原原版全表扫描解析（soup.select），纠正因表格定位失败导致的无响应跳过 Bug
2. 防砸崩保护：对 ddddocr 识别增加底层硬崩溃异常捕获
3. 智能兼容10点前数据：如果当天数据全在10点前发布（如节假日清晨/零点牌价），自动采纳当天最新的一条
"""
import re
import time
import base64
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
import ddddocr
from bs4 import BeautifulSoup
import os
import os
from dotenv import load_dotenv

# ============================================================
#  配置（支持环境变量覆盖）
# ============================================================
# 默认全量范围：2023-01-01 ~ 昨天
DEFAULT_START = date(2023, 1, 1)
# 环境变量 DAILY_MODE=true 时，尝试抓取当天数据
is_daily = os.getenv("DAILY_MODE", "").lower() in ("true", "1", "yes")
if is_daily:
    START_DATE = date.today()
    END_DATE   = date.today()
else:
    START_DATE = DEFAULT_START
    END_DATE   = date.today() - timedelta(days=1)
TARGET_HOUR = 10          # 优先抓每天 10:00 之后最早一条

# 多币种配置：币种中文名 → 输出文件名
CURRENCIES = {
    "美元": "boc_usd_cny.csv",
    "港币": "boc_hkd_cny.csv",
}

MAX_DAY_ATTEMPTS = 8      # 单日最大重试次数
PAGE_RETRY       = 3      # 单页最大重试次数
SESSION_REFRESH  = 50     # 缩短刷新周期，防 Session 频繁过期

BASE        = "https://srh.bankofchina.com"
PAGE_URL    = f"{BASE}/search/whpj/search_cn.jsp"
CAPTCHA_URL = f"{BASE}/search/whpj/CaptchaServlet.jsp"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# 只有当完全解析不出美元表格，且包含以下错误词时才触发重试
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


def submit_page1(session, d: date, captcha: str, token: str, currency: str = "美元") -> str:
    return post_form(session, {
        "searchDate": d.strftime("%Y-%m-%d"),
        "pjname":    currency,
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
#  HTML 解析（回归原版最稳健的全盲扫逻辑）
# ============================================================
def parse_table(html: str, currency: str = "美元") -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    # 还原：直接抓取网页中所有的 tr，避免被外层容器结构干扰
    for tr in soup.select("table tr"):
        tds = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(tds) >= 7 and tds[0] == currency:
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
    # 只要当前页最后一条数据的日期已经跨入前一天，说明当天的历史数据已经全捞完了，停止翻页
    if t and t.date() < d:
        return True
    return bool(t and t.date() == d and t.hour < TARGET_HOUR)


# ============================================================
#  带重试的单页获取
# ============================================================
def fetch_page_with_retry(
    session, pf: dict, page_no: int, d: date, currency: str = "美元"
) -> tuple[list[dict], dict]:
    for attempt in range(1, PAGE_RETRY + 1):
        try:
            html = submit_pageN(session, pf, page_no)
        except Exception as e:
            log.warning(f"    第{page_no}页第{attempt}次网络异常: {e}")
            time.sleep(attempt * 2.0)
            continue

        rows = parse_table(html, currency)
        if rows:
            new_pf = parse_pageform(html)
            if new_pf:
                pf.update({k: v for k, v in new_pf.items() if k in ["paramtk", "pageCount"]})
            return rows, pf

        if has_server_error(html):
            log.warning(f"    第{page_no}页第{attempt}次服务端异常或空响应提示")
            time.sleep(attempt * 1.5)
            continue

        time.sleep(attempt * 2.0)

    return [], pf


# ============================================================
#  单日完整流程
# ============================================================
def fetch_one_day(session, d: date, currency: str = "美元") -> dict | None:
    log.info(f"=== {d} ({currency}) ===")

    for day_attempt in range(1, MAX_DAY_ATTEMPTS + 1):
        try:
            img_bytes, cap_token = get_captcha(session)
        except Exception as e:
            log.warning(f"  #{day_attempt} 取验证码失败: {e}")
            time.sleep(2)
            continue

        if not img_bytes or len(img_bytes) < 100 or b"html" in img_bytes.lower():
            log.warning(f"  #{day_attempt} 验证码二进制数据异常")
            time.sleep(2)
            continue

        try:
            captcha = re.sub(r"[^A-Za-z0-9]", "", ocr.classification(img_bytes).strip())
        except Exception as ocr_err:
            log.error(f"  #{day_attempt} ddddocr 底层捕获: {ocr_err}")
            session = make_session()
            time.sleep(2)
            continue

        if not (3 <= len(captcha) <= 6):
            continue

        try:
            html1 = submit_page1(session, d, captcha, cap_token, currency)
        except Exception as e:
            log.warning(f"  #{day_attempt} 第1页网络异常: {e}")
            time.sleep(2)
            continue

        rows1 = parse_table(html1, currency)
        if not rows1:
            if has_server_error(html1):
                continue
            log.warning(f"  #{day_attempt} 第1页未解析出有效行数据，准备重试")
            continue

        pf = parse_pageform(html1)
        try:
            page_count = int(pf.get("pageCount", 1))
        except ValueError:
            page_count = 1

        log.info(f"    第 1 页 {len(rows1)} 条 共 {page_count} 页")
        all_rows = list(rows1)
        day_ok = True

        # 正常翻页控制
        if not crossed_target(rows1, d):
            for page_no in range(2, page_count + 1):
                rows_p, pf = fetch_page_with_retry(session, pf, page_no, d, currency)

                if not rows_p:
                    log.warning(f"  第{page_no}页翻页重试失败")
                    day_ok = False
                    break

                all_rows.extend(rows_p)
                if crossed_target(rows_p, d):
                    break

                time.sleep(random.uniform(0.4, 0.8))

        # 数据清洗过滤
        cands_all = [(parse_time(r["发布时间"]), r) for r in all_rows]
        cands_today = [(t, r) for t, r in cands_all if t and t.date() == d]

        if not cands_today:
            log.warning(f"  {d} 列表里未包含当天的有效记录")
            continue

        # 策略 A：寻找大于等于 10:00 的最早一条记录
        cands_after_10 = [item for item in cands_today if item[0].hour >= TARGET_HOUR]
        if cands_after_10:
            cands_after_10.sort(key=lambda x: x[0])
            best_t, best_r = cands_after_10[0]
            log.info(f"  ✓ {best_t} (策略A: 10点后首条) 折算价={best_r['中行折算价']}")
            return best_r
        
        # 策略 B（针对无高频更新日）：取当天最新、最接近10点的一条
        cands_today.sort(key=lambda x: x[0], reverse=True) 
        best_t, best_r = cands_today[0]
        log.info(f"  ✓ {best_t} (策略B: 10点前独家兜底) 折算价={best_r['中行折算价']}")
        return best_r

    log.error(f"  ✗ {d} 已达最大重试次数，跳过")
    return None


# ============================================================
#  主流程
# ============================================================
def load_done(output_file: str) -> set[str]:
    p = Path(output_file)
    if not p.exists():
        return set()
    try:
        df = pd.read_csv(p)
        return set(df["查询日期"].astype(str))
    except Exception:
        return set()


def append_row(row: dict, output_file: str):
    df = pd.DataFrame([row])
    header = not Path(output_file).exists()
    df.to_csv(output_file, mode="a", index=False, header=header, encoding="utf-8-sig")


def scrape_currency(currency: str, output_file: str):
    """抓取单个币种的完整流程"""
    log.info(f"{'='*50}")
    log.info(f"开始抓取: {currency} → {output_file}")
    log.info(f"{'='*50}")

    done = load_done(output_file)
    all_dates = [START_DATE + timedelta(days=i) for i in range((END_DATE - START_DATE).days + 1)]
    pending = [d for d in all_dates if d.strftime("%Y-%m-%d") not in done]

    mode_label = "每日模式" if is_daily else "补全模式"
    log.info(f"[{mode_label}][{currency}] 总范围: {START_DATE} → {END_DATE} | 已有: {len(done)} 天 | 待补抓: {len(pending)} 天")

    if not pending:
        log.info(f"== {currency} 没有需要补抓的日期，跳过 ==")
        return

    session = make_session()
    processed = 0

    for d in pending:
        ds = d.strftime("%Y-%m-%d")

        if processed > 0 and processed % SESSION_REFRESH == 0:
            log.info(f"--- 定期重置 Session (已处理 {processed} 天) ---")
            session = make_session()

        try:
            rec = fetch_one_day(session, d, currency)
            if rec and isinstance(rec, dict):
                rec["查询日期"] = ds
                append_row(rec, output_file)
        except Exception as e:
            log.exception(f"{ds} ({currency}) 遇到顶层异常: {e}")
            session = make_session()

        processed += 1
        if processed % 10 == 0:
            log.info(f">>> {currency} 补抓进度: {processed}/{len(pending)} ({processed/len(pending)*100:.1f}%) <<<")

        time.sleep(random.uniform(0.5, 1.0))

    log.info(f"== {currency} 运行结束，全量数据已安全闭环 ==")


def main():
    for currency, output_file in CURRENCIES.items():
        scrape_currency(currency, output_file)

    log.info(f"== 所有币种抓取完成 ==")

    # 发送邮件通知
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