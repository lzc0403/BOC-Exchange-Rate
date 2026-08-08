"""
独立边界测试（QA 补充，第二层质量关卡）— 最终版适配。

最终版 scrape_today 抓取范围 = [昨天, 今天]，且 except Exception（超时）不再重置 gt。
本文件补强工程师套件（test_retry_policy.py / test_backfill_prev_day.py）未独立断言的：
  - 跨币种 gt 持久化：某币种首错 BocCaptchaError（重解#2）恢复后，同日期下一币种复用该 gt
    （solve 总额=2 而非 3），防重复计费。
  - rec is None 不误清空 gt：某币种当日无牌价（不重试、保留 gt）后，同日期下一币种复用同一 gt
    （solve 总额=1）。

为把“重试策略”隔离到“今天”，与工程师 test_retry_policy.py 保持一致：把“昨天”设为两币种均 done 以跳过。

运行（单独跑，避免与含 sys.exit 的 test_scraper_logic.py 合跑）：
  python -m pytest test_retry_policy_extra.py -q
"""
import os
import importlib.util
from datetime import date, timedelta
from unittest.mock import patch, MagicMock
import unittest

# 文件名含点（boc_scraper_v6.1.py），无法用普通 import；用 importlib 按路径加载
_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "boc_scraper_v6_1", os.path.join(_HERE, "boc_scraper_v6.1.py"))
boc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(boc)


def make_data(currency: str, d: date) -> list:
    """构造一条“与查询日期 d 匹配”的当日、本币种接口 data 记录。"""
    return [{
        "cname_hbmc": currency,
        "hmrj2": "673.7", "cmrj2": "673.7", "mcj2": "676.5",
        "cmcj2": "676.5", "zhzjj2": "679.0",
        "pjtime": d.strftime("%Y/%m/%d 10:05:00"),
    }]


class RetryPolicyBoundaryTest(unittest.TestCase):
    """补强边界：跨币种 gt 持久化（重解恢复 / rec-None 保留）。"""

    def setUp(self):
        boc.is_daily = True
        boc.CAPSOLVER_API_KEY = "dummy"   # _has_captcha_key() 据此返回 True
        self.today = date.today()
        self.today_str = self.today.strftime("%Y-%m-%d")
        self.yesterday = self.today - timedelta(days=1)
        self.yesterday_str = self.yesterday.strftime("%Y-%m-%d")

    def _run(self, done_map, query_side_effect, solve_return=None):
        solve_return = solve_return or {
            "lot_number": "x", "pass_token": "y",
            "gen_time": "1", "captcha_output": "z",
        }
        html = 'var captchaId = "a4d5e32ec03f74bf0425916cabe1c5a9";'
        with patch.object(boc, "fetch_history_page", return_value=html), \
             patch.object(boc, "make_session", return_value=MagicMock()), \
             patch.object(boc.log, "error") as logerr_mock, \
             patch.object(boc, "append_row") as append_mock, \
             patch.object(boc, "solve_geetest", return_value=solve_return) as solve_mock, \
             patch.object(boc, "query_day", side_effect=query_side_effect) as query_mock, \
             patch.object(boc, "load_done", side_effect=lambda f: done_map.get(f, set())):
            boc.scrape_today()
        return query_mock, solve_mock, append_mock, logerr_mock

    def _skip_yesterday_done(self):
        """把“昨天”设为两币种均 done，将测试隔离到“今天”。"""
        return {
            boc.CURRENCIES["美元"]: {self.yesterday_str},
            boc.CURRENCIES["港币"]: {self.yesterday_str},
        }

    def test_b2_gt_reused_after_midstream_recovery(self):
        """边界B：今天美元首错验证码失效(重解#2)后成功，港币复用恢复后的 gt。
        验证跨币种 gt 持久化：solve 总额=2(而非3)，两币种各写入 1 次。"""
        done_map = self._skip_yesterday_done()
        state = {"n": 0}

        def side(*a, **k):
            state["n"] += 1
            d, currency = a[1], a[2]
            if currency == "美元" and state["n"] == 1:
                raise boc.BocCaptchaError("invalid")
            return (make_data(currency, d), "tok")

        qm, sm, am, _ = self._run(done_map, side)
        self.assertEqual(sm.call_count, 2,
                         "美元重解1次+港币复用，solve 应为2而非3（避免重复计费）")
        self.assertEqual(am.call_count, 2, "两个币种各写入 1 次")
        written_files = [c.args[1] for c in am.call_args_list]
        self.assertIn(boc.CURRENCIES["美元"], written_files)
        self.assertIn(boc.CURRENCIES["港币"], written_files)

    def test_b3_rec_none_preserves_gt_for_next_currency(self):
        """边界C：今天美元当日无牌价(rec None, 不重试, 保留 gt)，港币随后成功并复用同一 gt。
        验证 rec is None 分支不会误清空 gt 导致港币重复计费：solve 总额=1，仅港币写入 1 次。"""
        done_map = self._skip_yesterday_done()

        def side(*a, **k):
            d, currency = a[1], a[2]
            if currency == "美元":
                return ([], "tok")   # 当日无牌价 → rec None
            return (make_data("港币", d), "tok")

        qm, sm, am, _ = self._run(done_map, side)
        self.assertEqual(sm.call_count, 1,
                         "美元rec None不应清空gt，港币应复用(共1次)")
        self.assertEqual(qm.call_count, 2, "美元1次 + 港币1次")
        self.assertEqual(am.call_count, 1, "仅港币写入 1 次")
        self.assertEqual(am.call_args_list[0].args[1], boc.CURRENCIES["港币"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
