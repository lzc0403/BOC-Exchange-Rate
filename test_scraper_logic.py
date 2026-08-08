"""
无 Key 也能验证的逻辑测试（不依赖打码平台，不触碰真实 CSV）。

覆盖：
  1. captcha_id 提取（对线上检索页实时提取 + 片段匹配）
  2. 接口 JSON → 行结构 解析（含“非当日/非本币种”过滤）
  3. 每日选样：策略A（≥10:00最早）/ 策略B（兜底最新）
  4. 去重/追加：重复运行同一天不重复写入；CSV 列顺序契约
  5. “发布日期≠当天则跳过”防护

运行：python test_scraper_logic.py
"""
import os
import sys
import tempfile
import importlib.util
from datetime import date, datetime

import pandas as pd

# 文件名含点（boc_scraper_v6.1.py），无法用普通 import；用 importlib 按路径加载
_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "boc_scraper_v6_1", os.path.join(_HERE, "boc_scraper_v6.1.py"))
boc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(boc)

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

print("=" * 60)
print("2) 解析 + 每日选样（策略A / 策略B）")

TODAY = date(2026, 8, 7)
YEST = date(2026, 8, 6)
mock_data = [
    # 美元 当日，多个快照
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

rows = boc.parse_response(mock_data, "美元", TODAY)
check("仅保留当日+本币种（3条）", len(rows) == 3)
rec_a = boc.select_daily_record(rows, TODAY)
check("策略A 选到 10:05（≥10:00最早，折算价679.0）",
      rec_a is not None and rec_a["发布时间"] == "2026/08/07 10:05:00"
      and rec_a["中行折算价"] == "679.0")

# 策略B：当日只有 <10:00 的快照
mock_b = [{"cname_hbmc": "美元", "hmrj2": "673.1", "cmrj2": "673.1", "mcj2": "676.0",
           "cmcj2": "676.0", "zhzjj2": "679.0", "pjtime": "2026/08/07 09:15:00"}]
rows_b = boc.parse_response(mock_b, "美元", TODAY)
rec_b = boc.select_daily_record(rows_b, TODAY)
check("策略B 兜底选最新（09:15）",
      rec_b is not None and rec_b["发布时间"] == "2026/08/07 09:15:00")

# 发布日期≠当天则跳过：以“无任何记录命中”的日期为目标，应返回 0 条 → select 返回 None
NO_HIT = date(2026, 8, 10)
rows_none = boc.parse_response(mock_data, "美元", NO_HIT)
check("非当日记录被过滤（返回0条 → select 返回 None）",
      len(rows_none) == 0 and boc.select_daily_record(rows_none, NO_HIT) is None)

print("=" * 60)
print("3) 去重 / 追加 / CSV 列顺序契约（临时文件）")

with tempfile.TemporaryDirectory() as td:
    tmp = os.path.join(td, "boc_test_cny.csv")
    row = {"货币名称": "美元", "现汇买入价": "673.7", "现钞买入价": "673.7",
           "现汇卖出价": "676.5", "现钞卖出价": "676.5", "中行折算价": "679.0",
           "发布时间": "2026/08/07 10:05:00", "查询日期": "2026-08-07"}
    # 模拟调用方去重逻辑：先 load_done，命中则跳过 append_row
    if "2026-08-07" not in boc.load_done(tmp):
        boc.append_row(row, tmp)
    if "2026-08-07" not in boc.load_done(tmp):   # 重复当天，应被跳过
        boc.append_row(row, tmp)
    df = pd.read_csv(tmp)
    check("重复当天不重复写入（仍 1 条数据）", len(df) == 1)
    expected_cols = ["货币名称", "现汇买入价", "现钞买入价", "现汇卖出价",
                     "现钞卖出价", "中行折算价", "发布时间", "查询日期"]
    check("CSV 列顺序契约完全一致", list(df.columns) == expected_cols)
    check("查询日期为 YYYY-MM-DD", df["查询日期"].iloc[0] == "2026-08-07")

print("=" * 60)
print(f"结果：PASS={PASS}  FAIL={FAIL}")
sys.exit(1 if FAIL else 0)
