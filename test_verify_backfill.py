"""
verify_and_backfill.py 单元测试（unittest.mock，不触网、不需 Key）
覆盖：
  1. find_missing_dates：美元有数据 / 港币无文件 两种起点
  2. validate_record：合法 / 价格为空 / 价格非数字 / 日期不符
  3. backfill 成功：append_row 次数 == 缺失天数、solve 仅 1 次（gt 复用）
  4. backfill 验证码失效重解：首次 BocCaptchaError、次次成功，仍写入且 solve 2 次
  5. backfill 两次失败放弃：进 failed、未写入
"""

import unittest
from datetime import date
from unittest import mock

import verify_and_backfill as vb


# ============================================================
# 1. find_missing_dates
# ============================================================
class TestFindMissingDates(unittest.TestCase):
    @mock.patch.object(vb, "load_done")
    def test_usd_has_data_and_hkd_no_file(self, mock_load):
        def fake_load(path):
            # 美元根目录 CSV 存在且停在 2026-06-24；港币根目录 CSV 不存在
            if "usd" in path:
                return {"2026-06-24"}
            return set()

        mock_load.side_effect = fake_load

        today = date.today()
        usd = vb.find_missing_dates("美元", "boc_usd_cny.csv", date(2026, 6, 24), today, 60)
        hkd = vb.find_missing_dates("港币", "boc_hkd_cny.csv", date(2026, 6, 24), today, 60)

        # 美元：缺失含 2026-06-25..今天，不含已存在的 2026-06-24
        self.assertIn(date(2026, 6, 25), usd)
        self.assertNotIn(date(2026, 6, 24), usd)
        self.assertEqual(usd[-1], today)

        # 港币：从 OUTAGE_START 起、且不早于它
        self.assertGreaterEqual(hkd[0], vb.OUTAGE_START)
        self.assertEqual(hkd[0], vb.OUTAGE_START)
        self.assertNotIn(date(2026, 6, 24), hkd)


# ============================================================
# 2. validate_record
# ============================================================
class TestValidateRecord(unittest.TestCase):
    def _valid(self):
        return {
            "货币名称": "美元",
            "现汇买入价": "688.8",
            "现钞买入价": "683.2",
            "现汇卖出价": "691.72",
            "现钞卖出价": "691.72",
            "中行折算价": "696.46",
            "发布时间": "2026/06/25 10:00:55",
            "查询日期": "2026-06-25",
        }

    def test_valid_passes(self):
        ok, reason = vb.validate_record(self._valid(), "美元", date(2026, 6, 25))
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_empty_price_fails(self):
        rec = self._valid()
        rec["现汇买入价"] = ""
        ok, reason = vb.validate_record(rec, "美元", date(2026, 6, 25))
        self.assertFalse(ok)
        self.assertIn("现汇买入价", reason)

    def test_nan_price_fails(self):
        rec = self._valid()
        rec["现钞买入价"] = "abc"
        ok, reason = vb.validate_record(rec, "美元", date(2026, 6, 25))
        self.assertFalse(ok)
        self.assertIn("现钞买入价", reason)

    def test_date_mismatch_fails(self):
        rec = self._valid()
        rec["发布时间"] = "2026/06/26 10:00:55"  # 日期与查询日不符
        ok, reason = vb.validate_record(rec, "美元", date(2026, 6, 25))
        self.assertFalse(ok)
        self.assertIn("日期不符", reason)

    def test_currency_mismatch_fails(self):
        rec = self._valid()
        rec["货币名称"] = "港币"  # 货币名与期望不符
        ok, reason = vb.validate_record(rec, "美元", date(2026, 6, 25))
        self.assertFalse(ok)
        self.assertIn("货币名称不匹配", reason)

    def test_query_date_mismatch_fails(self):
        rec = self._valid()
        rec["查询日期"] = "2026-06-26"  # 查询日期与期望日不符
        ok, reason = vb.validate_record(rec, "美元", date(2026, 6, 25))
        self.assertFalse(ok)
        self.assertIn("查询日期不符", reason)


# ============================================================
# 3-5. backfill（mock query_day / solve_geetest / append_row）
# ============================================================
def _sample_data(currency, d):
    pjtime = d.strftime("%Y/%m/%d") + " 10:00:55"
    return [{
        "cname_hbmc": currency,
        "hmrj2": "688.8",
        "cmrj2": "683.2",
        "mcj2": "691.72",
        "cmcj2": "691.72",
        "zhzjj2": "696.46",
        "pjtime": pjtime,
    }]


class TestBackfill(unittest.TestCase):
    def _gt(self):
        return {"lot_number": "x", "captcha_output": "y", "pass_token": "z", "gen_time": "1"}

    @mock.patch.object(vb, "append_row")
    @mock.patch.object(vb, "solve_geetest")
    @mock.patch.object(vb, "query_day")
    def test_backfill_success_reuses_gt(self, mock_query, mock_solve, mock_append):
        def qd(session, d, currency, gt, token=None):
            return _sample_data(currency, d), "tok"

        mock_query.side_effect = qd
        mock_solve.return_value = self._gt()

        missing = {"美元": [date(2026, 6, 25), date(2026, 6, 26), date(2026, 6, 27)]}
        gt_ref = {"gt": None, "token": None}
        token_ref = {"token": None}

        res = vb.backfill(object(), gt_ref, token_ref, missing)

        self.assertEqual(mock_append.call_count, 3)
        self.assertEqual(mock_solve.call_count, 1)  # gt 复用，仅解一次
        self.assertEqual(len(res["filled"].get("美元", [])), 3)
        self.assertEqual(len(res["failed"].get("美元", [])), 0)

    @mock.patch.object(vb, "append_row")
    @mock.patch.object(vb, "solve_geetest")
    @mock.patch.object(vb, "query_day")
    def test_backfill_captcha_renew(self, mock_query, mock_solve, mock_append):
        calls = {"n": 0}

        def qd(session, d, currency, gt, token=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise vb.BocCaptchaError("captcha invalid")
            return _sample_data(currency, d), "tok"

        mock_query.side_effect = qd
        mock_solve.return_value = self._gt()

        missing = {"美元": [date(2026, 6, 25)]}
        gt_ref = {"gt": None, "token": None}
        token_ref = {"token": None}

        res = vb.backfill(object(), gt_ref, token_ref, missing)

        self.assertEqual(mock_append.call_count, 1)  # 该日期仍写入
        self.assertEqual(mock_solve.call_count, 2)    # 失效重解一次
        self.assertIn(date(2026, 6, 25), res["filled"].get("美元", []))

    @mock.patch.object(vb, "append_row")
    @mock.patch.object(vb, "solve_geetest")
    @mock.patch.object(vb, "query_day")
    def test_backfill_give_up_after_two_fails(self, mock_query, mock_solve, mock_append):
        def qd(session, d, currency, gt, token=None):
            raise RuntimeError("network timeout")

        mock_query.side_effect = qd
        mock_solve.return_value = self._gt()

        missing = {"美元": [date(2026, 6, 25)]}
        gt_ref = {"gt": None, "token": None}
        token_ref = {"token": None}

        res = vb.backfill(object(), gt_ref, token_ref, missing)

        self.assertEqual(mock_append.call_count, 0)  # 未写入
        self.assertEqual(len(res["failed"].get("美元", [])), 1)
        self.assertEqual(res["failed"]["美元"][0][0], date(2026, 6, 25))

    @mock.patch.object(vb, "append_row")
    @mock.patch.object(vb, "solve_geetest")
    @mock.patch.object(vb, "query_day")
    def test_backfill_empty_response_skipped_not_failed(self, mock_query, mock_solve, mock_append):
        # 边界用例：接口当日返回空 data（respStatus=00 但 data=[]）
        # → parse_response 返回 [] → select_daily_record 返回 None（当日无牌价）
        def qd(session, d, currency, gt, token=None):
            return [], "tok"

        mock_query.side_effect = qd
        mock_solve.return_value = self._gt()

        missing = {"美元": [date(2026, 6, 25)]}
        gt_ref = {"gt": None, "token": None}
        token_ref = {"token": None}

        res = vb.backfill(object(), gt_ref, token_ref, missing)

        # B1 核心回归点：当日无牌价日不得计入「已补」filled（它并未真正写入 CSV）
        self.assertNotIn(date(2026, 6, 25), res["filled"].get("美元", []))
        # 也不应计入失败（规格「不计失败、不重试」）
        failed_dates = [d for d, _ in res["failed"].get("美元", [])]
        self.assertNotIn(date(2026, 6, 25), failed_dates)
        # 应正确归入 skipped（既不入 filled 也不入 failed）
        self.assertIn(date(2026, 6, 25), res["skipped"].get("美元", []))
        self.assertEqual(mock_append.call_count, 0)

    @mock.patch.object(vb, "append_row")
    @mock.patch.object(vb, "solve_geetest")
    @mock.patch.object(vb, "query_day")
    def test_backfill_empty_response_in_skipped(self, mock_query, mock_solve, mock_append):
        # 新增用例：专门校验 result["skipped"] 含「当日无牌价」日，
        # 且 filled/failed 同时为空（三态互斥，口径正确）。
        def qd(session, d, currency, gt, token=None):
            return [], "tok"

        mock_query.side_effect = qd
        mock_solve.return_value = self._gt()

        d = date(2026, 6, 25)
        missing = {"美元": [d]}
        gt_ref = {"gt": None, "token": None}
        token_ref = {"token": None}

        res = vb.backfill(object(), gt_ref, token_ref, missing)

        # skipped 必须包含该日
        self.assertIn(d, res["skipped"].get("美元", []))
        # 三态互斥：filled 与 failed 对该日均无记录
        self.assertEqual(len(res["filled"].get("美元", [])), 0)
        self.assertEqual(len(res["failed"].get("美元", [])), 0)
        self.assertEqual(mock_append.call_count, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
