# 中国银行外汇牌价自动抓取系统

[English](README.md)

自动化抓取中国银行 USD/CNY 汇率数据，提供网页仪表盘、邮件订阅提醒和微信小程序。

## 功能特性

- **自动化数据采集** — GitHub Actions 每日定时抓取（北京时间 09:30）
- **网页仪表盘** — 响应式图表展示历史趋势，支持自定义日期范围查询
- **邮件订阅** — Cloudflare Worker 后端，每日向订阅者发送汇率通知
- **微信小程序** — 原生移动端体验，实时汇率和图表展示
- **1200+ 历史记录** — 完整数据从 2023-01-01 至今

## 系统架构

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│  GitHub Actions │───▶│  Python 抓取器   │───▶│  CSV 数据文件   │
│  (每日 09:30)   │    │  (验证码 OCR)    │    │  (1200+ 条)     │
└─────────────────┘    └──────────────────┘    └────────┬────────┘
                                                        │
                        ┌───────────────────────────────┼───────────────────────────────┐
                        ▼                               ▼                               ▼
               ┌─────────────────┐            ┌─────────────────┐            ┌─────────────────┐
               │  GitHub Pages   │            │  邮件服务       │            │ 微信小程序      │
               │  (Chart.js)     │            │  (Cloudflare)   │            │  (原生)         │
               └─────────────────┘            └─────────────────┘            └─────────────────┘
```

## 技术栈

| 组件 | 技术 |
|------|------|
| 抓取器 | Python 3.13, ddddocr (验证码识别) |
| CI/CD | GitHub Actions, 定时任务调度 |
| 网页 | HTML5, CSS3, Chart.js, GitHub Pages |
| 后端 | Cloudflare Worker, KV 存储 |
| 邮件 | SMTP (QQ 邮箱), HTML 模板 |
| 小程序 | 微信原生, Canvas API |

## 快速开始

### 1. 克隆并配置

```bash
git clone https://github.com/lzc0403/BOC-Exchange-Rate.git
cd BOC-Exchange-Rate
pip install -r requirements.txt
```

### 2. 设置 GitHub Secrets

| Secret | 说明 |
|--------|------|
| `SMTP_SERVER` | SMTP 服务器（默认：smtp.qq.com） |
| `SMTP_PORT` | SMTP 端口（默认：587） |
| `SENDER_EMAIL` | 发件人邮箱地址 |
| `SENDER_PASSWORD` | SMTP 授权码 |
| `RECIPIENT_EMAIL` | 通知收件人邮箱 |

### 3. 部署

推送到 GitHub — Actions 将自动执行：
- 每日北京时间 09:30 运行
- 抓取中国银行最新汇率
- 更新 CSV 数据文件
- 部署网页仪表盘到 GitHub Pages
- 向订阅者发送邮件通知

## 数据格式

CSV 文件包含以下列：
- 货币名称
- 现汇买入价
- 现钞买入价
- 现汇卖出价
- 现钞卖出价
- 中行折算价
- 发布时间
- 查询日期

## 在线演示

- **网页仪表盘**: https://lzc0403.github.io/BOC-Exchange-Rate/
- **API 端点**: https://boc-subscription-api.lg111481.workers.dev

## 项目结构

```
├── boc_scraper_v6.1.py      # 主抓取脚本
├── send_daily_emails.py     # 邮件通知服务
├── boc_usd_cny.csv          # 历史数据 (1200+ 条)
├── site/                    # GitHub Pages 网页仪表盘
│   ├── index.html           # 响应式仪表盘 (Chart.js)
│   └── boc_usd_cny.csv      # 同步的网页数据
├── miniprogram/             # 微信小程序
│   ├── pages/
│   │   ├── index/           # 首页：汇率卡片 + 图表
│   │   ├── history/         # 历史数据表格
│   │   └── about/           # 订阅说明
│   └── app.json             # 小程序配置
└── .github/workflows/       # CI/CD 自动化
    └── daily_boc_scrape.yml # 每日抓取工作流
```

## 贡献指南

1. Fork 本仓库
2. 创建功能分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 创建 Pull Request

## 许可证

本项目基于 [MIT 许可证](LICENSE) 开源。

## 致谢

- 中国银行提供公开的汇率数据
- GitHub Actions 提供可靠的 CI/CD 基础设施
- Cloudflare Workers 提供无服务器后端
- Chart.js 提供美观的数据可视化
