# 美元兑人民币汇率数据获取工具

自动获取每日美元兑人民币汇率数据，支持历史数据获取和每日自动运行。

## 功能特点

- ✅ 获取每日美元兑人民币汇率
- ✅ 支持历史数据批量获取（最近一年）
- ✅ 每日自动运行（GitHub Actions）
- ✅ 数据自动保存为CSV格式
- ✅ 完全免费部署方案

## 数据来源

| 数据源 | 类型 | 说明 |
|--------|------|------|
| Frankfurter.app | 历史数据 | 基于欧洲央行(ECB)每日参考汇率，免费无需API Key |
| ExchangeRate-API | 实时数据 | 当前汇率，免费 |

**注意：**
- 数据基于欧洲央行参考汇率，与银行现汇买入价有0.1%-0.3%的点差
- 与在岸人民币(CNY)有微小差异

## 文件结构

```
.
├── main.py                 # 主程序脚本
├── requirements.txt        # Python依赖包
├── data.csv               # 每日数据存储文件
├── README.md              # 项目说明文档
└── .github/
    └── workflows/
        └── daily_run.yml  # GitHub Actions工作流配置
```

## 使用方法

### 1. 本地运行

#### 安装依赖
```bash
pip install -r requirements.txt
```

#### 获取今日汇率
```bash
python main.py daily
```

#### 显示当前实时汇率
```bash
python main.py current
```

#### 获取历史数据（最近一年）
```bash
python main.py historical
```

#### 指定日期范围获取
```bash
python main.py historical 2025-05-15 2026-05-15
```

#### 测试模式（最近一周）
```bash
python main.py test
```

### 2. GitHub Actions 自动部署

#### 步骤一：创建GitHub仓库
1. 在GitHub上创建一个新仓库（如 `daily-fx-rate`）
2. 将本项目所有文件上传到仓库

#### 步骤二：启用GitHub Actions
1. 进入仓库的 `Actions` 选项卡
2. 点击 `I understand my workflows, go ahead and enable them`
3. 工作流将自动在每天北京时间10:05运行

#### 步骤三：手动触发测试
1. 在 `Actions` 选项卡选择 `Get Daily Exchange Rate`
2. 点击 `Run workflow` 手动测试一次

## 数据说明

### CSV字段说明
| 字段名 | 说明 | 示例 |
|--------|------|------|
| date | 日期 | 2026-05-15 |
| rate | 美元兑人民币汇率 | 6.7852 |

### 示例数据
```
date,rate
2026-05-08,6.8012
2026-05-11,6.7965
2026-05-12,6.7921
2026-05-13,6.7910
2026-05-14,6.7852
```

## 注意事项

1. **数据说明**: 本工具获取的是市场参考汇率，非银行实际交易价格
2. **节假日处理**: 周末和法定节假日无数据（自动跳过）
3. **GitHub Actions限制**: 
   - 公开仓库完全免费
   - 私有仓库每月有2000分钟免费额度

## 故障排除

### 常见问题

**Q: 为什么某些日期没有数据？**
A: 周末和法定节假日无汇率数据，API会自动跳过这些日期。

**Q: 汇率数据与银行牌价不同？**
A: 这是正常的。本工具使用欧洲央行参考汇率，银行牌价会有点差（银行利润）。

**Q: GitHub Actions运行失败怎么办？**
A: 检查网络连接，或在仓库设置中配置代理。

## 扩展功能

如需添加以下功能，可联系开发者：
1. 多币种支持（欧元、英镑等）
2. 数据可视化图表
3. 价格波动报警
4. 邮件/微信通知

## 许可证

MIT License