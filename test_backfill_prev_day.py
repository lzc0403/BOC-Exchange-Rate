"""
补抓前一天（backfill）测试 —— 验证 scrape_today 现抓取 [昨天, 今天] 两个日期。

无需打码平台 Key，用 unittest.mock 把 solve_geetest / query_day / load_done /
append_row / fetch_history_page / make_session / log.error 全部 mock。

覆盖场景：
  1. 今天已 done（模拟历史已写）→ 仅抓昨天、今天跳过（验证去重 + 补抓前一天）。
  2. 昨天未 done（模拟昨天失败）→ 昨天被抓取并写入（验证 backfill 生效）。
  3. 两日期都正常 → query_day 对每个币种各 1 次（昨天1+今天1=共4）、solve 仅 1 次（gt 跨日期复用）。
  4. 昨天某币种两次失败 → 标记放弃、今天仍正常抓（互不影响）。

运行：
  python -m pytest test_backfill_prev_day.py -q
  python -m unittest test_backfill_prev_day -v
  python test_backfill_prev_day.py
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
    """构造一条当日、本币种的接口 data 记录，供 mock query_day 返回。"""
    return [{
        "cname_hbmc": currency,
        "hmrj2": "673.7", "cmrj2": "673.7", "mcj2": "676.5",
        "cmcj2": "676.5", "zhzjj2": "679.0",
        "pjtime": d.strftime("%Y/%m/%d 10:05:00"),
    }]


class BackfillPrevDayTest(unittest.TestCase):
    """验证抓取范围 = [昨天, 今天]，且幂等/去重/互不影响。"""

    def setUp(self):
        boc.is_daily = True
        boc.CAPSOLVER_API_KEY = "dummy"   # _has_captcha_key() 据此返回 True
        self.today = date.today()
        self.today_str = self.today.strftime("%Y-%m-%d")
        self.yesterday = self.today - timedelta(days=1)
        self.yesterday_str = self.yesterday.strftime("%Y-%m-%d")

    def _run(self, done_map, query_side_effect):
        html = 'var captchaId = "a4d5e32ec03f74bf0425916cabe1c5a9";'
        with patch.object(boc, "fetch_history_page", return_value=html), \
             patch.object(boc, "make_session", return_value=MagicMock()), \
             patch.object(boc.log, "error") as logerr_mock, \
             patch.object(boc, "append_row") as append_mock, \
             patch.object(boc, "solve_geetest", return_value={
                 "lot_number": "x", "pass_token": "y",
                 "gen_time": "1", "captcha_output": "z"}) as solve_mock, \
             patch.object(boc, "query_day", side_effect=query_side_effect) as query_mock, \
             patch.object(boc, "load_done", side_effect=lambda f: done_map.get(f, set())):
            boc.scrape_today()
        return query_mock, solve_mock, append_mock, logerr_mock

    @staticmethod
    def _query_dates(qm):
        """返回所有 query_day 调用里传入的查询日期 d 集合。"""
        return {c.args[1] for c in qm.call_args_list}

    @staticmethod
    def _append_dates(am):
        """返回所有 append_row 调用里记录所属的查询日期集合。"""
        return {c.args[0]["查询日期"] for c in am.call_args_list}

    def _success_side(self, *a, **k):
        d, currency = a[1], a[2]
        return (make_data(currency, d), "tok")

    def test_1_today_done_only_backfill_yesterday(self):
        """场景1：今天已 done → 仅抓昨天、今天跳过（去重 + 补抓前一天）。"""
        # 两个币种“今天”都已写过；昨天未写 → 仅昨天待抓
        done_map = {
            boc.CURRENCIES["美元"]: {self.today_str},
            boc.CURRENCIES["港币"]: {self.today_str},
        }
        qm, sm, am, _ = self._run(done_map, self._success_side)

        # 今天被去重跳过：不应有任何以“今天”为查询日期的调用
        self.assertNotIn(self.today, self._query_dates(qm),
                         "今天应被去重跳过，不应查询")
        # 昨天被抓取：两币种各 1 次查询 + 1 次写入
        self.assertEqual(qm.call_count, 2, "仅昨天两币种应各查询 1 次")
        self.assertEqual(am.call_count, 2, "仅昨天两币种应各写入 1 次")
        self.assertEqual(self._append_dates(am), {self.yesterday_str},
                         "写入应只针对昨天")

    def test_2_yesterday_not_done_gets_backfilled(self):
        """场景2：昨天未 done（模拟昨天失败）→ 昨天被抓取并写入。"""
        # 什么都不曾写过 → 昨天与今天都待抓，重点验证昨天被补回
        done_map = {}
        qm, sm, am, _ = self._run(done_map, self._success_side)

        # 昨天确实被查询并写入（backfill 生效）
        self.assertIn(self.yesterday, self._query_dates(qm),
                      "昨天应被查询")
        self.assertIn(self.yesterday_str, self._append_dates(am),
                      "昨天应被写入（补抓生效）")
        # 今天也正常抓（预期行为）
        self.assertIn(self.today_str, self._append_dates(am),
                      "今天也应被写入")

    def test_3_both_dates_normal_query_once_each_solve_once(self):
        """场景3：两日期都正常 → 每币种各 1 次（共4）、solve 仅 1 次（gt 跨日期复用）。"""
        done_map = {}
        qm, sm, am, _ = self._run(done_map, self._success_side)

        # 2 日期 × 2 币种 = 4 次查询、4 次写入
        self.assertEqual(am.call_count, 4, "两日期两币种应各写入 1 次")
        self.assertEqual(qm.call_count, 4, "两日期两币种应各查询 1 次")
        self.assertEqual(self._append_dates(am),
                         {self.yesterday_str, self.today_str},
                         "应同时写入昨天与今天")
        # gt 跨币种、跨日期复用：solve 仅 1 次
        self.assertEqual(sm.call_count, 1,
                         "正常流程 solve 仅 1 次，gt 跨币种与跨日期复用")

    def test_4_yesterday_failure_does_not_block_today(self):
        """场景4：昨天某币种两次失败 → 标记放弃、今天仍正常抓（互不影响）。"""
        # 美元始终失败（含昨天与今天），港币始终成功
        def side(*a, **k):
            if a[2] == "美元":
                raise RuntimeError("timeout")
            return (make_data(a[2], a[1]), "tok")

        done_map = {}
        qm, sm, am, logerr = self._run(done_map, side)

        # 美元昨天两次失败 → 日志标记“放弃该日该币种”
        msgs = " ".join(str(c.args) for c in logerr.call_args_list)
        self.assertIn("放弃该日该币种", msgs,
                      "昨天美元连续失败应被标记放弃")

        # 写入仅来自港币（昨天+今天各 1 次），美元任何一天都不应写入
        self.assertEqual(am.call_count, 2, "仅港币两日期各写入 1 次")
        # 验证“今天仍正常抓”：今天港币应被写入
        self.assertIn(self.today_str, self._append_dates(am),
                      "昨天的失败不应阻断今天，今天港币应被写入")
        # 今天港币确实被查询（今天流程跑到了）
        today_calls = [c for c in qm.call_args_list if c.args[1] == self.today]
        self.assertTrue(any(c.args[2] == "港币" for c in today_calls),
                        "今天港币应被查询")


if __name__ == "__main__":
    unittest.main(verbosity=2)
