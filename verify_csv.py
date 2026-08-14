r"""
CSV 完整性校验脚本（供 CI 门禁调用）
================================================================================
校验 boc_usd_cny.csv / boc_hkd_cny.csv（可用 --csv <path> 指定单文件）：

  1. 存在性：文件必须存在；
  2. 可解析：必须是合法 UTF-8(-sig) CSV，行长度与表头一致；
  3. 必需列存在：货币名称 / 现汇买入价 / 现钞买入价 / 现汇卖出价 /
                现钞卖出价 / 中行折算价 / 发布时间 / 查询日期；
  4. 查询日期：格式合法（YYYY-MM-DD）、无重复、严格单调递增（后一行日期 > 前一行）；
  5. 价格字段：缺失视为失败；非数值 / 负数视为失败；
  6. 最新日期不超过 今日+1（容忍时区差 1 天），超过视为失败；
  7. 无任何数据行（仅表头）视为失败（数据有效性门禁）。

输出：日志打印校验项与失败明细 + 退出码（0=通过，非 0=失败），供 CI 直接判断。

用法：
  python verify_csv.py                 # 校验默认两个文件
  python verify_csv.py --csv boc_usd_cny.csv   # 只校验单文件
"""
import argparse
import csv
import logging
import math
import sys
from datetime import date, timedelta
from pathlib import Path

# CSV 列顺序契约（与 boc_scraper_v6.1.CSV_COLUMNS 保持一致；勿改）
CSV_COLUMNS = [
    "货币名称", "现汇买入价", "现钞买入价", "现汇卖出价",
    "现钞卖出价", "中行折算价", "发布时间", "查询日期",
]
# 必填价格字段（缺失/非数值/负数均视为失败）
PRICE_FIELDS = ("现汇买入价", "现钞买入价", "现汇卖出价", "现钞卖出价", "中行折算价")
# 缺省校验文件（CI 在仓库根目录运行；可被 --csv 覆盖）
DEFAULT_CSV_PATHS = ["boc_usd_cny.csv", "boc_hkd_cny.csv"]
# 容忍最新日期超出系统日期的最多天数（时区差容忍 1 天）
MAX_FUTURE_DAYS = 1

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger("verify_csv")


def _is_iso_date(s: str) -> bool:
    """判断字符串是否为合法 YYYY-MM-DD 日期。"""
    try:
        date.fromisoformat(s.strip())
        return True
    except (ValueError, TypeError):
        return False


def _parse_price(s: str) -> float | None:
    """解析价格字段：空/非法/非有限数(nan/inf) 返回 None；合法返回数值。"""
    sv = s.strip()
    if not sv:
        return None
    try:
        val = float(sv)
    except ValueError:
        return None
    # 纵深防御：float() 会接受 "nan"/"inf"，价格必须为有限正数 → 拒绝
    if not math.isfinite(val):
        return None
    return val


def validate_csv(path) -> list[str]:
    """校验单个 CSV 文件，返回失败原因列表（空列表 = 通过）。"""
    errors: list[str] = []
    p = Path(path)
    name = str(path)

    # 1) 存在性
    if not p.exists():
        return [f"{name}: 文件不存在"]
    if not p.is_file():
        return [f"{name}: 路径不是文件"]

    # 2) 可解析（UTF-8(-sig)，用 csv 标准库逐行读取）
    try:
        with open(p, encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
    except Exception as e:
        return [f"{name}: 无法解析 CSV: {type(e).__name__}: {e}"]

    if not rows:
        return [f"{name}: CSV 为空（无表头）"]

    header = [c.strip() for c in rows[0]]
    # 3) 必需列存在
    missing_cols = [c for c in CSV_COLUMNS if c not in header]
    if missing_cols:
        errors.append(f"{name}: 缺少必需列: {', '.join(missing_cols)}（实际表头: {header}）")
        # 列缺失时后续按位置取列已无意义，直接返回
        return errors

    data_rows = rows[1:]
    # 数据有效性：仅表头无数据视为失败
    if not data_rows:
        errors.append(f"{name}: CSV 无任何数据行（仅表头）")

    idx = {c: header.index(c) for c in CSV_COLUMNS}

    parsed_dates: list[date] = []
    seen_dates: dict[str, int] = {}

    for lineno, row in enumerate(data_rows, start=2):
        if len(row) != len(header):
            errors.append(f"{name}: 第 {lineno} 行列数不匹配（期望 {len(header)}，实际 {len(row)}）")
            continue

        # 4a) 查询日期格式合法
        ds = row[idx["查询日期"]].strip()
        if not _is_iso_date(ds):
            errors.append(f"{name}: 第 {lineno} 行 查询日期 格式非法: '{ds}'")
            continue
        d = date.fromisoformat(ds)
        seen_dates[ds] = seen_dates.get(ds, 0) + 1
        parsed_dates.append(d)

        # 5) 价格字段：缺失 / 非数值 / 负数 均失败
        for field in PRICE_FIELDS:
            raw = row[idx[field]]
            if raw.strip() == "":
                errors.append(f"{name}: 第 {lineno} 行 {field} 缺失（空值）")
                continue
            val = _parse_price(raw)
            if val is None:
                errors.append(f"{name}: 第 {lineno} 行 {field} 非数值: '{raw}'")
                continue
            if val < 0:
                errors.append(f"{name}: 第 {lineno} 行 {field} 为负数: '{raw}'")

    # 4b) 查询日期无重复
    dupes = [ds for ds, n in seen_dates.items() if n > 1]
    if dupes:
        errors.append(f"{name}: 查询日期重复 {len(dupes)} 个: {sorted(dupes)[:10]}{'...' if len(dupes) > 10 else ''}")

    # 4c) 单调递增：后一行日期必须 > 前一行（严格不重复、不递减）
    for i in range(1, len(parsed_dates)):
        prev = parsed_dates[i - 1]
        cur = parsed_dates[i]
        if cur <= prev:
            errors.append(
                f"{name}: 查询日期非严格单调递增（第 {i + 2} 行 {cur} <= 第 {i + 1} 行 {prev}）"
            )
            break  # 只报第一处，避免海量重复日志

    # 6) 最新日期不超过 今日+1（容忍时区差 1 天）
    if parsed_dates:
        latest = max(parsed_dates)
        latest_str = latest.strftime("%Y-%m-%d")
        today = date.today()
        limit = today + timedelta(days=MAX_FUTURE_DAYS)
        if latest > limit:
            errors.append(
                f"{name}: 最新日期 {latest_str} 超过 今日+{MAX_FUTURE_DAYS}（今日 {today}，上限 {limit}）"
            )

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="BOC 汇率 CSV 完整性校验（CI 门禁；非 0 退出码 = 校验失败）"
    )
    parser.add_argument(
        "--csv", dest="csv_path", default=None,
        help="校验单个 CSV 文件（缺省校验默认两个文件）",
    )
    args = parser.parse_args(argv)

    if args.csv_path:
        paths = [args.csv_path]
    else:
        paths = DEFAULT_CSV_PATHS

    log.info("== CSV 完整性校验开始 ==")
    all_errors: list[str] = []
    for path in paths:
        log.info("校验 %s ...", path)
        errs = validate_csv(path)
        if errs:
            for e in errs:
                log.error("  ✗ %s", e)
            all_errors.extend(errs)
        else:
            log.info("  ✓ %s 校验通过", path)

    log.info("==" + ("校验通过" if not all_errors else f"校验失败（{len(all_errors)} 项）") + "==")
    return 1 if all_errors else 0


if __name__ == "__main__":
    sys.exit(main())