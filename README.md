# 中国银行外汇牌价抓取系统

## 功能特性

- 📊 自动抓取中国银行外汇牌价数据
- 🕐 每日10:30定时运行（GitHub Actions）
- 📧 自动发送邮件通知和CSV附件
- 🔄 支持断点续抓和数据去重
- 🛡️ 完善的错误处理和重试机制

## 快速开始

### 1. 配置环境变量

复制 `.env.example` 文件为 `.env` 并填写邮件配置：

```bash
cp .env.example .env
```

编辑 `.env` 文件，填写你的邮箱信息：

```env
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SENDER_EMAIL=your_email@gmail.com
SENDER_PASSWORD=your_app_password
RECIPIENT_EMAIL=recipient@example.com
```

> **注意**: Gmail需要使用应用专用密码而不是普通密码

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 本地测试

```bash
python test_basic.py
python boc_scraper_v6.1.py
```

## GitHub Actions 部署

### 1. 创建 GitHub Secrets

在 GitHub 仓库的 Settings > Secrets and variables > Actions 中创建以下 secrets：

- `SMTP_SERVER`: SMTP服务器地址 (如 smtp.gmail.com)
- `SMTP_PORT`: SMTP端口 (默认 587)
- `SENDER_EMAIL`: 发件人邮箱
- `SENDER_PASSWORD`: 邮箱密码或应用专用密码
- `RECIPIENT_EMAIL`: 收件人邮箱

### 2. 启用 Actions

GitHub Actions 会自动检测 `.github/workflows/` 目录下的 workflow 文件，无需额外配置。

## 定时任务说明

- **时间**: 北京时间每天上午10:30
- **对应UTC时间**: 每天凌晨2:30
- **cron表达式**: `30 2 * * *`

## 数据结构

输出文件 `boc_usd_cny.csv` 包含以下字段：

| 字段 | 描述 |
|------|------|
| 货币名称 | 美元 |
| 现汇买入价 | 现汇买入汇率 |
| 现钞买入价 | 现钞买入汇率 |
| 现汇卖出价 | 现汇卖出汇率 |
| 现钞卖出价 | 现钞卖出汇率 |
| 中行折算价 | 中行折算汇率 |
| 发布时间 | 数据发布时间 |

## 日志查看

- 程序运行日志: `boc.log`
- GitHub Actions 日志: 在 GitHub 仓库的 Actions 标签页查看

## 故障排除

### 常见问题

1. **验证码识别失败**
   - 检查网络连接
   - 增加重试次数 (修改 MAX_DAY_ATTEMPTS)

2. **邮件发送失败**
   - 检查SMTP配置
   - Gmail用户需使用应用专用密码
   - 检查防火墙设置

3. **数据抓取中断**
   - 程序具有自动重试机制
   - 可通过 `boc.log` 查看详细错误信息

### 调试模式

设置环境变量开启详细日志：

```bash
export LOG_LEVEL=DEBUG
python boc_scraper_v6.1.py
```

## 性能优化

- **SESSION_REFRESH**: 调整会话刷新频率
- **MAX_DAY_ATTEMPTS**: 单日最大重试次数
- **PAGE_RETRY**: 单页最大重试次数

## 注意事项

1. 请遵守中国银行网站的使用条款
2. 避免过于频繁的请求，以免被封禁
3. 建议在稳定的网络环境下运行
4. 定期检查程序更新和依赖版本

## 技术支持

如有问题，请查看：
- `boc.log` 文件中的详细日志
- GitHub Actions 运行日志
- 项目 Issues 页面