"""
CSV 原子写 + 损坏处理 单元测试（独立文件，不改旧测试语义）
覆盖：
  1. append_row 新建/追加：列顺序契约、utf-8-sig BOM、无 tmp 残留
  2. append_row 前置校验（fail-closed）：必填缺失 / 价格非数值 / 负数 → 拒绝并返回 False
  3. load_done 正常路径返回 set（str 化）
  4. load_done 损坏路径：抛 CsvCorruptError（绝不静默当空集）
  5. append_row 遇到已损坏目标：抛 CsvCorruptError（不覆盖坏数据）
  6. 追加后的数据可被 pd.read_csv 正常读回（原子替换完整性）
"""
import os
import tempfile
import importlib.util
from pathlib import Path
import unittest

import pandas as pd

# 文件名含点（boc_scraper_v6.1.py），用 importlib 按路径加载
_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "boc_scraper_v6_1", os.path.join(_HERE, "boc_scraper_v6.1.py"))
boc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(boc)

BOM = b"\xef\xbb\xbf"


def _row(qdate: str = "2026-08-07", **over):
    """构造一条合法记录（可覆盖字段制造非法场景）。"""
    r = {
        "货币名称": "美元",
        "现汇买入价": "673.7", "现钞买入价": "673.7",
        "现汇卖出价": "676.5", "现钞卖出价": "676.5",
        "中行折算价": "679.0",
        "发布时间": "2026/08/07 10:05:00",
        "查询日期": qdate,
    }
    r.update(over)
    return r


class TestAppendRowAtomic(unittest.TestCase):
    def test_new_then_append_column_order_and_bom(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "t.csv")
            self.assertTrue(boc.append_row(_row("2026-08-07"), p))
            self.assertTrue(boc.append_row(_row("2026-08-08"), p))
            raw = Path(p).read_bytes()
            self.assertEqual(raw[:3], BOM, "应写 utf-8-sig BOM")
            df = pd.read_csv(p)
            self.assertEqual(list(df.columns), boc.CSV_COLUMNS, "列顺序契约一致")
            self.assertEqual(len(df), 2)
            # 无 tmp 残留
            leftovers = [f for f in os.listdir(td) if f.endswith(".tmp")]
            self.assertEqual(leftovers, [])

    def test_append_rejects_bad_rows(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "t.csv")
            self.assertTrue(boc.append_row(_row("2026-08-07"), p))
            # 必填价格为空
            self.assertFalse(boc.append_row(_row("2026-08-08", 现汇买入价=""), p))
            # 价格非数值
            self.assertFalse(boc.append_row(_row("2026-08-08", 现汇卖出价="abc"), p))
            # 价格负数
            self.assertFalse(boc.append_row(_row("2026-08-08", 中行折算价="-5"), p))
            # 查询日期为空
            self.assertFalse(boc.append_row(_row("", ), p))
            # 被拒绝的行不应写入
            df = pd.read_csv(p)
            self.assertEqual(len(df), 1, "非法行应被拒绝写入")

    def test_append_with_internal_field_stripped(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "t.csv")
            r = _row("2026-08-07")
            r["_t"] = object()  # 内部字段应在写前剔除
            self.assertTrue(boc.append_row(r, p))
            df = pd.read_csv(p)
            self.assertNotIn("_t", df.columns)


class TestLoadDone(unittest.TestCase):
    def test_normal_returns_set(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "t.csv")
            self.assertEqual(boc.load_done(p), set(), "文件不存在返回空集")
            boc.append_row(_row("2026-08-07"), p)
            self.assertEqual(boc.load_done(p), {"2026-08-07"})

    def test_corrupt_raises_not_empty(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "t.csv")
            # 截断半行（列数不足，pandas 可读但缺必需列）
            Path(p).write_text("货币名称,现汇买入价\n美元,673.7\n", encoding="utf-8")
            with self.assertRaises(boc.CsvCorruptError):
                boc.load_done(p)
            # 真乱码（无法 UTF-8 解码）
            Path(p).write_bytes(b"\xff\xfe\x00\x01garbage\xff\xff")
            with self.assertRaises(boc.CsvCorruptError):
                boc.load_done(p)

    def test_append_does_not_overwrite_corrupt(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "t.csv")
            Path(p).write_text("货币名称,现汇买入价\n美元,673.7\n", encoding="utf-8")
            before = Path(p).read_text(encoding="utf-8")
            with self.assertRaises(boc.CsvCorruptError):
                boc.append_row(_row("2026-08-07"), p)
            self.assertEqual(Path(p).read_text(encoding="utf-8"), before,
                             "损坏文件不应被覆盖（fail-closed）")

    # ---- QA 复测缺陷1 回归：损坏绝不静默当空 ----
    _HEADER = "货币名称,现汇买入价,现钞买入价,现汇卖出价,现钞卖出价,中行折算价,发布时间,查询日期"

    def test_only_header_raises_not_empty(self):
        """仅表头（全 8 列无数据行）→ 抛 CsvCorruptError，绝不静默当空集。"""
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "h.csv")
            Path(p).write_text(self._HEADER + "\n", encoding="utf-8")
            with self.assertRaises(boc.CsvCorruptError):
                boc.load_done(p)

    def test_narrow_row_raises_not_empty(self):
        """数据行宽<表头（查询日期落 NaN）→ 抛 CsvCorruptError。"""
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "n.csv")
            Path(p).write_text(self._HEADER + "\n美元,1,2,3\n", encoding="utf-8")
            with self.assertRaises(boc.CsvCorruptError):
                boc.load_done(p)

    def test_truncated_tail_raises_not_empty(self):
        """尾部截断最后一行（查询日期落 NaN）→ 抛 CsvCorruptError。"""
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "t.csv")
            Path(p).write_text(self._HEADER + "\n"
                               "美元,673.7,673.7,676.5,676.5,679.0,2026/08/10 10:00:00,2026-08-10\n"
                               "美元,86.5\n", encoding="utf-8")
            with self.assertRaises(boc.CsvCorruptError):
                boc.load_done(p)

    def test_blank_query_date_raises_not_empty(self):
        """查询日期列存在空值（NaN）→ 抛 CsvCorruptError。"""
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "b.csv")
            Path(p).write_text(self._HEADER + "\n"
                               "美元,673.7,673.7,676.5,676.5,679.0,2026/08/01 10:00:00,\n",
                               encoding="utf-8")
            with self.assertRaises(boc.CsvCorruptError):
                boc.load_done(p)

    def test_truncated_tail_mid_date_raises(self):
        """QA 加固建议：尾部截断恰好落在 查询日期 值中间（"2026-08-10"→"2026"）
        → pandas 当字符串而非 NaN，load_done 必须仍判损坏抛 CsvCorruptError。"""
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "m.csv")
            Path(p).write_text(self._HEADER + "\n"
                               "美元,673.7,673.7,676.5,676.5,679.0,2026/08/09 10:00:00,2026-08-09\n"
                               "美元,673.33,673.33,676.16,676.16,678.84,2026/08/10 10:04:55,2026",
                               encoding="utf-8")
            with self.assertRaises(boc.CsvCorruptError):
                boc.load_done(p)


if __name__ == "__main__":
    unittest.main(verbosity=2)
