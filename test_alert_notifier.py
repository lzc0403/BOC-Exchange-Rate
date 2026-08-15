"""
alert_notifier.py 单元测试。

覆盖场景：
  1. ALERT_EMAIL 未配置 → 返回 False，不抛异常
  2. SMTP_SERVER 未配置 → 返回 False
  3. mock smtplib.SMTP → 验证 send_alert 调用了 sendmail/send_message
  4. mock smtplib.SMTP 抛异常 → 返回 False，异常不传播
  5. mask_email 脱敏基本逻辑
  6. mask_hostname 脱敏基本逻辑

运行：
  python -m pytest test_alert_notifier.py -v --tb=short
  python -m unittest test_alert_notifier -v
"""
import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch, MagicMock

import alert_notifier as an


@contextmanager
def env_override(**overrides):
    """安全地临时设置环境变量，退出时恢复原值。

    替代 @patch.dict(os.environ, ...) —— 在 Windows 上 patch.dict 恢复
    超长环境变量（如 ACC_PRODUCT_CONFIG_V3 ~500KB）时会触发 ValueError。
    """
    saved = {}
    for key, val in overrides.items():
        saved[key] = os.environ.get(key)
        if val is None or val == "":
            os.environ.pop(key, None)
        else:
            os.environ[key] = val
    try:
        yield
    finally:
        for key, old_val in saved.items():
            if old_val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_val


class SendAlertMissingConfigTest(unittest.TestCase):
    """ALERT_EMAIL / SMTP_SERVER 等配置缺失时的行为。"""

    def test_send_alert_missing_config(self):
        """ALERT_EMAIL 未配置时返回 False，不抛异常。"""
        with env_override(
            SMTP_SERVER="smtp.example.com",
            SMTP_PORT="587",
            SENDER_EMAIL="sender@example.com",
            SENDER_PASSWORD="dummy-password",
            ALERT_EMAIL="",
        ):
            result = an.send_alert("[告警] 测试", "测试告警正文")
        self.assertFalse(result)

    def test_send_alert_missing_smtp(self):
        """SMTP_SERVER 未配置时返回 False，不抛异常。"""
        with env_override(
            SMTP_SERVER="",
            SMTP_PORT="587",
            SENDER_EMAIL="sender@example.com",
            SENDER_PASSWORD="dummy-password",
            ALERT_EMAIL="alert@example.com",
        ):
            result = an.send_alert("[告警] 测试", "测试告警正文")
        self.assertFalse(result)

    def test_send_alert_missing_sender(self):
        """SENDER_EMAIL 未配置时返回 False。"""
        with env_override(
            SMTP_SERVER="smtp.example.com",
            SMTP_PORT="587",
            SENDER_EMAIL="",
            SENDER_PASSWORD="dummy-password",
            ALERT_EMAIL="alert@example.com",
        ):
            result = an.send_alert("[告警] 测试", "测试告警正文")
        self.assertFalse(result)

    def test_send_alert_invalid_alert_email_format(self):
        """ALERT_EMAIL 格式非法时返回 False。"""
        with env_override(
            SMTP_SERVER="smtp.example.com",
            SMTP_PORT="587",
            SENDER_EMAIL="sender@example.com",
            SENDER_PASSWORD="dummy-password",
            ALERT_EMAIL="not-an-email",
        ):
            result = an.send_alert("[告警] 测试", "测试告警正文")
        self.assertFalse(result)


class SendAlertMockTest(unittest.TestCase):
    """mock smtplib.SMTP 验证调用链。"""

    @staticmethod
    def _make_fake_server():
        """创建一个可作为 context manager 使用的 fake SMTP server。

        smtplib.SMTP 在 send_alert 中以 `with smtplib.SMTP(...) as server:` 使用，
        所以 __enter__ 必须返回 fake_server 自身，否则方法调用会落到子 mock 上。
        """
        fake = MagicMock()
        fake.__enter__.return_value = fake
        fake.__exit__.return_value = False
        return fake

    def test_send_alert_success_mock(self):
        """mock smtplib.SMTP，验证 send_alert 调用了 send_message，返回 True。"""
        fake_server = self._make_fake_server()
        with env_override(
            SMTP_SERVER="smtp.example.com",
            SMTP_PORT="587",
            SENDER_EMAIL="sender@example.com",
            SENDER_PASSWORD="dummy-password",
            ALERT_EMAIL="alert@example.com",
        ), patch("alert_notifier.smtplib.SMTP", return_value=fake_server) as mock_smtp:
            result = an.send_alert("[告警] 测试", "测试告警正文")

        self.assertTrue(result)
        self.assertTrue(mock_smtp.called)
        # 验证连接参数
        args = mock_smtp.call_args[0]
        self.assertEqual(args[0], "smtp.example.com")
        self.assertEqual(args[1], 587)
        # 验证 timeout 传入
        kwargs = mock_smtp.call_args[1]
        self.assertEqual(kwargs.get("timeout"), 30)
        # 验证 starttls + login + send_message 被调用
        fake_server.starttls.assert_called_once()
        fake_server.login.assert_called_once_with("sender@example.com", "dummy-password")
        fake_server.send_message.assert_called_once()
        # 验证邮件 To 字段为 alert@example.com
        sent_msg = fake_server.send_message.call_args[0][0]
        self.assertEqual(sent_msg["To"], "alert@example.com")
        self.assertIn("告警", sent_msg["Subject"])

    def test_send_alert_failure_mock(self):
        """mock smtplib.SMTP 抛异常，验证返回 False 且异常不传播。"""
        with env_override(
            SMTP_SERVER="smtp.example.com",
            SMTP_PORT="587",
            SENDER_EMAIL="sender@example.com",
            SENDER_PASSWORD="dummy-password",
            ALERT_EMAIL="alert@example.com",
        ), patch("alert_notifier.smtplib.SMTP",
                   side_effect=Exception("SMTP connection refused")) as mock_smtp:
            result = an.send_alert("[告警] 测试", "测试告警正文")

        self.assertFalse(result)
        self.assertTrue(mock_smtp.called)

    def test_send_alert_login_failure_returns_false(self):
        """SMTP login 抛异常时返回 False，不传播。"""
        fake_server = self._make_fake_server()
        fake_server.login.side_effect = Exception("Authentication failed")
        with env_override(
            SMTP_SERVER="smtp.example.com",
            SMTP_PORT="587",
            SENDER_EMAIL="sender@example.com",
            SENDER_PASSWORD="dummy-password",
            ALERT_EMAIL="alert@example.com",
        ), patch("alert_notifier.smtplib.SMTP", return_value=fake_server):
            result = an.send_alert("[告警] 测试", "测试告警正文")
        self.assertFalse(result)


class MaskEmailTest(unittest.TestCase):
    """mask_email 脱敏基本逻辑。"""

    def test_mask_email_basic(self):
        """验证邮箱脱敏：test@example.com -> t***@e***.com。"""
        masked = an.mask_email("alert@example.com")
        self.assertEqual(masked, "a***@e***.com")
        self.assertIn("***", masked)
        self.assertNotIn("alert@example.com", masked)

    def test_mask_email_multi_label(self):
        """多标签域名也正确脱敏。"""
        masked = an.mask_email("user@sub.domain.org")
        self.assertIn("***", masked)
        self.assertNotIn("user@sub.domain.org", masked)
        # 末级域名 .org 保留完整
        self.assertTrue(masked.endswith(".org"))

    def test_mask_email_invalid_falls_back(self):
        """空串或非法邮箱退化为 ***@***。"""
        self.assertEqual(an.mask_email(""), "***@***")
        self.assertEqual(an.mask_email("not-an-email"), "***@***")
        self.assertEqual(an.mask_email("@"), "***@***")


class MaskHostnameTest(unittest.TestCase):
    """mask_hostname 脱敏基本逻辑。"""

    def test_mask_hostname_basic(self):
        """验证主机名脱敏：smtp.qq.com -> sm**.*.c*m。"""
        masked = an.mask_hostname("smtp.qq.com")
        self.assertIn("*", masked)
        self.assertNotIn("smtp.qq.com", masked)
        # 应保留末级域名首尾字符
        self.assertTrue(masked.startswith("sm"))

    def test_mask_hostname_strips_protocol(self):
        """剥离协议前缀后脱敏。"""
        masked = an.mask_hostname("smtp://smtp.example.com:587")
        self.assertIn("*", masked)
        self.assertNotIn("smtp.example.com", masked)

    def test_mask_hostname_empty(self):
        """空值返回 <未配置>。"""
        self.assertEqual(an.mask_hostname(""), "<未配置>")
        self.assertEqual(an.mask_hostname(None), "<未配置>")

    def test_mask_hostname_single_label(self):
        """单标签主机名也脱敏（不崩溃）。"""
        masked = an.mask_hostname("localhost")
        self.assertIn("*", masked)
        self.assertNotIn("localhost", masked)


class CheckDataIntegrityTest(unittest.TestCase):
    """_check_data_integrity 回归测试。

    通过 importlib 加载 boc_scraper_pw.py（该文件内部又通过 importlib
    加载 boc_scraper_v6.1.py），测试三种场景：
      1. 今日数据缺失 → 调用 send_alert
      2. 今日数据在位 → 不调用 send_alert
      3. load_done 抛 CsvCorruptError → 仍调用 send_alert，异常不传播
    """

    @classmethod
    def setUpClass(cls):
        """通过 importlib 加载 boc_scraper_pw 模块，供测试使用。"""
        import importlib.util
        from pathlib import Path

        cls._project_dir = Path(__file__).resolve().parent
        spec = importlib.util.spec_from_file_location(
            "boc_scraper_pw", str(cls._project_dir / "boc_scraper_pw.py"))
        cls.pw = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.pw)

    def setUp(self):
        """设置环境变量，避免干扰 send_alert 的配置检查。

        使用 env_override 替代 patch.dict(os.environ, ...)，
        因为 Windows 上 patch.dict 恢复超长环境变量时触发 ValueError。
        """
        self._env_ctx = env_override(
            ALERT_EMAIL="alert@example.com",
            SMTP_SERVER="smtp.example.com",
            SMTP_PORT="587",
            SENDER_EMAIL="sender@example.com",
            SENDER_PASSWORD="dummy-password",
        )
        self._env_ctx.__enter__()

    def tearDown(self):
        self._env_ctx.__exit__(None, None, None)

    def test_missing_today_calls_send_alert(self):
        """load_done 返回不含今日日期的集合 → _check_data_integrity 调用 send_alert。"""
        today_str = self.pw._parse_end_date().strftime(self.pw.DATE_FMT)
        # 返回一个不含 today_str 的集合，模拟数据缺失
        done_without_today = {"2026-01-01", "2026-01-02"}

        with patch.object(self.pw, "load_done", return_value=done_without_today), \
             patch("alert_notifier.send_alert", return_value=True) as mock_alert:
            all_ok, missing = self.pw._check_data_integrity(self.pw._parse_end_date())

        self.assertFalse(all_ok)
        self.assertTrue(len(missing) > 0)
        mock_alert.assert_called_once()
        # 验证告警主题包含日期信息
        subject = mock_alert.call_args[0][0]
        self.assertIn("告警", subject)

    def test_today_present_no_alert(self):
        """load_done 返回包含今日日期的集合 → 不调用 send_alert。"""
        today_str = self.pw._parse_end_date().strftime(self.pw.DATE_FMT)
        done_with_today = {today_str, "2026-01-01"}

        with patch.object(self.pw, "load_done", return_value=done_with_today), \
             patch("alert_notifier.send_alert", return_value=True) as mock_alert:
            all_ok, missing = self.pw._check_data_integrity(self.pw._parse_end_date())

        self.assertTrue(all_ok)
        self.assertEqual(missing, [])
        mock_alert.assert_not_called()

    def test_csv_corrupt_calls_alert_no_propagation(self):
        """load_done 抛 CsvCorruptError → 仍调用 send_alert，异常不传播。"""
        CsvCorruptError = self.pw.boc.CsvCorruptError

        def _raise_corrupt(_path):
            raise CsvCorruptError("test: file is corrupt")

        with patch.object(self.pw, "load_done", side_effect=_raise_corrupt), \
             patch("alert_notifier.send_alert", return_value=True) as mock_alert:
            # 异常不应传播到调用方
            all_ok, missing = self.pw._check_data_integrity(self.pw._parse_end_date())

        self.assertFalse(all_ok)
        self.assertTrue(len(missing) > 0)
        mock_alert.assert_called_once()
        # 验证每个币种都被标记为缺失（2 个币种 = 2 个 missing 条目）
        self.assertEqual(len(missing), len(self.pw.CURRENCIES))


if __name__ == "__main__":
    unittest.main()
