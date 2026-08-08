"""
QA 独立边界用例（第二层质量关卡补充）—— 由 QA 工程师严过关编写。

仅用 unittest.mock 验证 scrape_today() 控制流；不触网、不需要打码 Key。
目的：补齐工程师测试未显式钉死的两条边界：

  1. 双发 BocCaptchaError（两次都验证码失效）→ query_day 恰好 2 次、
     solve_geetest 因每次失效都重置 gt 而重解恰好 2 次、最终 0 写入。
     （工程师 test_2 只测了“1 次失效 + 第 2 次成功”，未钉“两发都失效”的
      solve 计数，这里是 gt 复用省钱逻辑的关键反向边界。）

  2. 补抓前一天后重跑幂等：第一次运行昨天缺失+今天已 done → 仅补写昨天；
     第二次运行（昨天+今天都已 done）→ 0 查询、0 写入（CI 每天 09:30 重跑
     不会产生重复行）。验证 load_done 去重确实让已存在日期不重复写。

运行（务必单独指定文件，勿与 test_scraper_logic.py 合跑，后者顶层 sys.exit）：
  python -m pytest test_qa_boundary.py -q
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


class QABoundaryTest(unittest.TestCase):
    """边界：双发验证码失效的 solve 计数 + 补抓后重跑幂等。"""

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

    def _success_side(self, *a, **k):
        d, currency = a[1], a[2]
        return (make_data(currency, d), "tok")

    def test_1_double_boccaptchaerror_resets_gt_twice(self):
        """两发都 BocCaptchaError → query 恰好 2 次、solve 恰好 2 次（每次失效重解）、0 写入。"""
        # 昨天 done 跳过，今天仅美元待抓（港币 done 跳过），聚焦美元两次失效
        done_map = {
            boc.CURRENCIES["美元"]: {self.yesterday_str},
            boc.CURRENCIES["港币"]: {self.yesterday_str, self.today_str},
        }

        def side(*a, **k):
            raise boc.BocCaptchaError("captcha invalid (02)")

        qm, sm, am, _ = self._run(done_map, side)

        self.assertEqual(qm.call_count, 2,
                         "两次验证码失效应恰好尝试 2 次，不无限重试")
        self.assertEqual(sm.call_count, 2,
                         "每次 BocCaptchaError 都重置 gt 并重新求解，共恰好 2 次")
        self.assertEqual(am.call_count, 0, "全部失败不应写入任何数据")

    def test_2_full_idempotent_rerun_is_noop(self):
        """两日期全部已写 → 0 查询、0 写入、0 求解（CI 重跑不产生重复行）。"""
        done_map = {
            boc.CURRENCIES["美元"]: {self.yesterday_str, self.today_str},
            boc.CURRENCIES["港币"]: {self.yesterday_str, self.today_str},
        }
        qm, sm, am, _ = self._run(done_map, self._success_side)

        self.assertEqual(qm.call_count, 0, "已写日期不应再查询")
        self.assertEqual(am.call_count, 0, "已写日期不应重复写入（幂等去重）")
        self.assertEqual(sm.call_count, 0, "无查询则不应求解（更不会计费）")

    def test_3_backfill_then_rerun_idempotent(self):
        """第一次运行：昨天缺失+今天已 done → 仅补写昨天；
        第二次运行：昨天+今天都已 done → 0 写入（去重幂等，不重复）。"""
        # 第一次：今天两币种已写，昨天两币种未写 → 仅补写昨天
        done_map_run1 = {
            boc.CURRENCIES["美元"]: {self.today_str},
            boc.CURRENCIES["港币"]: {self.today_str},
        }
        qm1, sm1, am1, _ = self._run(done_map_run1, self._success_side)
        self.assertEqual(am1.call_count, 2, "仅昨天两币种应被补写")
        self.assertEqual({c.args[0]["查询日期"] for c in am1.call_args_list},
                         {self.yesterday_str}, "补写应只针对昨天")
        # 今天被去重跳过
        self.assertNotIn(self.today, {c.args[1] for c in qm1.call_args_list},
                         "今天已 done 应被跳过，不查询")

        # 第二次：昨天+今天都已写 → 完全跳过
        done_map_run2 = {
            boc.CURRENCIES["美元"]: {self.yesterday_str, self.today_str},
            boc.CURRENCIES["港币"]: {self.yesterday_str, self.today_str},
        }
        qm2, sm2, am2, _ = self._run(done_map_run2, self._success_side)
        self.assertEqual(am2.call_count, 0, "补写后重跑应完全跳过（不重复写）")
        self.assertEqual(qm2.call_count, 0, "补写后重跑应无查询")


if __name__ == "__main__":
    unittest.main(verbosity=2)
