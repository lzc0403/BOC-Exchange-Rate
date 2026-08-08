"""
每日查询重试策略测试（无需打码平台 Key，用 unittest.mock 验证逻辑）。

被测逻辑：boc_scraper_v6.1.py 的 scrape_today()
  - 抓取日期范围 = [昨天, 今天]（补充前一天防漏抓；已写过的日期被去重跳过）。
  - 每个币种独立查询：单次执行，仅当本次调用出错时才重试一次（最多 2 次）。
  - gt4 解(gt) 仅在为 None 时求解，成功求解后在币种间、日期间复用，避免无谓计费。
  - rec is None（当日无牌价）视为正常，不重试。

覆盖场景（以“今天”为目标做隔离，昨天用 done 去重跳过）：
  1. 单次成功不重试：query_day 首次即成功 → 仅尝试 1 次、写入 1 次。
  2. 失败重试一次后成功：首次 BocCaptchaError，第二次成功 → 最多 2 次、最终写入。
  3. 两次都失败放弃：两次都抛异常 → 恰好 2 次、未写入、日志标记“放弃该日该币种”。
  4. gt 复用计数：美元成功后港币不重新 solve（solve 仅 1 次）。
  5. rec is None 不重试：query_day 返回空 data → 仅查询 1 次，不重试。

运行：
  python -m pytest test_retry_policy.py -q
  python -m unittest test_retry_policy -v
  python test_retry_policy.py
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


class RetryPolicyTest(unittest.TestCase):
    """验证“每个币种单次执行、失败仅重试一次（最多 2 次）”策略（隔离到“今天”）。"""

    def setUp(self):
        # 让 scrape_today 进入每日模式且认为已配置打码 Key（不真正调用打码平台）
        boc.is_daily = True
        boc.CAPSOLVER_API_KEY = "dummy"   # _has_captcha_key() 据此返回 True
        self.today = date.today()
        self.today_str = self.today.strftime("%Y-%m-%d")
        self.yesterday = self.today - timedelta(days=1)
        self.yesterday_str = self.yesterday.strftime("%Y-%m-%d")

    def _run(self, done_map, query_side_effect, solve_return=None):
        """执行一次 scrape_today，返回 (query_mock, solve_mock, append_mock, logerr_mock)。

        done_map: {output_file: set(done_dates)} —— 控制哪些 (币种,日期) 已写过。
        为把“重试策略”隔离到今天，测试里通常把“昨天”设为已 done 以跳过。
        query_side_effect 接收 (session, d, currency, gt, token)，需用 d 构造匹配数据。
        """
        solve_return = solve_return or {
            "lot_number": "x", "pass_token": "y",
            "gen_time": "1", "captcha_output": "z",
        }
        # 提供含 captcha_id 的 HTML，确保 extract_captcha_id 能提取（不触网）
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

    def _success_side(self, *a, **k):
        """通用成功 side：用实际查询日期 d(a[1]) 与币种(a[2]) 构造返回数据。"""
        d, currency = a[1], a[2]
        return (make_data(currency, d), "tok")

    def test_1_single_success_no_retry(self):
        """场景1：query_day 首次即成功 → 仅尝试 1 次、append 1 次、solve 1 次。"""
        # 昨天两币种都 done（跳过），今天仅美元待抓、港币 done（跳过）
        done_map = {
            boc.CURRENCIES["美元"]: {self.yesterday_str},
            boc.CURRENCIES["港币"]: {self.yesterday_str, self.today_str},
        }
        qm, sm, am, _ = self._run(done_map, self._success_side)

        self.assertEqual(qm.call_count, 1, "正常成功应仅查询 1 次，不重试")
        self.assertEqual(am.call_count, 1, "应仅写入 1 次")
        self.assertEqual(sm.call_count, 1, "美元首次求解 1 次即可")
        written_file = am.call_args_list[0][0][1]
        self.assertEqual(written_file, boc.CURRENCIES["美元"])

    def test_2_fail_then_retry_success(self):
        """场景2：首次 BocCaptchaError，第二次成功 → 最多 2 次、最终写入、失效重解 2 次。"""
        done_map = {
            boc.CURRENCIES["美元"]: {self.yesterday_str},
            boc.CURRENCIES["港币"]: {self.yesterday_str, self.today_str},
        }
        state = {"n": 0}

        def side(*a, **k):
            state["n"] += 1
            if state["n"] == 1:
                raise boc.BocCaptchaError("captcha invalid")
            return self._success_side(*a, **k)

        qm, sm, am, _ = self._run(done_map, side)

        self.assertEqual(qm.call_count, 2, "失败应触发第 2 次尝试")
        self.assertEqual(am.call_count, 1, "第 2 次成功应写入 1 次")
        self.assertEqual(sm.call_count, 2, "验证码失效重解：应重新求解 2 次")

    def test_3_two_failures_give_up(self):
        """场景3：两次都抛异常 → 恰好 2 次、未写入、日志标记“放弃该日该币种”。"""
        done_map = {
            boc.CURRENCIES["美元"]: {self.yesterday_str},
            boc.CURRENCIES["港币"]: {self.yesterday_str, self.today_str},
        }

        def side(*a, **k):
            raise RuntimeError("timeout")

        qm, sm, am, logerr = self._run(done_map, side)

        self.assertEqual(qm.call_count, 2, "连续失败应恰好尝试 2 次，不再无限重试")
        self.assertEqual(am.call_count, 0, "失败不应写入任何数据")
        msgs = " ".join(str(c.args) for c in logerr.call_args_list)
        self.assertIn("放弃该日该币种", msgs, "应记录‘连续 N 次失败，放弃该日该币种’日志")

    def test_4_gt_reuse_across_currencies(self):
        """场景4：美元成功后港币不重新 solve（solve 仅 1 次），两币种各写入 1 次。"""
        # 昨天两币种都 done（跳过），今天美元+港币都待抓
        done_map = {
            boc.CURRENCIES["美元"]: {self.yesterday_str},
            boc.CURRENCIES["港币"]: {self.yesterday_str},
        }
        qm, sm, am, _ = self._run(done_map, self._success_side)

        self.assertEqual(sm.call_count, 1, "正常流程仅求解 1 次，港币复用同一 gt")
        self.assertEqual(qm.call_count, 2, "两个币种各查询 1 次")
        self.assertEqual(am.call_count, 2, "两个币种各写入 1 次")

    def test_5_no_retry_when_rec_none(self):
        """场景5：rec is None（当日无牌价）→ 仅查询 1 次，不重试、不写入。"""
        done_map = {
            boc.CURRENCIES["美元"]: {self.yesterday_str},
            boc.CURRENCIES["港币"]: {self.yesterday_str, self.today_str},
        }
        # query_day 返回空 data → parse 为空 → select 返回 None（非错误）
        qm, sm, am, _ = self._run(done_map, lambda *a, **k: ([], "tok"))

        self.assertEqual(qm.call_count, 1, "空结果属正常情况，不应重试")
        self.assertEqual(am.call_count, 0, "无牌价不应写入")
        self.assertEqual(sm.call_count, 1, "首次求解 1 次，未触发重试求解")

    def test_6_timeout_does_not_reset_gt(self):
        """场景6：首次普通异常(超时,非BocCaptchaError)、第二次成功 →
        solve 仅 1 次（gt 复用、不因普通异常无谓重解），最终写入成功。"""
        # 昨天两币种 done（跳过），今天仅美元待抓、港币 done（跳过）
        done_map = {
            boc.CURRENCIES["美元"]: {self.yesterday_str},
            boc.CURRENCIES["港币"]: {self.yesterday_str, self.today_str},
        }
        state = {"n": 0}

        def side(*a, **k):
            state["n"] += 1
            if state["n"] == 1:
                # 普通查询超时（非验证码失效），不应清空 gt
                raise RuntimeError("timeout")
            return self._success_side(*a, **k)

        qm, sm, am, _ = self._run(done_map, side)

        self.assertEqual(qm.call_count, 2, "超时触发第 2 次尝试")
        self.assertEqual(am.call_count, 1, "重试成功后应写入 1 次")
        self.assertEqual(sm.call_count, 1,
                         "普通超时不应重置 gt，solve 仅 1 次（gt 复用，节省 CapSolver 计费）")
        written_file = am.call_args_list[0][0][1]
        self.assertEqual(written_file, boc.CURRENCIES["美元"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
