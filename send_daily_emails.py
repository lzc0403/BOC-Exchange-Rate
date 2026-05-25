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
    """构建精美的 HTML 邮件内容"""
    if not latest_data:
        return "<p>暂无最新数据</p>"

    latest = latest_data[-1]  # 最新一条

    def fmt(v):
        return f"{v:.2f}" if v else "-"

    rows = ""
    for d in latest_data[-10:]:  # 最近10条
        rows += f"""
        <tr>
            <td style="padding:8px 12px;border-bottom:1px solid #eee;font-size:14px;">{d['查询日期']}</td>
            <td style="padding:8px 12px;border-bottom:1px solid #eee;font-size:14px;text-align:right;font-weight:500;">{fmt(d.get('现汇买入价'))}</td>
            <td style="padding:8px 12px;border-bottom:1px solid #eee;font-size:14px;text-align:right;font-weight:500;">{fmt(d.get('现汇卖出价'))}</td>
            <td style="padding:8px 12px;border-bottom:1px solid #eee;font-size:14px;text-align:right;font-weight:500;color:#C4956A;">{fmt(d.get('中行折算价'))}</td>
        </tr>"""

    html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="font-family:-apple-system,'Noto Sans SC',sans-serif;background:#f5f3ef;padding:40px 20px;">
        <div style="max-width:600px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 20px rgba(0,0,0,0.06);">
            <!-- Header -->
            <div style="background:linear-gradient(135deg,#C4956A,#B8865A);padding:32px;text-align:center;">
                <h1 style="color:#fff;margin:0 0 8px;font-size:22px;font-weight:600;">Monica的经验分享</h1>
                <p style="color:rgba(255,255,255,0.85);margin:0;font-size:14px;">每日外汇牌价速递</p>
            </div>

            <!-- Today's rates -->
            <div style="padding:24px 24px 0;">
                <p style="color:#666;font-size:13px;margin:0 0 4px;">{latest['查询日期']} 最新牌价</p>
                <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:20px;">
                    <div style="flex:1;min-width:100px;padding:16px;background:#fafaf8;border-radius:8px;text-align:center;">
                        <div style="font-size:11px;color:#999;margin-bottom:4px;">现汇买入</div>
                        <div style="font-size:24px;font-weight:600;color:#27AE60;">{fmt(latest.get('现汇买入价'))}</div>
                    </div>
                    <div style="flex:1;min-width:100px;padding:16px;background:#fafaf8;border-radius:8px;text-align:center;">
                        <div style="font-size:11px;color:#999;margin-bottom:4px;">现汇卖出</div>
                        <div style="font-size:24px;font-weight:600;color:#E74C3C;">{fmt(latest.get('现汇卖出价'))}</div>
                    </div>
                    <div style="flex:1;min-width:100px;padding:16px;background:#fafaf8;border-radius:8px;text-align:center;">
                        <div style="font-size:11px;color:#999;margin-bottom:4px;">折算价</div>
                        <div style="font-size:24px;font-weight:600;color:#C4956A;">{fmt(latest.get('中行折算价'))}</div>
                    </div>
                </div>
            </div>

            <!-- Data table -->
            <div style="padding:0 24px;">
                <h3 style="font-size:15px;color:#333;margin:0 0 12px;">最近汇率数据</h3>
                <table style="width:100%;border-collapse:collapse;">
                    <thead>
                        <tr style="background:#f5f3ef;">
                            <th style="padding:10px 12px;text-align:left;font-size:12px;color:#666;">日期</th>
                            <th style="padding:10px 12px;text-align:right;font-size:12px;color:#666;">买入价</th>
                            <th style="padding:10px 12px;text-align:right;font-size:12px;color:#666;">卖出价</th>
                            <th style="padding:10px 12px;text-align:right;font-size:12px;color:#666;">折算价</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows}
                    </tbody>
                </table>
            </div>

            <!-- Footer -->
            <div style="padding:24px;border-top:1px solid #eee;margin-top:20px;">
                <p style="font-size:12px;color:#999;margin:0;line-height:1.6;">
                    数据来源：<a href="https://www.bankofchina.com" style="color:#C4956A;text-decoration:none;">中国银行外汇牌价</a><br>
                    自动更新：每日北京时间 10:30
                </p>
                <p style="font-size:12px;color:#ccc;margin:12px 0 0;">
                    <a href="{os.getenv('UNSUBSCRIBE_BASE_URL', '#')}" style="color:#999;text-decoration:none;">退订</a> ·
                    本邮件由系统自动发送，请勿回复
                </p>
            </div>
        </div>
    </body>
    </html>
    """
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