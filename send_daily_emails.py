"""
BOC Exchange Rate - Daily Email Sender
发每日汇率邮件给所有订阅者
"""
import os
import json
import logging
import re
import smtplib
import socket
import ssl
import base64
import hashlib
import hmac
import secrets
import time
import html
import urllib.error
import urllib.parse
import urllib.request
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

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

CURRENCIES = {
    "美元": "boc_usd_cny.csv",
    "港币": "boc_hkd_cny.csv",
}


def get_subscriber_list() -> list[str]:
    """从 Cloudflare Worker API 获取订阅者邮箱列表。

    已停用公开订阅来源（安全紧急修复）：不再从公开 Worker /subscribers 接口批量拉取订阅者，
    避免攻击者通过公开订阅表单批量填塞垃圾地址触发每日群发。收件人来源已收敛到 RECIPIENT_EMAIL 白名单。
    本函数保留定义以兼容 import / 测试，但始终返回空列表。
    """
    # 安全修复：弃用公开订阅者来源，直接返回空列表，避免向被滥用的订阅地址群发。
    log.info("get_subscriber_list 已停用（公开订阅来源），返回空列表")
    return []

    # ---- 以下为原实现，保留备查，不再执行 ----
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
            headers={
                "X-API-Key": api_key,
                # Cloudflare bot 防护会拦截 urllib 默认 UA（Python-urllib/3.x）返回 403，
                # 使用浏览器 UA 绕过（2026-08-10 实测：带浏览器 UA 返回 200）
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
            },
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
    except urllib.error.HTTPError as e:
        # 区分 401（未授权）与 403（禁止）等状态码，便于定位 GitHub Secret 问题
        if e.code == 401:
            log.error(
                "获取订阅列表失败: HTTP 401 Unauthorized —— 缺少 X-API-Key 或 key 与 Worker 端不匹配。"
                "请检查 GitHub Secret SUBSCRIBER_API_KEY 是否已配置，且值与 Worker 端 SUBSCRIBER_API_KEY 环境变量一致"
                "（GitHub Actions 中该值来自 secrets.SUBSCRIBER_API_KEY）。"
            )
        elif e.code == 403:
            log.error(
                "获取订阅列表失败: HTTP 403 Forbidden —— 已确认根因为 Cloudflare bot 防护拦截 urllib 默认 UA"
                "（脚本已带浏览器 UA 修复）；若仍 403，请检查 GitHub Secret SUBSCRIBER_API_KEY 是否已配置，"
                "且其值与 Worker 端 `wrangler secret put SUBSCRIBER_API_KEY` 配置的 SUBSCRIBER_API_KEY 保持一致。"
                "如需更新该 Secret，可执行 `gh secret set SUBSCRIBER_API_KEY`（交互式输入，值不落盘、不入日志）。"
            )
        else:
            log.error(
                f"获取订阅列表失败: HTTP {e.code} {e.reason} —— "
                "请检查 SUBSCRIBER_API_URL 是否指向正确的 Worker 地址、Worker 是否在线。"
            )
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


EXAMPLE_DOMAINS = {"example.com", "example.org", "example.net"}
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class RecipientStats(NamedTuple):
    """收件人规范化统计信息（NamedTuple，防键名拼写错误静默失败）。

    不变量：total_raw == valid + skipped_invalid + skipped_example + skipped_duplicate
    """
    total_raw: int
    skipped_invalid: int
    skipped_example: int
    skipped_duplicate: int
    valid: int

    def to_dict(self) -> dict:
        """转换为字典（兼容旧调用方字典式访问与日志 % 格式化）。"""
        return self._asdict()


def is_disposable_example_domain(email: str) -> bool:
    """判断邮箱是否属于示例/测试域名（example.com / example.org / example.net）。

    解析 @ 后域名并整体小写比较；如 test@example.com 必然命中 example.com。
    """
    if not email or "@" not in email:
        return False
    domain = email.split("@", 1)[1].strip().lower()
    return domain in EXAMPLE_DOMAINS


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


def normalize_recipient_list(raw_emails: list[str]) -> tuple[list[str], RecipientStats]:
    """规范化收件人列表：trim、小写、过滤空串/非法格式/示例域名、按序去重。

    返回 (可用收件人列表, 统计信息)。统计信息为 RecipientStats NamedTuple，
    支持点号访问（stats.skipped_invalid）与字典式访问（stats.to_dict()["skipped_invalid"]）。
    统计不变量：total_raw == valid + skipped_invalid + skipped_example + skipped_duplicate
    """
    stats = RecipientStats(
        total_raw=len(raw_emails),
        skipped_invalid=0,
        skipped_example=0,
        skipped_duplicate=0,
        valid=0,
    )
    seen: set[str] = set()
    recipients: list[str] = []
    s_invalid = 0
    s_example = 0
    s_duplicate = 0
    for raw in raw_emails:
        email = raw.strip().lower()
        if not email:
            s_invalid += 1
            continue
        if not EMAIL_RE.match(email):
            s_invalid += 1
            continue
        if is_disposable_example_domain(email):
            s_example += 1
            continue
        if email in seen:
            s_duplicate += 1
            continue
        seen.add(email)
        recipients.append(email)
    stats = stats._replace(
        skipped_invalid=s_invalid,
        skipped_example=s_example,
        skipped_duplicate=s_duplicate,
        valid=len(recipients),
    )
    return recipients, stats


def build_currency_card(latest_data: list[dict], currency: str, pair_label: str) -> str:
    """构建单个币种的 HTML 卡片"""
    if not latest_data:
        return f"<p>{currency}暂无最新数据</p>"

    latest = latest_data[-1]  # 最新一条

    def fmt(v):
        return f"{v:.2f}" if v else "-"

    def trend(v, prev_v):
        if prev_v is None or not v or not prev_v:
            return ""
        diff = v - prev_v
        if diff > 0:
            return f'<span style="color:#E74C3C;font-size:13px;">↑ {diff:.2f}</span>'
        elif diff < 0:
            return f'<span style="color:#27AE60;font-size:13px;">↓ {abs(diff):.2f}</span>'
        return '<span style="color:#999;font-size:13px;">— 0.00</span>'

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

    return f"""
<!-- ===== {currency} Card ===== -->
<tr><td style="padding:0;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 30px rgba(0,0,0,0.06);margin-bottom:24px;">
<tr>
<td style="padding:24px 32px 0;text-align:center;">
    <p style="font-size:12px;color:#999;margin:0 0 4px;text-transform:uppercase;letter-spacing:1px;">{latest['查询日期']} 最新牌价</p>
    <div style="font-size:36px;font-weight:700;color:#2D3436;font-family:'Helvetica Neue',Arial,sans-serif;letter-spacing:-1px;margin:4px 0 8px;">
        {fmt(latest.get('中行折算价'))}
        <span style="font-size:14px;font-weight:400;color:#999;letter-spacing:0;"> CNY</span>
    </div>
    <p style="font-size:12px;color:#999;margin:0;">{pair_label} · 中行折算价</p>
</td>
</tr>
<tr>
<td style="padding:16px 32px 8px;">
<table width="100%" cellpadding="0" cellspacing="0">
<tr>
<td width="33%" style="padding:0 6px;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f9f8f6;border-radius:10px;">
<tr><td style="padding:14px;text-align:center;">
    <p style="font-size:11px;color:#999;margin:0 0 4px;">现汇买入</p>
    <p style="font-size:20px;font-weight:700;color:#27AE60;margin:0;font-family:'Menlo',monospace;">{fmt(latest.get('现汇买入价'))}</p>
    <p style="font-size:11px;margin:4px 0 0;">{buy_trend}</p>
</td></tr></table>
</td>
<td width="33%" style="padding:0 6px;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f9f8f6;border-radius:10px;">
<tr><td style="padding:14px;text-align:center;">
    <p style="font-size:11px;color:#999;margin:0 0 4px;">现汇卖出</p>
    <p style="font-size:20px;font-weight:700;color:#E74C3C;margin:0;font-family:'Menlo',monospace;">{fmt(latest.get('现汇卖出价'))}</p>
    <p style="font-size:11px;margin:4px 0 0;">{sell_trend}</p>
</td></tr></table>
</td>
<td width="33%" style="padding:0 6px;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f9f8f6;border-radius:10px;">
<tr><td style="padding:14px;text-align:center;">
    <p style="font-size:11px;color:#999;margin:0 0 4px;">折算价</p>
    <p style="font-size:20px;font-weight:700;color:#C4956A;margin:0;font-family:'Menlo',monospace;">{fmt(latest.get('中行折算价'))}</p>
    <p style="font-size:11px;margin:4px 0 0;">{mid_trend}</p>
</td></tr></table>
</td>
</tr></table>
</td>
</tr>
<tr>
<td style="padding:16px 32px 24px;">
    <h3 style="font-size:14px;color:#2D3436;margin:0 0 12px;font-weight:600;">{currency}最近数据 <span style="font-size:12px;color:#999;font-weight:400;">（近10期）</span></h3>
    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;border-radius:8px;overflow:hidden;">
        <thead><tr style="background:#f5f3ef;">
            <th style="padding:10px 14px;text-align:left;font-size:11px;color:#888;font-weight:500;">日期</th>
            <th style="padding:10px 14px;text-align:right;font-size:11px;color:#888;font-weight:500;">买入</th>
            <th style="padding:10px 14px;text-align:right;font-size:11px;color:#888;font-weight:500;">卖出</th>
            <th style="padding:10px 14px;text-align:right;font-size:11px;color:#888;font-weight:500;">折算</th>
        </tr></thead>
        <tbody>{rows}</tbody>
    </table>
</td>
</tr>
</table>
</td></tr>"""


# 退订 Token 参数（与 worker.js 验签端严格一致）
UNSUBSCRIBE_TTL_SECONDS = 7 * 24 * 3600  # 7 天
UNSUBSCRIBE_VERSION = 1


def build_unsubscribe_url(email: str) -> str:
    """为单个收件人生成带 HMAC-SHA256 签名的退订链接。

    与 Worker 端 worker.js `verifyToken` 的验签公式严格一致：

        密钥优先级（两端必须一致）：
            secret = os.getenv("UNSUBSCRIBE_SECRET") or os.getenv("SUBSCRIBER_API_KEY")
        若两者均未配置：返回回退链接（UNSUBSCRIBE_BASE_URL 或 "#"），并在日志告警（脱敏，不打印密钥）。

        email  = email.strip().lower()              # 与订阅时一致（小写）
        exp    = int(time.time()) + 7 * 24 * 3600   # 过期时间戳（Unix 秒）
        v      = 1
        nonce  = secrets.token_hex(8)               # 随机 nonce（16 位十六进制）
        payload = {"email": email, "exp": exp, "v": v, "nonce": nonce}  # 键顺序固定
        canonical = f"{email}|{exp}|{v}|{nonce}"    # 规范串：竖线分隔，无空格
        p64 = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode()
        s64 = base64.urlsafe_b64encode(hmac.new(secret, canonical, hashlib.sha256).digest()).rstrip(b"=").decode()
        token = f"{p64}.{s64}"
        url   = f"{UNSUBSCRIBE_BASE_URL}?email={urllib.parse.quote(email)}&token={token}"

    Worker 端 `verifyToken` 的校验顺序：解析 payload → 恒时验签（crypto.subtle.verify）
    → 校验 payload.email 与 query email 一致 → 校验未过期（exp > now）。
    本函数生成的 token 恰好满足该验签逻辑。

    Args:
        email: 收件人邮箱（内部会小写化）。

    Returns:
        完整的退订链接；密钥未配置时返回 UNSUBSCRIBE_BASE_URL（未配置则 "#"）。
    """
    email = (email or "").strip().lower()
    secret = os.getenv("UNSUBSCRIBE_SECRET") or os.getenv("SUBSCRIBER_API_KEY")
    base_url = os.getenv("UNSUBSCRIBE_BASE_URL", "").rstrip("/")

    if not secret:
        log.warning(
            f"退订签名密钥未配置（UNSUBSCRIBE_SECRET / SUBSCRIBER_API_KEY 均缺失），"
            f"收件人 {mask_email(email)} 的退订链接将不可用（回退链接，未携带 token）"
        )
        return base_url if base_url else "#"
    if len(secret) < 16:
        # 与 Worker 端 fail-closed 阈值一致：过短密钥视为未配置，避免被误用
        log.warning(
            f"退订签名密钥长度不足 16 字符（fail-closed），收件人 {mask_email(email)} 的退订链接将不可用"
        )
        return base_url if base_url else "#"
    if not base_url:
        log.warning(
            f"UNSUBSCRIBE_BASE_URL 未配置，退订链接无法拼接域名（收件人 {mask_email(email)}），"
            "将退化为仅返回 '#'"
        )
        return "#"

    exp = int(time.time()) + UNSUBSCRIBE_TTL_SECONDS
    v = UNSUBSCRIBE_VERSION
    nonce = secrets.token_hex(8)
    # 键顺序必须固定：email, exp, v, nonce（与 worker.js generateToken / Python 公式一致）
    payload = {"email": email, "exp": exp, "v": v, "nonce": nonce}
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    canonical = f"{email}|{exp}|{v}|{nonce}"
    p64 = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode("ascii")
    s64 = base64.urlsafe_b64encode(
        hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).digest()
    ).rstrip(b"=").decode("ascii")
    token = f"{p64}.{s64}"
    return f"{base_url}?email={urllib.parse.quote(email)}&token={token}"


def build_html_email(all_currency_data: dict[str, list[dict]], unsubscribe_url: str) -> str:
    """构建精美的 HTML 邮件内容 - 多币种杂志风格

    Args:
        all_currency_data: 各币种最新数据（key=币种名，value=记录列表）。
        unsubscribe_url: 该收件人的专属签名退订链接（由 build_unsubscribe_url 生成）。
    """
    pairs = {"美元": "美元兑人民币", "港币": "港币兑人民币"}
    cards = ""
    for currency, data in all_currency_data.items():
        cards += build_currency_card(data, currency, pairs.get(currency, currency))

    # 退订链接放入 href 前做 HTML 转义，杜绝任何注入（邮箱/token 均为受控字符，双保险）
    unsubscribe_href = html.escape(unsubscribe_url, quote=True)

    # 注意：局部变量必须避免命名为 html（顶层已 import html 模块），否则 Python
    # 词法作用域会把整个函数内的 html 视为局部变量，导致上方 html.escape 触发 UnboundLocalError。
    html_body = f"""<!DOCTYPE html>
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

{cards}

<!-- ===== Footer ===== -->
<tr>
<td style="padding:28px 32px;border-top:1px solid #f0eee9;">
    <p style="font-size:12px;color:#aaa;margin:0;line-height:1.8;">
        📊 数据来源：<a href="https://www.bankofchina.com" style="color:#C4956A;text-decoration:none;">中国银行外汇牌价</a><br>
        ⏰ 自动更新：每日北京时间 09:30 · 本邮件由系统自动发送
    </p>
    <p style="font-size:11px;color:#ccc;margin:16px 0 0;padding-top:16px;border-top:1px solid #f5f5f5;">
        <a href="{unsubscribe_href}" style="color:#bbb;text-decoration:none;">退订邮件</a>
        <span style="color:#ddd;margin:0 8px;">·</span>
        <a href="https://lzc0403.github.io/BOC-Exchange-Rate/" style="color:#bbb;text-decoration:none;">访问网站</a>
    </p>
</td>
</tr>

</table>
</td></tr></table>
</body>
</html>"""
    return html_body


def mask_hostname(host: str) -> str:
    """脱敏显示 SMTP 服务器主机名，避免在日志中泄露完整域名。

    示例: smtp.qq.com -> sm**.*.c*m（保留前 2 位与末级首尾 1 位）
    同时会剥离可能的协议前缀(smtp:// 等)与端口，便于排查 Secret 中的脏值。
    """
    if not host:
        return "<未配置>"
    cleaned = host.strip()
    for prefix in ("smtps://", "smtp://", "ssl://", "tls://"):
        if cleaned.lower().startswith(prefix):
            cleaned = cleaned[len(prefix):]
            break
    # 去掉可能的端口与路径部分
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


def send_email(to_email: str, html_body: str, attachment_paths: list[str] = None):
    """发送单封邮件"""
    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    sender_email = os.getenv("SENDER_EMAIL")
    sender_password = os.getenv("SENDER_PASSWORD")

    if not all([smtp_server, sender_email, sender_password]):
        log.warning("邮件配置不完整，跳过")
        return False

    # 显式 SMTP 超时（秒），防止连接挂起；非法值回退默认 30
    try:
        smtp_timeout = int(os.getenv("SMTP_TIMEOUT", "30"))
    except (TypeError, ValueError):
        smtp_timeout = 30
    if smtp_timeout <= 0:
        smtp_timeout = 30

    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = sender_email
        msg["To"] = to_email
        msg["Subject"] = f"Monica的经验分享 - 每日汇率速递 {datetime.now().strftime('%Y-%m-%d')}"

        # 添加 HTML 正文
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        # 添加 CSV 附件
        if attachment_paths:
            for path in attachment_paths:
                if path and Path(path).exists():
                    with open(path, "rb") as f:
                        part = MIMEBase("application", "octet-stream")
                        part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header("Content-Disposition", f'attachment; filename="{Path(path).name}"')
                    msg.attach(part)

        # 发送（starttls / login / send_message 均在同一个带超时的连接内）
        context = ssl.create_default_context()
        with smtplib.SMTP(smtp_server, smtp_port, timeout=smtp_timeout) as server:
            server.starttls(context=context)
            server.login(sender_email, sender_password)
            server.send_message(msg)

        log.info(f"邮件发送成功: {mask_email(to_email)}")
        return True
    except socket.gaierror as e:
        # DNS 解析失败（如 [Errno -3] Temporary failure in name resolution）
        log.error(
            f"邮件发送失败 ({mask_email(to_email)}): DNS 解析失败，无法解析 SMTP 服务器 {mask_hostname(smtp_server)}。"
            "CI 环境 DNS 本身正常，大概率是 GitHub Secret SMTP_SERVER 的值有问题"
            "（域名拼写错误 / 含空格或协议头如 smtp:// / 指向不存在的 host）。"
            "请检查/修正 Secret，并在本地用 `nslookup <smtp_server>` 验证域名可解析。"
        )
        return False
    except Exception as e:
        log.error(f"邮件发送失败 ({mask_email(to_email)}): {e}")
        return False


def main():
    log.info("=== 开始发送每日汇率邮件（多币种）===")

    # 读取各币种CSV数据
    all_currency_data = {}
    attachment_paths = []
    for currency, csv_file in CURRENCIES.items():
        csv_path = Path(csv_file)
        if csv_path.exists():
            df = pd.read_csv(csv_path)
            latest_data = df.tail(10).to_dict("records")
            if latest_data:
                all_currency_data[currency] = latest_data
                attachment_paths.append(str(csv_path))
                log.info(f"[{currency}] {len(df)} 条记录，最新: {latest_data[-1].get('查询日期', 'N/A')}")
            else:
                log.warning(f"[{currency}] {csv_file} 无数据")
        else:
            log.warning(f"[{currency}] {csv_file} 不存在")

    if not all_currency_data:
        log.warning("没有任何币种数据，跳过发送")
        return

    # 安全修复：收件人来源收敛为受限白名单 —— 仅从 RECIPIENT_EMAIL 环境变量读取，
    # 不再从公开 Worker /subscribers 接口批量拉取订阅者（避免向被滥用的订阅地址群发）。
    raw_recipients: list[str] = get_recipient_from_env()

    recipients, stats = normalize_recipient_list(raw_recipients)
    if stats.skipped_invalid or stats.skipped_example or stats.skipped_duplicate:
        log.info(
            "收件人过滤统计: 原始 %d，合法 %d，"
            "跳过示例域名 %d，跳过非法/空 %d，跳过重复 %d" % stats.to_dict()
        )

    if not recipients:
        log.warning("没有有效收件人，跳过邮件发送")
        return

    log.info(f"共 {len(recipients)} 个收件人（跳过 {stats.skipped_example} 个示例域名）")

    # 发送邮件：HTML 骨架（币种卡片）不变，但退订链接必须按收件人逐一生成，
    # 因此在循环内为每个收件人构建专属 HTML 再发送。
    success = 0
    fail = 0
    for email in recipients:
        unsubscribe_url = build_unsubscribe_url(email)
        html_body = build_html_email(all_currency_data, unsubscribe_url)
        if send_email(email, html_body, attachment_paths):
            success += 1
        else:
            fail += 1
        time.sleep(1)

    log.info(
        f"发送完成: 成功 {success}, 失败 {fail}, 总计 {len(recipients)}, "
        f"跳过 {stats.skipped_example + stats.skipped_invalid + stats.skipped_duplicate}"
    )


if __name__ == "__main__":
    main()