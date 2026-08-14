"""
verify_csv.py 单元测试（独立文件，不改旧测试语义）
覆盖：
  1. 文件不存在 → fail
  2. 必需列缺失 → fail
  3. 无数据行（仅表头）→ fail
  4. 查询日期格式非法 → fail
  5. 查询日期重复 → fail
  6. 查询日期非严格单调递增 → fail
  7. 价格缺失 / 非数值 / 负数 → fail
  8. 最新日期超过 今日+1 → fail
  9. 合法文件 → pass
"""
import os
import tempfile
from datetime import date, timedelta
from pathlib import Path
import unittest

import verify_csv as vc


def _valid_rows():
    """构造一个连续两日、全部合法的数据行。"""
    today = date.today()
    d1 = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    d2 = today.strftime("%Y-%m-%d")
    return [
        ["港币", "86.73", "86.73", "87.07", "87.07", "87.01",
         f"{d1} 10:00:40", d1],
        ["港币", "86.55", "86.55", "86.89", "86.89", "86.94",
         f"{d2} 10:02:57", d2],
    ]


def _write(tmp_dir, name, rows, header=None):
    header = header or vc.CSV_COLUMNS
    p = Path(tmp_dir) / name
    with open(p, "w", encoding="utf-8-sig", newline="") as f:
        f.write(",".join(header) + "\n")
        for r in rows:
            f.write(",".join(str(x) for x in r) + "\n")
    return str(p)


class TestVerifyCsv(unittest.TestCase):
    def test_missing_file(self):
        errs = vc.validate_csv("/nonexistent/not_there.csv")
        self.assertTrue(any("不存在" in e for e in errs))

    def test_missing_required_columns(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "x.csv"
            p.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
            errs = vc.validate_csv(str(p))
            self.assertTrue(any("缺少必需列" in e for e in errs))

    def test_header_only_fails(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write(td, "h.csv", [])
            errs = vc.validate_csv(p)
            self.assertTrue(any("无任何数据行" in e for e in errs))

    def test_invalid_date_format(self):
        with tempfile.TemporaryDirectory() as td:
            rows = _valid_rows()
            rows[0][7] = "08/07/2026"  # 非法格式
            p = _write(td, "d.csv", rows)
            errs = vc.validate_csv(p)
            self.assertTrue(any("格式非法" in e for e in errs))

    def test_duplicate_dates(self):
        with tempfile.TemporaryDirectory() as td:
            rows = _valid_rows()
            rows[1][7] = rows[0][7]  # 重复
            p = _write(td, "dup.csv", rows)
            errs = vc.validate_csv(p)
            self.assertTrue(any("重复" in e for e in errs))

    def test_monotonic_increasing(self):
        with tempfile.TemporaryDirectory() as td:
            rows = _valid_rows()
            rows[0][7], rows[1][7] = rows[1][7], rows[0][7]  # 乱序（后行 <= 前行）
            p = _write(td, "mono.csv", rows)
            errs = vc.validate_csv(p)
            self.assertTrue(any("单调递增" in e for e in errs))

    def test_price_empty(self):
        with tempfile.TemporaryDirectory() as td:
            rows = _valid_rows()
            rows[0][1] = ""
            p = _write(td, "pe.csv", rows)
            errs = vc.validate_csv(p)
            self.assertTrue(any("缺失" in e for e in errs))

    def test_price_non_numeric(self):
        with tempfile.TemporaryDirectory() as td:
            rows = _valid_rows()
            rows[0][4] = "abc"
            p = _write(td, "pn.csv", rows)
            errs = vc.validate_csv(p)
            self.assertTrue(any("非数值" in e for e in errs))

    def test_price_negative(self):
        with tempfile.TemporaryDirectory() as td:
            rows = _valid_rows()
            rows[0][5] = "-87.01"
            p = _write(td, "neg.csv", rows)
            errs = vc.validate_csv(p)
            self.assertTrue(any("负数" in e for e in errs))

    def test_price_nan_inf_fail(self):
        """QA 复测缺陷2 回归：nan/inf（含大小写、正负）必须判 fail，退出码非 0。"""
        for bad_val in ("nan", "NaN", "NAN", "inf", "-inf", "Infinity", "-Infinity"):
            with tempfile.TemporaryDirectory() as td:
                rows = _valid_rows()
                rows[0][1] = bad_val
                p = _write(td, "bad.csv", rows)
                errs = vc.validate_csv(p)
                self.assertTrue(any("非数值" in e or "非有限" in e for e in errs),
                                f"{bad_val!r} 应被判定为非合法价格")
            self.assertIsNone(vc._parse_price(bad_val), f"{bad_val!r} 应解析为 None")

    def test_future_date_fails(self):
        with tempfile.TemporaryDirectory() as td:
            rows = _valid_rows()
            future = (date.today() + timedelta(days=5)).strftime("%Y-%m-%d")
            rows[1][7] = future
            rows[1][6] = f"{future} 10:00:00"
            p = _write(td, "fut.csv", rows)
            errs = vc.validate_csv(p)
            self.assertTrue(any("超过" in e for e in errs))

    def test_valid_passes(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write(td, "ok.csv", _valid_rows())
            errs = vc.validate_csv(p)
            self.assertEqual(errs, [])

    def test_cli_explicit_csv(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write(td, "ok.csv", _valid_rows())
            rc = vc.main(["--csv", p])
            self.assertEqual(rc, 0)
            # 坏文件 → 非 0
            bad = Path(td) / "bad.csv"
            bad.write_text("货币名称,现汇买入价\n美元,673.7\n", encoding="utf-8")
            rc2 = vc.main(["--csv", str(bad)])
            self.assertNotEqual(rc2, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)