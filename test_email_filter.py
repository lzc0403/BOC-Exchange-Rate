"""
send_daily_emails.py 收件人规范化 / 示例域过滤 / 脱敏 / SMTP 超时 / 签名退订链接 单元测试。

覆盖场景：
  1. test@example.com 被过滤且不计入发送列表；
  2. foo@example.org、bar@example.net 被过滤；
  3. 正常邮箱 user@gmail.com 保留；
  4. 大小写 TEST@EXAMPLE.COM 被过滤（小写化后命中）；
  5. 首尾空格被 trim 后再判断；
  6. 非法格式 not-an-email 被跳过；
  7. 去重：同一邮箱出现两次只保留一次；
  8. env 与订阅列表混合后正确合并去重；
  9. 全被过滤时返回空列表且不抛异常；
  10. mask_email 不泄露完整邮箱（输出不含原始完整邮箱、且含 ***）；
  11. build_unsubscribe_url 无密钥时回退、有密钥时生成含 email+token 的签名链接。

运行：
  python -m unittest test_email_filter -v
  python -m pytest test_email_filter.py -q
  python test_email_filter.py
"""
import os
import re
import unittest
from unittest.mock import patch, MagicMock

# 被测模块顶层会创建 boc_email.log（FileHandler），接受该行为（运行目录可能多一个日志文件）。
import send_daily_emails as sd


def _raw_list(*emails):
    return list(emails)


class NormalizeRecipientListTest(unittest.TestCase):
    """normalize_recipient_list 的过滤、去重、统计逻辑。"""

    def test_example_com_filtered(self):
        recipients, stats = sd.normalize_recipient_list(_raw_list("test@example.com"))
        self.assertEqual(recipients, [])
        self.assertEqual(stats.skipped_example, 1)
        self.assertEqual(stats.valid, 0)

    def test_example_org_and_net_filtered(self):
        recipients, stats = sd.normalize_recipient_list(
            _raw_list("foo@example.org", "bar@example.net"))
        self.assertEqual(recipients, [])
        self.assertEqual(stats.skipped_example, 2)

    def test_normal_email_kept(self):
        recipients, stats = sd.normalize_recipient_list(_raw_list("user@gmail.com"))
        self.assertEqual(recipients, ["user@gmail.com"])
        self.assertEqual(stats.valid, 1)
        self.assertEqual(stats.skipped_example, 0)

    def test_uppercase_example_filtered(self):
        recipients, stats = sd.normalize_recipient_list(_raw_list("TEST@EXAMPLE.COM"))
        self.assertEqual(recipients, [])
        self.assertEqual(stats.skipped_example, 1)

    def test_whitespace_trimmed_then_judged(self):
        recipients, stats = sd.normalize_recipient_list(_raw_list("  test@example.com  "))
        self.assertEqual(recipients, [])
        self.assertEqual(stats.skipped_example, 1)
        # 空格包裹的正常邮箱 trim 后保留
        recipients2, _ = sd.normalize_recipient_list(_raw_list("  user@gmail.com  "))
        self.assertEqual(recipients2, ["user@gmail.com"])

    def test_invalid_format_skipped(self):
        recipients, stats = sd.normalize_recipient_list(_raw_list("not-an-email"))
        self.assertEqual(recipients, [])
        self.assertEqual(stats.skipped_invalid, 1)

    def test_duplicate_removed(self):
        recipients, stats = sd.normalize_recipient_list(
            _raw_list("user@gmail.com", "user@gmail.com", "a@b.co"))
        self.assertEqual(recipients, ["user@gmail.com", "a@b.co"])
        self.assertEqual(len(recipients), 2)
        self.assertEqual(stats.valid, 2)
        self.assertEqual(stats.skipped_duplicate, 1)

    def test_duplicate_counted_in_stats(self):
        """Fix 4 回归：重复邮箱计入 skipped_duplicate，统计恒自洽。"""
        recipients, stats = sd.normalize_recipient_list(
            _raw_list("dup@gmail.com", "dup@gmail.com", "dup@gmail.com", "ok@b.co"))
        self.assertEqual(recipients, ["dup@gmail.com", "ok@b.co"])
        self.assertEqual(stats.valid, 2)
        self.assertEqual(stats.skipped_duplicate, 2)
        # 不变量：total_raw == valid + skipped_invalid + skipped_example + skipped_duplicate
        self.assertEqual(
            stats.total_raw,
            stats.valid + stats.skipped_invalid + stats.skipped_example + stats.skipped_duplicate,
        )

    def test_env_and_subscriber_merged(self):
        recipients, stats = sd.normalize_recipient_list(
            _raw_list("env@test.com", "sub@test.com", "env@test.com", "test@example.com"))
        self.assertEqual(recipients, ["env@test.com", "sub@test.com"])
        self.assertEqual(stats.skipped_example, 1)
        self.assertEqual(stats.skipped_duplicate, 1)

    def test_all_filtered_returns_empty(self):
        recipients, stats = sd.normalize_recipient_list(
            _raw_list("test@example.com", "foo@example.net", ""))
        self.assertEqual(recipients, [])
        self.assertEqual(stats.skipped_example, 2)
        self.assertEqual(stats.skipped_invalid, 1)
        # 不抛异常即通过

    def test_empty_input(self):
        recipients, stats = sd.normalize_recipient_list([])
        self.assertEqual(recipients, [])
        self.assertEqual(stats.total_raw, 0)
        self.assertEqual(stats.skipped_duplicate, 0)


class MaskEmailTest(unittest.TestCase):
    """mask_email 不泄露完整邮箱。"""

    def test_mask_normal_email(self):
        masked = sd.mask_email("test@example.com")
        self.assertEqual(masked, "t***@e***.com")
        self.assertIn("***", masked)
        self.assertNotIn("test@example.com", masked)

    def test_mask_does_not_leak_full_email(self):
        for raw in ["user@gmail.com", "alice@sub.domain.org", "x@y.com"]:
            masked = sd.mask_email(raw)
            self.assertIn("***", masked)
            self.assertNotIn(raw, masked, f"mask_email 泄露了 {raw} -> {masked}")

    def test_mask_short_email(self):
        masked = sd.mask_email("a@b.co")
        self.assertIn("***", masked)
        self.assertNotIn("a@b.co", masked)

    def test_mask_invalid_falls_back(self):
        self.assertEqual(sd.mask_email(""), "***@***")
        self.assertEqual(sd.mask_email("not-an-email"), "***@***")


class SendEmailFilterTest(unittest.TestCase):
    """验证 send_email 永远不会收到示例域地址（mock 掉真实 SMTP）。"""

    def test_example_never_passed_to_send(self):
        env_recipients = ["owner@real.com"]
        subscriber_list = ["test@example.com", "sub@real.com", "TEST@EXAMPLE.ORG"]
        raw = env_recipients + subscriber_list
        recipients, stats = sd.normalize_recipient_list(raw)
        self.assertEqual(stats.skipped_example, 2)

        with patch("send_daily_emails.send_email", return_value=True) as mock_send:
            for email in recipients:
                mock_send(email, "<html/>", [])
            called = [call.args[0] for call in mock_send.call_args_list]
        self.assertNotIn("test@example.com", called)
        self.assertNotIn("test@example.org", called)
        self.assertIn("owner@real.com", called)
        self.assertIn("sub@real.com", called)


class SendEmailTimeoutTest(unittest.TestCase):
    """SMTP 显式超时：连接创建时传入 timeout，且与配置不符时回退默认。"""

    @patch.dict(os.environ, {
        "SMTP_SERVER": "smtp.example.com",
        "SMTP_PORT": "587",
        "SENDER_EMAIL": "sender@example.com",
        "SENDER_PASSWORD": "dummy-password",
    })
    def test_smtp_timeout_passed_to_connection(self):
        fake_server = MagicMock()
        with patch("send_daily_emails.smtplib.SMTP", return_value=fake_server) as mock_smtp:
            result = sd.send_email("user@gmail.com", "<p>hi</p>", [])

        self.assertTrue(result)
        self.assertTrue(mock_smtp.called)
        kwargs = mock_smtp.call_args[1]
        self.assertEqual(kwargs.get("timeout"), 30)  # 默认 30 秒

    @patch.dict(os.environ, {
        "SMTP_SERVER": "smtp.example.com",
        "SMTP_PORT": "587",
        "SENDER_EMAIL": "sender@example.com",
        "SENDER_PASSWORD": "dummy-password",
        "SMTP_TIMEOUT": "5",
    })
    def test_smtp_timeout_from_env(self):
        fake_server = MagicMock()
        with patch("send_daily_emails.smtplib.SMTP", return_value=fake_server) as mock_smtp:
            sd.send_email("user@gmail.com", "<p>hi</p>", [])
            self.assertEqual(mock_smtp.call_args[1].get("timeout"), 5)

    @patch.dict(os.environ, {
        "SMTP_SERVER": "smtp.example.com",
        "SMTP_PORT": "587",
        "SENDER_EMAIL": "sender@example.com",
        "SENDER_PASSWORD": "dummy-password",
        "SMTP_TIMEOUT": "not-a-number",
    })
    def test_smtp_timeout_invalid_falls_back(self):
        fake_server = MagicMock()
        with patch("send_daily_emails.smtplib.SMTP", return_value=fake_server) as mock_smtp:
            sd.send_email("user@gmail.com", "<p>hi</p>", [])
            self.assertEqual(mock_smtp.call_args[1].get("timeout"), 30)


class BuildUnsubscribeUrlTest(unittest.TestCase):
    """build_unsubscribe_url：HMAC-SHA256 签名退订链接，与 worker.js 验签端严格一致。"""

    # 与 send_daily_emails.py / worker.js 一致的固定密钥（>=16 字符）
    SECRET = "test-unsub-secret-0123456789abcdef"
    BASE_URL = "https://api.example.com/unsubscribe"

    def test_no_secret_falls_back(self):
        # 无 UNSUBSCRIBE_SECRET / SUBSCRIBER_API_KEY：返回 UNSUBSCRIBE_BASE_URL（未配置则 "#"），不抛异常
        with patch.dict(os.environ, {
            "UNSUBSCRIBE_BASE_URL": self.BASE_URL,
        }, clear=False):
            # 显式清空两个密钥
            with patch.dict(os.environ, {
                "UNSUBSCRIBE_SECRET": "",
                "SUBSCRIBER_API_KEY": "",
            }):
                url = sd.build_unsubscribe_url("Test@Example.com")
        self.assertEqual(url, self.BASE_URL)
        # 不含 token（未携带签名）
        self.assertNotIn("token=", url)

        # 连 UNSUBSCRIBE_BASE_URL 也未配置时回退 "#"
        with patch.dict(os.environ, {
            "UNSUBSCRIBE_SECRET": "",
            "SUBSCRIBER_API_KEY": "",
            "UNSUBSCRIBE_BASE_URL": "",
        }):
            self.assertEqual(sd.build_unsubscribe_url("a@b.co"), "#")

    def test_short_secret_falls_back(self):
        # 密钥长度 < 16 视为未配置（与 Worker fail-closed 阈值一致）
        with patch.dict(os.environ, {
            "UNSUBSCRIBE_SECRET": "",
            "SUBSCRIBER_API_KEY": "short",
            "UNSUBSCRIBE_BASE_URL": self.BASE_URL,
        }):
            url = sd.build_unsubscribe_url("user@example.com")
        self.assertEqual(url, self.BASE_URL)

    def test_url_contains_email_and_token(self):
        with patch.dict(os.environ, {
            "UNSUBSCRIBE_SECRET": self.SECRET,
            "SUBSCRIBER_API_KEY": "",
            "UNSUBSCRIBE_BASE_URL": self.BASE_URL,
        }):
            url = sd.build_unsubscribe_url("User@Example.COM")

        # email 已小写化并 URL 编码
        self.assertIn("email=user%40example.com", url)
        # 包含 token 参数且格式为 payload.signature 两段
        self.assertIn("token=", url)
        token = url.split("token=")[1]
        parts = token.split(".")
        self.assertEqual(len(parts), 2, f"token 应恰为两段: {token}")
        self.assertTrue(parts[0], "payload 段非空")
        self.assertTrue(parts[1], "签名段非空")

    def test_signature_segment_is_43_chars_base64url_no_padding(self):
        # HMAC-SHA256 摘要 32 字节 -> base64url 无 padding = ceil(32*4/3)=43 字符
        with patch.dict(os.environ, {
            "UNSUBSCRIBE_SECRET": self.SECRET,
            "SUBSCRIBER_API_KEY": "",
            "UNSUBSCRIBE_BASE_URL": self.BASE_URL,
        }):
            url = sd.build_unsubscribe_url("user@example.com")
        token = url.split("token=")[1]
        sig = token.split(".")[1]
        self.assertEqual(len(sig), 43, f"签名段长度应为 43，实际 {len(sig)}: {sig}")
        # 无 padding：不含 '='
        self.assertNotIn("=", sig)
        # 仅含 base64url 字符集 [A-Za-z0-9_-]
        self.assertTrue(re.fullmatch(r"[A-Za-z0-9_-]+", sig), f"签名段含非法字符: {sig}")

    def test_payload_decodes_to_expected_fields(self):
        # 反解 payload 段，验证键顺序为 {"email","exp","v","nonce"}，且能按 Worker 公式复算
        import base64
        import hashlib
        import hmac
        import json
        import time

        with patch.dict(os.environ, {
            "UNSUBSCRIBE_SECRET": self.SECRET,
            "SUBSCRIBER_API_KEY": "",
            "UNSUBSCRIBE_BASE_URL": self.BASE_URL,
        }):
            url = sd.build_unsubscribe_url("user@example.com")
        token = url.split("token=")[1]
        p64, s64 = token.split(".")

        # 解码 payload 并验证键顺序（dict 保持插入序）
        payload_bytes = base64.urlsafe_b64decode(p64 + "=" * (-len(p64) % 4))
        payload = json.loads(payload_bytes.decode("utf-8"))
        self.assertEqual(list(payload.keys()), ["email", "exp", "v", "nonce"])
        self.assertEqual(payload["email"], "user@example.com")
        self.assertEqual(payload["v"], 1)
        self.assertIsInstance(payload["exp"], int)
        self.assertGreater(payload["exp"], int(time.time()))

        # 用 Worker 端公式复算签名，必须与 s64 一致（两端互操作验证）
        canonical = f"{payload['email']}|{payload['exp']}|{payload['v']}|{payload['nonce']}"
        expected_s64 = base64.urlsafe_b64encode(
            hmac.new(self.SECRET.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).digest()
        ).rstrip(b"=").decode("ascii")
        self.assertEqual(s64, expected_s64, "Python 生成的签名与 Worker 验签公式复算不一致")

    def test_different_nonce_produces_different_tokens(self):
        # 同一邮箱、同一密钥，两次调用应因 nonce 不同而产生不同 token（防重放）
        with patch.dict(os.environ, {
            "UNSUBSCRIBE_SECRET": self.SECRET,
            "SUBSCRIBER_API_KEY": "",
            "UNSUBSCRIBE_BASE_URL": self.BASE_URL,
        }):
            url1 = sd.build_unsubscribe_url("user@example.com")
            url2 = sd.build_unsubscribe_url("user@example.com")
        token1 = url1.split("token=")[1]
        token2 = url2.split("token=")[1]
        self.assertNotEqual(token1, token2)


class BuildHtmlEmailTest(unittest.TestCase):
    """build_html_email：退订链接注入 + HTML 转义 + 不抛 UnboundLocalError。

    回归背景：批次 A 曾因函数内局部变量命名为 html 遮蔽顶层 import html，
    导致 html.escape 触发 UnboundLocalError，邮件发送功能完全不可用。
    本组用例确保该函数可正常调用且转义正确。
    """

    DATA = {"美元": [{"查询日期": "2026-08-13", "现汇买入价": 7.1, "现汇卖出价": 7.2, "中行折算价": 7.15}]}

    def test_returns_html_with_unsubscribe_link(self):
        html_out = sd.build_html_email(
            self.DATA, "https://api.example.com/unsub?email=a%40b.com&token=p.s")
        self.assertIsInstance(html_out, str)
        self.assertIn("退订邮件", html_out)
        self.assertIn('href="https://api.example.com/unsub?email=a%40b.com&amp;token=p.s"', html_out)

    def test_escapes_ampersand_in_href(self):
        html_out = sd.build_html_email(
            self.DATA, "https://api.example.com/unsub?a=1&b=2&email=a%40b.com&token=p.s")
        self.assertIn("&amp;", html_out)
        # 不存在未转义的裸 &（href 属性内）
        m = re.search(r'<a href="([^"]*)"[^>]*>退订邮件</a>', html_out)
        self.assertIsNotNone(m)
        self.assertNotIn('<a href="https://api.example.com/unsub?a=1&b=2', html_out)

    def test_escapes_quotes_and_angle_brackets_in_href(self):
        malicious = 'https://api.example.com/unsub?a=1&b="x"<script>alert(1)</script>&email=a%40b.com&token=p.s'
        html_out = sd.build_html_email(self.DATA, malicious)
        m = re.search(r'<a href="([^"]*)"[^>]*>退订邮件</a>', html_out)
        self.assertIsNotNone(m)
        href = m.group(1)
        self.assertIn("&quot;", href)
        self.assertIn("&lt;script&gt;", href)
        self.assertNotIn("<script>", href)
        self.assertNotIn('"x"', href)

    def test_injects_per_recipient_token(self):
        # 每个收件人的专属退订链接应原样注入自身 token
        with patch.dict(os.environ, {
            "UNSUBSCRIBE_SECRET": BuildUnsubscribeUrlTest.SECRET,
            "SUBSCRIBER_API_KEY": "",
            "UNSUBSCRIBE_BASE_URL": BuildUnsubscribeUrlTest.BASE_URL,
        }):
            url = sd.build_unsubscribe_url("user@example.com")
            token = url.split("token=")[1]
        html_out = sd.build_html_email(self.DATA, url)
        self.assertIn(token, html_out)

    def test_no_unbound_local_error_on_call(self):
        # 回归核心：调用不抛异常（曾因 html 局部变量遮蔽导致必崩）
        try:
            html_out = sd.build_html_email(
                self.DATA, "https://api.example.com/unsub?email=a%40b.com&token=p.s")
        except UnboundLocalError as e:
            self.fail(f"build_html_email 不应抛 UnboundLocalError: {e}")
        self.assertTrue(html_out)


# ---- Fix 3 回归：RecipientStats 是 NamedTuple 且属性可访问 ----


class RecipientStatsNamedTupleTest(unittest.TestCase):
    """Fix 3 回归：normalize_recipient_list 返回 RecipientStats NamedTuple。

    确保返回类型从 dict 改为 NamedTuple 后：
    - RecipientStats 是 NamedTuple 子类
    - .valid / .skipped_invalid / .skipped_example / .skipped_duplicate / .total_raw 属性可访问
    - 同时支持 to_dict() 字典式访问（兼容旧调用方）
    """

    def test_recipient_stats_is_namedtuple(self):
        """RecipientStats 应为 NamedTuple 子类。"""
        from collections import namedtuple
        # NamedTuple 子类同时也是 tuple 子类
        self.assertTrue(issubclass(sd.RecipientStats, tuple))
        # hasattr __fields__ 是 NamedTuple 的特征
        self.assertTrue(hasattr(sd.RecipientStats, "_fields"))
        expected_fields = (
            "total_raw", "skipped_invalid", "skipped_example",
            "skipped_duplicate", "valid",
        )
        self.assertEqual(sd.RecipientStats._fields, expected_fields)

    def test_all_attributes_accessible(self):
        """所有统计字段通过点号访问，无 AttributeError。"""
        recipients, stats = sd.normalize_recipient_list(
            _raw_list("user@gmail.com", "bad", "test@example.com", "dup@gmail.com", "dup@gmail.com"))
        # 每个属性都能访问且为 int
        self.assertIsInstance(stats.total_raw, int)
        self.assertIsInstance(stats.skipped_invalid, int)
        self.assertIsInstance(stats.skipped_example, int)
        self.assertIsInstance(stats.skipped_duplicate, int)
        self.assertIsInstance(stats.valid, int)

    def test_to_dict_returns_correct_keys(self):
        """to_dict() 返回含所有字段的字典（兼容旧调用方）。"""
        recipients, stats = sd.normalize_recipient_list(
            _raw_list("user@gmail.com", "test@example.com"))
        d = stats.to_dict()
        self.assertIsInstance(d, dict)
        for key in ("total_raw", "skipped_invalid", "skipped_example",
                    "skipped_duplicate", "valid"):
            self.assertIn(key, d, f"to_dict() 缺少键 {key}")

    def test_namedtuple_immutable(self):
        """NamedTuple 不可变：修改属性应抛 AttributeError（防止运行时篡改统计）。"""
        recipients, stats = sd.normalize_recipient_list(
            _raw_list("user@gmail.com"))
        with self.assertRaises(AttributeError):
            stats.valid = 999


# ---- Fix 4 回归：skipped_duplicate 计数 + 不变量恒自洽 ----


class SkippedDuplicateInvariantTest(unittest.TestCase):
    """Fix 4 回归：去重时计入 skipped_duplicate，且统计不变量恒成立。

    不变量：total_raw == valid + skipped_invalid + skipped_example + skipped_duplicate
    """

    def test_single_duplicate_counted(self):
        """1 个重复邮箱 → skipped_duplicate == 1，不变量成立。"""
        recipients, stats = sd.normalize_recipient_list(
            _raw_list("a@gmail.com", "a@gmail.com"))
        self.assertEqual(stats.skipped_duplicate, 1)
        self.assertEqual(stats.valid, 1)
        self.assertEqual(
            stats.total_raw,
            stats.valid + stats.skipped_invalid + stats.skipped_example + stats.skipped_duplicate)

    def test_multiple_duplicates_counted(self):
        """3 个重复邮箱 → skipped_duplicate == 3（含首次出现之外的每次重复）。"""
        recipients, stats = sd.normalize_recipient_list(
            _raw_list("dup@gmail.com", "dup@gmail.com", "dup@gmail.com", "dup@gmail.com"))
        self.assertEqual(recipients, ["dup@gmail.com"])
        self.assertEqual(stats.valid, 1)
        self.assertEqual(stats.skipped_duplicate, 3)
        self.assertEqual(
            stats.total_raw,
            stats.valid + stats.skipped_invalid + stats.skipped_example + stats.skipped_duplicate)

    def test_invariant_with_mixed_categories(self):
        """混合场景（合法+非法+示例域+重复）不变量成立。"""
        raw = [
            "ok1@gmail.com",      # valid
            "ok2@gmail.com",      # valid
            "not-an-email",       # skipped_invalid
            "",                   # skipped_invalid
            "test@example.com",   # skipped_example
            "ok1@gmail.com",      # skipped_duplicate
            "ok1@gmail.com",      # skipped_duplicate
            "ok2@gmail.com",      # skipped_duplicate
        ]
        recipients, stats = sd.normalize_recipient_list(_raw_list(*raw))
        self.assertEqual(stats.valid, 2)
        self.assertEqual(stats.skipped_invalid, 2)
        self.assertEqual(stats.skipped_example, 1)
        self.assertEqual(stats.skipped_duplicate, 3)
        self.assertEqual(stats.total_raw, len(raw))
        # 核心不变量
        self.assertEqual(
            stats.total_raw,
            stats.valid + stats.skipped_invalid + stats.skipped_example + stats.skipped_duplicate)

    def test_invariant_empty_input(self):
        """空输入：不变量成立（0 == 0+0+0+0）。"""
        recipients, stats = sd.normalize_recipient_list([])
        self.assertEqual(stats.total_raw, 0)
        self.assertEqual(
            stats.total_raw,
            stats.valid + stats.skipped_invalid + stats.skipped_example + stats.skipped_duplicate)

    def test_invariant_all_valid_no_duplicates(self):
        """全部合法无重复：不变量成立。"""
        raw = ["a@gmail.com", "b@gmail.com", "c@gmail.com"]
        recipients, stats = sd.normalize_recipient_list(_raw_list(*raw))
        self.assertEqual(stats.valid, 3)
        self.assertEqual(stats.skipped_duplicate, 0)
        self.assertEqual(
            stats.total_raw,
            stats.valid + stats.skipped_invalid + stats.skipped_example + stats.skipped_duplicate)

    def test_invariant_all_duplicates(self):
        """全部重复（除第一个）：不变量成立。"""
        raw = ["x@gmail.com"] * 10
        recipients, stats = sd.normalize_recipient_list(_raw_list(*raw))
        self.assertEqual(stats.valid, 1)
        self.assertEqual(stats.skipped_duplicate, 9)
        self.assertEqual(
            stats.total_raw,
            stats.valid + stats.skipped_invalid + stats.skipped_example + stats.skipped_duplicate)

    def test_invariant_all_filtered_no_valid(self):
        """全部被过滤（无 valid）：不变量成立。"""
        raw = ["test@example.com", "bad", "", "foo@example.org"]
        recipients, stats = sd.normalize_recipient_list(_raw_list(*raw))
        self.assertEqual(recipients, [])
        self.assertEqual(stats.valid, 0)
        self.assertEqual(
            stats.total_raw,
            stats.valid + stats.skipped_invalid + stats.skipped_example + stats.skipped_duplicate)


if __name__ == "__main__":
    unittest.main()
