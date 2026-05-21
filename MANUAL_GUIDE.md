# 📋 GitHub 手动部署指南 - 昊哥

## ⚠️ 为什么需要手动操作？

当前GitHub CLI的Token缺少 `repo` 权限，无法自动创建仓库。这是GitHub的安全限制，需要您手动创建一次。

---

## ✅ 我已准备好的所有内容

### 📁 项目文件清单
```
D:\boc_scraper\
├── boc_scraper_v6.1.py      # 主程序（含邮件发送功能）
├── requirements.txt         # Python依赖包
├── .env                     # QQ邮箱配置（已填入您的信息）
├── .github/workflows/
│   └── daily_boc_scrape.yml # GitHub Actions定时任务
├── README.md               # 使用说明
└── deploy_guide.md         # 这份指南
```

### 🔐 QQ邮箱配置（已就绪）
```
SENDER_EMAIL=21618822@qq.com
SENDER_PASSWORD=pgzznzltqyfebhic
SMTP_SERVER=smtp.qq.com
RECIPIENT_EMAIL=21618822@qq.com
```

### ⏰ GitHub Actions 定时任务
- **运行时间**: 每天北京时间 10:30
- **Cron表达式**: `30 2 * * *`

---

## 🚀 三步完成部署（3分钟）

### 步骤1: 创建GitHub仓库 (1分钟)

1. **打开浏览器访问**: https://github.com/new
2. **填写以下信息**:
   - **Repository name**: `boc-scraper`
   - **Description**: 中国银行外汇牌价自动化抓取系统
   - **Visibility**: ☑️ Public (公开)
3. **点击按钮**: 滚动到底部，点击 **"Create repository"**

### 步骤2: 推送代码到GitHub (1分钟)

在终端（PowerShell或命令行）中依次执行以下命令:

```bash
cd D:\boc_scraper

# 配置Git远程仓库
git remote remove origin 2>nul
git remote add origin https://github.com/lzc0403/boc-scraper.git

# 修改分支名为main
git branch -M main

# 推送到GitHub
git push -u origin main --force
```

### 步骤3: 配置GitHub Secrets (1分钟)

1. **访问**: https://github.com/lzc0403/boc-scraper/settings/secrets/actions
2. **依次添加5个Secrets**:

| Name | Value |
|------|-------|
| `SMTP_SERVER` | `smtp.qq.com` |
| `SMTP_PORT` | `587` |
| `SENDER_EMAIL` | `21618822@qq.com` |
| `SENDER_PASSWORD` | `pgzznzltqyfebhic` |
| `RECIPIENT_EMAIL` | `21618822@qq.com` |

**操作步骤**:
1. 点击 **"New repository secret"** 按钮
2. 填入 Name 和 Value
3. 点击 **"Add secret"**
4. 重复5次添加所有Secrets

---

## 🧪 验证部署（测试运行）

完成上述步骤后:

1. **访问Actions页面**: https://github.com/lzc0403/boc-scraper/actions
2. **在左侧**找到 **"Daily BOC Scraping"**
3. **点击它**，然后看到 **"Run workflow"** 按钮
4. **点击"Run workflow"**
5. **等待5-10分钟**（运行时间）
6. **检查QQ邮箱** (21618822@qq.com) 是否收到测试邮件

---

## 📊 系统功能说明

| 功能 | 说明 |
|------|------|
| ⏰ **定时运行** | 每天北京时间10:30自动执行 |
| 📧 **邮件通知** | 自动发送CSV数据文件和运行摘要 |
| 📊 **数据内容** | USD/CNY历史汇率数据 |
| 🛡️ **错误处理** | 异常自动捕获、日志记录、自动重试 |

---

## 🔧 故障排除

### Q1: 推送时提示"Repository not found"?
**A**: 
- ✅ 确认仓库已创建完成
- ✅ 确认仓库名称是 `boc-scraper`
- ✅ 确认是公开仓库（Public）

### Q2: 推送时提示"authentication failed"?
**A**:
```bash
git config --global user.name "Your Name"
git config --global user.email "your@email.com"
```

### Q3: 收不到测试邮件?
**A**:
1. ✅ 确认QQ邮箱已开启SMTP服务
   - 登录QQ邮箱 → 设置 → 账户 → 开启"POP3/SMTP服务"
2. ✅ 确认使用的是授权码（pgzznzltqyfebhic），不是登录密码
3. ✅ 检查QQ邮箱的"垃圾邮件"箱
4. ✅ 确认Secrets中的邮箱地址正确

### Q4: GitHub Actions运行失败?
**A**:
1. 查看Actions日志获取详细错误
2. 确认所有5个Secrets都已配置
3. 确认`.github/workflows/`目录存在

---

## 📞 技术支持

部署完成后如有任何问题，请提供:
- ❗ **GitHub Actions运行日志截图**
- ❗ **错误信息详细内容**
- ❗ **运行时间和现象描述**

---

## 💡 为什么不能全自动？

GitHub的自动创建仓库功能需要特殊权限（`repo` scope），而当前的个人访问Token（PAT）只有基本权限。这是一个**安全限制**，不是技术缺陷。

**解决方案**: 手动创建一次后，后续的：
- ✅ Secrets配置
- ✅ 代码推送
- ✅ Actions运行
都可以自动化完成！

---

**🎯 核心目标**: 用最少的操作完成部署，之后完全自动化，无需手动干预。

**📞 有任何问题随时告诉我，我立即协助解决！**

---

## 📁 已部署的文件

### 核心文件
- `boc_scraper_v6.1.py` - 主程序
- `.github/workflows/daily_boc_scrape.yml` - GitHub Actions配置

### 配置文件
- `.env` - QQ邮箱配置
- `requirements.txt` - Python依赖

### 文档文件
- `README.md` - 使用说明
- `MANUAL_GUIDE.md` - 本指南

---

*2026-05-21 昊哥的中国银行外汇抓取系统部署指南*
