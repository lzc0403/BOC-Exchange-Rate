"""
无 Key 也能验证的逻辑测试（不依赖打码平台，不触碰真实 CSV）。

覆盖：
  1. captcha_id 提取（对线上检索页实时提取 + 片段匹配）
  2. 接口 JSON → 行结构 解析（含"非当日/非本币种"过滤）
  3. 每日选样：策略A（≥10:00最早）/ 策略B（兜底最新）
  4. 去重/追加：重复运行同一天不重复写入；CSV 列顺序契约
  5. "发布日期≠当天则跳过"防护

运行方式：
  python -m pytest test_scraper_logic.py -v        # pytest 模式
  python test_scraper_logic.py                      # 脚本模式（含线上 captcha 验证）
"""
import os
import sys
import tempfile
import importlib.util
import unittest
from datetime import date, datetime

import pandas as pd

# 文件名含点（boc_scraper_v6.1.py），无法用普通 import；用 importlib 按路径加载
_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "boc_scraper_v6_1", os.path.join(_HERE, "boc_scraper_v6.1.py"))
boc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(boc)


class CaptchaIdTest(unittest.TestCase):
    """captcha_id 提取逻辑。"""

    def test_snippet_match(self):
        """片段匹配 captcha_id。"""
        snippet = 'var captchaId = "a4d5e32ec03f74bf0425916cabe1c5a9"; initGeetest({captchaId: captchaId})'
        cid = boc.extract_captcha_id(snippet)
        self.assertEqual(cid, "a4d5e32ec03f74bf0425916cabe1c5a9")


class ParseAndSelectTest(unittest.TestCase):
    """接口解析 + 每日选样（策略A / 策略B）。"""

    TODAY = date(2026, 8, 7)

    def setUp(self):
        self.mock_data = [
            {"cname_hbmc": "美元", "hmrj2": "673.1", "cmrj2": "673.1", "mcj2": "676.0",
             "cmcj2": "676.0", "zhzjj2": "679.0", "pjtime": "2026/08/07 09:15:00"},
            {"cname_hbmc": "美元", "hmrj2": "673.7", "cmrj2": "673.7", "mcj2": "676.5",
             "cmcj2": "676.5", "zhzjj2": "679.0", "pjtime": "2026/08/07 10:05:00"},
            {"cname_hbmc": "美元", "hmrj2": "673.9", "cmrj2": "673.9", "mcj2": "676.7",
             "cmcj2": "676.7", "zhzjj2": "679.2", "pjtime": "2026/08/07 11:30:00"},
            # 港币 当日（应被币种过滤排除）
            {"cname_hbmc": "港币", "hmrj2": "85.8", "cmrj2": "85.8", "mcj2": "86.2",
             "cmcj2": "86.2", "zhzjj2": "86.5", "pjtime": "2026/08/07 10:05:00"},
            # 美元 昨日（应被日期过滤排除）
            {"cname_hbmc": "美元", "hmrj2": "670.0", "cmrj2": "670.0", "mcj2": "673.0",
             "cmcj2": "673.0", "zhzjj2": "676.0", "pjtime": "2026/08/06 10:05:00"},
        ]

    def test_filter_currency_and_date(self):
        """仅保留当日+本币种（3条）。"""
        rows = boc.parse_response(self.mock_data, "美元", self.TODAY)
        self.assertEqual(len(rows), 3)

    def test_strategy_a_earliest_after_10(self):
        """策略A 选到 10:05（≥10:00最早，折算价679.0）。"""
        rows = boc.parse_response(self.mock_data, "美元", self.TODAY)
        rec = boc.select_daily_record(rows, self.TODAY)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["发布时间"], "2026/08/07 10:05:00")
        self.assertEqual(rec["中行折算价"], "679.0")

    def test_strategy_b_fallback_latest(self):
        """策略B 兜底选最新（09:15）。"""
        mock_b = [{"cname_hbmc": "美元", "hmrj2": "673.1", "cmrj2": "673.1", "mcj2": "676.0",
                   "cmcj2": "676.0", "zhzjj2": "679.0", "pjtime": "2026/08/07 09:15:00"}]
        rows_b = boc.parse_response(mock_b, "美元", self.TODAY)
        rec = boc.select_daily_record(rows_b, self.TODAY)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["发布时间"], "2026/08/07 09:15:00")

    def test_no_hit_date_returns_none(self):
        """非当日记录被过滤（返回0条 → select 返回 None）。"""
        no_hit = date(2026, 8, 10)
        rows = boc.parse_response(self.mock_data, "美元", no_hit)
        self.assertEqual(len(rows), 0)
        self.assertIsNone(boc.select_daily_record(rows, no_hit))


class DedupAppendTest(unittest.TestCase):
    """去重 / 追加 / CSV 列顺序契约（临时文件）。"""

    def test_dedup_and_column_order(self):
        row = {"货币名称": "美元", "现汇买入价": "673.7", "现钞买入价": "673.7",
               "现汇卖出价": "676.5", "现钞卖出价": "676.5", "中行折算价": "679.0",
               "发布时间": "2026/08/07 10:05:00", "查询日期": "2026-08-07"}
        with tempfile.TemporaryDirectory() as td:
            tmp = os.path.join(td, "boc_test_cny.csv")
            if "2026-08-07" not in boc.load_done(tmp):
                boc.append_row(row, tmp)
            if "2026-08-07" not in boc.load_done(tmp):
                boc.append_row(row, tmp)
            df = pd.read_csv(tmp)
            self.assertEqual(len(df), 1, "重复当天不重复写入（仍 1 条数据）")
            expected_cols = ["货币名称", "现汇买入价", "现钞买入价", "现汇卖出价",
                             "现钞卖出价", "中行折算价", "发布时间", "查询日期"]
            self.assertEqual(list(df.columns), expected_cols, "CSV 列顺序契约完全一致")
            self.assertEqual(df["查询日期"].iloc[0], "2026-08-07", "查询日期为 YYYY-MM-DD")


if __name__ == "__main__":
    # 脚本模式：含线上 captcha_id 提取验证（需要网络）
    PASS = 0
    FAIL = 0

    def check(name: str, cond: bool):
        global PASS, FAIL
        if cond:
            PASS += 1
            print(f"  [PASS] {name}")
        else:
            FAIL += 1
            print(f"  [FAIL] {name}")

    print("=" * 60)
    print("1) captcha_id 提取")
    snippet = 'var captchaId = "a4d5e32ec03f74bf0425916cabe1c5a9"; initGeetest({captchaId: captchaId})'
    cid_snip = boc.extract_captcha_id(snippet)
    check("片段匹配 captcha_id", cid_snip == "a4d5e32ec03f74bf0425916cabe1c5a9")

    try:
        html = boc.fetch_history_page()
        cid_live = boc.extract_captcha_id(html)
        check("线上检索页成功提取 captcha_id", bool(cid_live) and len(cid_live) >= 16)
        print(f"       线上 captcha_id = {cid_live}（兜底常量 = {boc.GEETEST_CAPTCHA_ID}）")
    except Exception as e:
        print(f"  [WARN] 线上提取失败（可能无网络）: {e}")

    # 运行 pytest 用例
    print("=" * 60)
    print("2-3) 运行 pytest 测试...")
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
