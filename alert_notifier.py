"""
BOC Exchange Rate - Alert Email Notifier
独立的告警邮件模块，不依赖 send_daily_emails.py。

功能：
  - send_alert(subject, body) -> bool：发送告警邮件到 ALERT_EMAIL
  - 邮件配置从环境变量读取：SMTP_SERVER, SMTP_PORT, SENDER_EMAIL, SENDER_PASSWORD, ALERT_EMAIL
  - ALERT_EMAIL 未配置时 log.warning 并返回 False（不阻塞主流程）
  - SMTP 超时 30s，失败不抛异常（只 log.error 返回 False）
  - 使用 mask_email / mask_hostname 做日志脱敏

设计约束：
  - 纯 stdlib（smtplib, ssl, os, logging, re）
  - 不依赖 send_daily_emails.py（避免循环导入和耦合）
  - 告警邮件只发到 ALERT_EMAIL，不影响每日行情邮件的收件人逻辑
"""
import os
import re
import smtplib
import ssl
from datetime import datetime
from email.mime.text import MIMEText
from logging import getLogger

log = getLogger(__name__)

# SMTP 默认超时（秒）
_SMTP_TIMEOUT = 30

# 邮箱基本格式校验
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def mask_email(email: str) -> str:
    """脱敏显示邮箱，避免在日志中泄露完整地址。

    保留本地部分前 1 位 + *** + @ + 域名首标签前 1 位 + *** + 末级域名。
    示例: test@example.com -> t***@e***.com
    长度过短或解析失败时退化为 ***@***。
    """
    if not email or "@" not in email:
        return "***@***"
    local, _, domain = email.partition("@")
    labels = [label for label in domain.split(".") if label]
    if not labels:
        return "***@***"
    tld = labels[-1]
    if len(labels) >= 2:
        head = labels[0]
    else:
        head = tld
    masked_local = (local[0] + "***") if local else "***"
    masked_head = (head[0] + "***") if head else "***"
    if len(labels) >= 2:
        return f"{masked_local}@{masked_head}.{tld}"
    return f"{masked_local}@{masked_head}"


def mask_hostname(host: str) -> str:
    """脱敏显示 SMTP 服务器主机名，避免在日志中泄露完整域名。

    示例: smtp.qq.com -> sm**.*.c*m
    同时剥离可能的协议前缀(smtp:// 等)与端口。
    """
    if not host:
        return "<未配置>"
    cleaned = host.strip()
    for prefix in ("smtps://", "smtp://", "ssl://", "tls://"):
        if cleaned.lower().startswith(prefix):
            cleaned = cleaned[len(prefix):]
            break
    cleaned = cleaned.split("/")[0]
    if ":" in cleaned:
        cleaned = cleaned.split(":")[0]
    labels = [label for label in cleaned.split(".") if label]
    if not labels:
        return "<无效主机名>"
    masked_labels = []
    for i, label in enumerate(labels):
        if len(label) <= 2:
            masked_labels.append(label)
        elif i == len(labels) - 1:
            masked_labels.append(label[0] + "*" * (len(label) - 2) + label[-1])
        else:
            masked_labels.append(label[:2] + "*" * (len(label) - 2))
    return ".".join(masked_labels)


def send_alert(subject: str, body: str) -> bool:
    """发送告警邮件到 ALERT_EMAIL。

    纯文本邮件，SMTP 超时 30s，失败不抛异常。

    Args:
        subject: 邮件主题。
        body: 邮件正文（纯文本）。

    Returns:
        True 发送成功；False 发送失败或配置不完整（不抛异常）。
    """
    smtp_server = os.getenv("SMTP_SERVER", "").strip()
    smtp_port_raw = os.getenv("SMTP_PORT", "587").strip()
    sender_email = os.getenv("SENDER_EMAIL", "").strip()
    sender_password = os.getenv("SENDER_PASSWORD", "").strip()
    alert_email = os.getenv("ALERT_EMAIL", "").strip()

    if not alert_email:
        log.warning("ALERT_EMAIL 未配置，跳过告警邮件发送（不阻塞主流程）")
        return False

    if not _EMAIL_RE.match(alert_email):
        log.warning("ALERT_EMAIL 格式非法: %s，跳过告警邮件发送", mask_email(alert_email))
        return False

    if not smtp_server:
        log.warning("SMTP_SERVER 未配置，跳过告警邮件发送")
        return False

    if not sender_email or not sender_password:
        log.warning("SENDER_EMAIL 或 SENDER_PASSWORD 未配置，跳过告警邮件发送")
        return False

    try:
        smtp_port = int(smtp_port_raw)
    except (TypeError, ValueError):
        smtp_port = 587

    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["From"] = sender_email
        msg["To"] = alert_email
        msg["Subject"] = subject

        context = ssl.create_default_context()
        with smtplib.SMTP(smtp_server, smtp_port, timeout=_SMTP_TIMEOUT) as server:
            server.starttls(context=context)
            server.login(sender_email, sender_password)
            server.send_message(msg)

        log.info("告警邮件发送成功 -> %s", mask_email(alert_email))
        return True
    except Exception as e:
        log.error(
            "告警邮件发送失败 (收件人 %s, SMTP %s): %s",
            mask_email(alert_email), mask_hostname(smtp_server), e,
        )
        return False


if __name__ == "__main__":
    # 手动测试入口
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    ok = send_alert(
        "[告警] BOC抓取测试",
        f"告警邮件模块测试\n时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    )
    print(f"send_alert -> {ok}")
