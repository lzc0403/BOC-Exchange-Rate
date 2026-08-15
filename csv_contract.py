"""CSV 列契约共享模块（纯 stdlib，仅供 boc_scraper_v6.1.py 与 verify_csv.py 共用）。

将 CSV 列顺序、必填价格字段、价格正则、CsvCorruptError 异常集中到一处，
避免双份复制漂移导致前端/邮箱附件/CI 门禁静默不一致。

约束：
  - 仅依赖 re（纯 stdlib），不引入 pandas 等第三方库；
  - 不依赖 boc_scraper_v6.1.py（避免循环导入）。
"""
import re

# CSV 列顺序契约（写入/校验/读取共用；勿改，前端与邮箱附件依赖此顺序）
CSV_COLUMNS = [
    "货币名称", "现汇买入价", "现钞买入价", "现汇卖出价",
    "现钞卖出价", "中行折算价", "发布时间", "查询日期",
]

# 必填价格字段（缺失/非数值/负数均视为失败）
# boc_scraper_v6.1.py 中以 REQUIRED_FIELDS 名称引用，verify_csv.py 中以 PRICE_FIELDS 名称引用
PRICE_FIELDS = ("现汇买入价", "现钞买入价", "现汇卖出价", "现钞卖出价", "中行折算价")

# 价格字段合法格式：非负数字（可含 1 位以上小数），如 688.8 / 691.72 / 673.0
# 拒绝科学计数法（如 1e5）、nan、inf 等非常规格式
_PRICE_RE = re.compile(r"^\d+(\.\d+)?$")


class CsvCorruptError(Exception):
    """CSV 文件损坏（无法解析/列缺失/日期列不可用）时的哨兵异常。

    由 load_done 在损坏场景抛出，调用方（scrape_today 等）据此中止或告警，
    绝不允许静默当作"无任何历史数据"而触发灾难性重复补全。
    """
