"""
BOC Exchange Rate - Daily Email Sender
发每日汇率邮件给所有订阅者
"""
import os
import json
import logging
import smtplib
import ssl
import urllib.request
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from pathlib import Path

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("boc_email.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

OUTPUT_FILE = "boc_usd_cny.csv"


def get_subscriber_list() -> list[str]:
    """从 Cloudflare Worker API 获取订阅者邮箱列表"""
    api_url = os.getenv("SUBSCRIBER_API_URL", "")
    api_key = os.getenv("SUBSCRIBER_API_KEY", "")

    if not api_url or not api_key:
        log.warning("SUBSCRIBER_API_URL 或 SUBSCRIBER_API_KEY 未配置")
        return []

    if "your-worker" in api_url:
        log.info("Worker URL 尚未配置，跳过订阅邮件发送")
        return []

    try:
        req = urllib.request.Request(
            api_url.rstrip("/") + "/subscribers",
            headers={"X-API-Key": api_key},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data.get("success"):
                subscribers = data.get("subscribers", [])
                log.info(f"从 Worker API 获取到 {len(subscribers)} 个订阅者")
                return subscribers
            else:
                log.warning(f"Worker API 返回异常: {data}")
                return []
    except Exception as e:
        log.error(f"获取订阅列表失败: {e}")
        return []


def get_recipient_from_env() -> list[str]:
    """从环境变量获取原本的接收邮箱（兼容旧配置）"""
    recipients = []
    recipient = os.getenv("RECIPIENT_EMAIL", "")
    if recipient:
        recipients.append(recipient)
    return recipients


def build_html_email(latest_data: list[dict]) -> str:
    """构建精美的 HTML 邮件内容 - 杂志风格"""
    if not latest_data:
        return "<p>暂无最新数据</p>"

    latest = latest_data[-1]  # 最新一条

    def fmt(v):
        return f"{v:.2f}" if v else "-"

    # 趋势箭头
    def trend(v, prev_v):
        if prev_v is None or not v or not prev_v:
            return ""
        diff = v - prev_v
        if diff > 0:
            return f'<span style="color:#E74C3C;font-size:13px;">↑ {diff:.2f}</span>'
        elif diff < 0:
            return f'<span style="color:#27AE60;font-size:13px;">↓ {abs(diff):.2f}</span>'
        return '<span style="color:#999;font-size:13px;">— 0.00</span>'

    # 对比前一天
    prev = latest_data[-2] if len(latest_data) >= 2 else None
    buy_trend = trend(latest.get('现汇买入价'), prev.get('现汇买入价') if prev else None)
    sell_trend = trend(latest.get('现汇卖出价'), prev.get('现汇卖出价') if prev else None)
    mid_trend = trend(latest.get('中行折算价'), prev.get('中行折算价') if prev else None)

    rows = ""
    for d in latest_data[-10:]:
        rows += f"""
        <tr>
            <td style="padding:10px 14px;border-bottom:1px solid #eee;font-size:13px;color:#555;">{d['查询日期']}</td>
            <td style="padding:10px 14px;border-bottom:1px solid #eee;font-size:13px;text-align:right;font-weight:600;font-family:'Menlo',monospace;">{fmt(d.get('现汇买入价'))}</td>
            <td style="padding:10px 14px;border-bottom:1px solid #eee;font-size:13px;text-align:right;font-weight:600;font-family:'Menlo',monospace;">{fmt(d.get('现汇卖出价'))}</td>
            <td style="padding:10px 14px;border-bottom:1px solid #eee;font-size:13px;text-align:right;font-weight:700;font-family:'Menlo',monospace;color:#C4956A;">{fmt(d.get('中行折算价'))}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f0eee9;font-family:'Helvetica Neue',Arial,'Noto Sans SC','Microsoft YaHei',sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f0eee9;">
<tr><td align="center" style="padding:30px 16px;">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 30px rgba(0,0,0,0.06);">

<!-- ===== Header ===== -->
<tr>
<td style="background:linear-gradient(135deg,#C4956A 0%,#B8865A 50%,#A6784A 100%);padding:36px 32px 28px;text-align:center;">
    <h1 style="color:#fff;margin:0 0 4px;font-size:22px;font-weight:700;letter-spacing:1px;">Monica的经验分享</h1>
    <p style="color:rgba(255,255,255,0.8);margin:0;font-size:13px;letter-spacing:2px;">每 日 外 汇 牌 价 速 递</p>
</td>
</tr>

<!-- ===== Hero Rate ===== -->
<tr>
<td style="padding:28px 32px 0;text-align:center;">
    <p style="font-size:12px;color:#999;margin:0 0 4px;text-transform:uppercase;letter-spacing:1px;">{latest['查询日期']} 最新牌价</p>
    <div style="font-size:40px;font-weight:700;color:#2D3436;font-family:'Helvetica Neue',Arial,sans-serif;letter-spacing:-1px;margin:4px 0 8px;">
        {fmt(latest.get('中行折算价'))}
        <span style="font-size:14px;font-weight:400;color:#999;letter-spacing:0;"> CNY</span>
    </div>
    <p style="font-size:12px;color:#999;margin:0;">美元兑人民币 · 中行折算价</p>
</td>
</tr>

<!-- ===== Three Stats ===== -->
<tr>
<td style="padding:20px 32px 8px;">
<table width="100%" cellpadding="0" cellspacing="0">
<tr>
<td width="33%" style="padding:0 8px;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f9f8f6;border-radius:10px;">
<tr><td style="padding:16px;text-align:center;">
    <p style="font-size:11px;color:#999;margin:0 0 6px;">现汇买入</p>
    <p style="font-size:22px;font-weight:700;color:#27AE60;margin:0;font-family:'Menlo',monospace;">{fmt(latest.get('现汇买入价'))}</p>
    <p style="font-size:11px;margin:4px 0 0;">{buy_trend}</p>
</td></tr>
</table>
</td>
<td width="33%" style="padding:0 8px;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f9f8f6;border-radius:10px;">
<tr><td style="padding:16px;text-align:center;">
    <p style="font-size:11px;color:#999;margin:0 0 6px;">现汇卖出</p>
    <p style="font-size:22px;font-weight:700;color:#E74C3C;margin:0;font-family:'Menlo',monospace;">{fmt(latest.get('现汇卖出价'))}</p>
    <p style="font-size:11px;margin:4px 0 0;">{sell_trend}</p>
</td></tr>
</table>
</td>
<td width="33%" style="padding:0 8px;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f9f8f6;border-radius:10px;">
<tr><td style="padding:16px;text-align:center;">
    <p style="font-size:11px;color:#999;margin:0 0 6px;">折算价</p>
    <p style="font-size:22px;font-weight:700;color:#C4956A;margin:0;font-family:'Menlo',monospace;">{fmt(latest.get('中行折算价'))}</p>
    <p style="font-size:11px;margin:4px 0 0;">{mid_trend}</p>
</td></tr>
</table>
</td>
</tr>
</table>
</td>
</tr>

<!-- ===== Table ===== -->
<tr>
<td style="padding:24px 32px 0;">
    <h3 style="font-size:14px;color:#2D3436;margin:0 0 14px;font-weight:600;">最近汇率数据 <span style="font-size:12px;color:#999;font-weight:400;">（近10期）</span></h3>
    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;border-radius:8px;overflow:hidden;">
        <thead>
            <tr style="background:#f5f3ef;">
                <th style="padding:10px 14px;text-align:left;font-size:11px;color:#888;font-weight:500;text-transform:uppercase;letter-spacing:0.5px;">日期</th>
                <th style="padding:10px 14px;text-align:right;font-size:11px;color:#888;font-weight:500;text-transform:uppercase;letter-spacing:0.5px;">买入价</th>
                <th style="padding:10px 14px;text-align:right;font-size:11px;color:#888;font-weight:500;text-transform:uppercase;letter-spacing:0.5px;">卖出价</th>
                <th style="padding:10px 14px;text-align:right;font-size:11px;color:#888;font-weight:500;text-transform:uppercase;letter-spacing:0.5px;">折算价</th>
            </tr>
        </thead>
        <tbody>
            {rows}
        </tbody>
    </table>
</td>
</tr>

<!-- ===== Footer ===== -->
<tr>
<td style="padding:28px 32px;border-top:1px solid #f0eee9;margin-top:24px;">
    <p style="font-size:12px;color:#aaa;margin:0;line-height:1.8;">
        📊 数据来源：<a href="https://www.bankofchina.com" style="color:#C4956A;text-decoration:none;">中国银行外汇牌价</a><br>
        ⏰ 自动更新：每日北京时间 10:30 · 本邮件由系统自动发送
    </p>
    <p style="font-size:11px;color:#ccc;margin:16px 0 0;padding-top:16px;border-top:1px solid #f5f5f5;">
        <a href="{os.getenv('UNSUBSCRIBE_BASE_URL', '#')}" style="color:#bbb;text-decoration:none;">退订邮件</a>
        <span style="color:#ddd;margin:0 8px;">·</span>
        <a href="https://lzc0403.github.io/BOC-Exchange-Rate/" style="color:#bbb;text-decoration:none;">访问网站</a>
    </p>
</td>
</tr>

</table>
</td></tr></table>
</body>
</html>"""
    return html


def send_email(to_email: str, html_body: str, attachment_path: str = None):
    """发送单封邮件"""
    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    sender_email = os.getenv("SENDER_EMAIL")
    sender_password = os.getenv("SENDER_PASSWORD")

    if not all([smtp_server, sender_email, sender_password]):
        log.warning("邮件配置不完整，跳过")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = sender_email
        msg["To"] = to_email
        msg["Subject"] = f"Monica的经验分享 - 每日汇率速递 {datetime.now().strftime('%Y-%m-%d')}"

        # 添加 HTML 正文
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        # 添加 CSV 附件
        if attachment_path and Path(attachment_path).exists():
            with open(attachment_path, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f'attachment; filename="boc_usd_cny.csv"')
            msg.attach(part)

        # 发送
        context = ssl.create_default_context()
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls(context=context)
            server.login(sender_email, sender_password)
            server.send_message(msg)

        log.info(f"邮件发送成功: {to_email}")
        return True
    except Exception as e:
        log.error(f"邮件发送失败 ({to_email}): {e}")
        return False


def main():
    log.info("=== 开始发送每日汇率邮件 ===")

    # 读取CSV数据
    csv_path = Path(OUTPUT_FILE)
    if not csv_path.exists():
        log.error(f"CSV文件不存在: {OUTPUT_FILE}")
        return

    df = pd.read_csv(csv_path)
    latest_data = df.tail(10).to_dict("records")

    if not latest_data:
        log.warning("没有数据可发送")
        return

    log.info(f"CSV共 {len(df)} 条记录，最新日期: {latest_data[-1].get('查询日期', 'N/A')}")

    # 生成HTML邮件
    html_body = build_html_email(latest_data)

    # 收集所有收件人
    recipients = []

    # 1. 从环境变量获取（兼容旧配置）
    recipients.extend(get_recipient_from_env())

    # 2. 从 Worker API 获取订阅者列表
    subscribers = get_subscriber_list()
    recipients.extend([s for s in subscribers if s not in recipients])

    if not recipients:
        log.warning("没有收件人，跳过邮件发送")
        return

    log.info(f"共 {len(recipients)} 个收件人")

    # 发送邮件
    success = 0
    fail = 0
    for email in recipients:
        if send_email(email, html_body, str(csv_path)):
            success += 1
        else:
            fail += 1
        import time
        time.sleep(1)  # 避免被判定为垃圾邮件

    log.info(f"发送完成: 成功 {success}, 失败 {fail}, 总计 {len(recipients)}")


if __name__ == "__main__":
    main()