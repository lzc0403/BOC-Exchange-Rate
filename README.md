# GitHub 部署操作指南 - 昊哥的中国银行外汇抓取系统

## ⚠️ 重要说明

由于GitHub CLI权限限制，需要您手动创建仓库，我为您生成了完整的一键操作脚本。

## 🎯 您只需做以下3步

### 步骤1: 创建GitHub仓库 (1分钟)

访问: **https://github.com/new**

填入以下信息:
- **Repository name**: `boc-scraper`
- **Description**: 中国银行外汇牌价自动化抓取系统
- **Visibility**: Public
- 点击 **"Create repository"**

### 步骤2: 运行一键部署脚本 (30秒)

**Windows PowerShell中执行以下命令:**

```powershell
cd D:\boc_scraper
git remote add origin https://github.com/lzc0403/boc-scraper.git
git branch -M main
git push -u origin main
```

### 步骤3: 配置GitHub Secrets (2分钟)

在GitHub仓库页面，按以下顺序操作:

1. 点击 **"Settings"** → **"Secrets and variables"** → **"Actions"**
2. 点击 **"New repository secret"**
3. 依次添加以下5个Secrets:

| Name | Value |
|------|-------|
| `SMTP_SERVER` | `smtp.qq.com` |
| `SMTP_PORT` | `587` |
| `SENDER_EMAIL` | `21618822@qq.com` |
| `SENDER_PASSWORD` | `pgzznzltqyfebhic` |
| `RECIPIENT_EMAIL` | `21618822@qq.com` |

---

## 🧪 验证部署

完成上述步骤后:

1. 访问: **https://github.com/lzc0403/boc-scraper/actions**
2. 点击左侧的 **"Daily BOC Scraping"**
3. 点击 **"Run workflow"** 手动测试
4. 等待5-10分钟，检查邮箱是否收到测试邮件

---

## 📋 已完成的部署内容

✅ **代码增强**: 完整邮件发送系统 + 错误处理  
✅ **自动化配置**: GitHub Actions定时任务  
✅ **环境变量**: QQ邮箱完整配置  
✅ **文档体系**: README + 部署指南 + 检查清单  
✅ **Git准备**: 所有代码已提交到本地仓库  

---

## 🎯 系统功能

- ⏰ **定时运行**: 每天北京时间10:30自动执行
- 📧 **邮件通知**: 自动发送CSV数据文件和运行摘要
- 📊 **数据完整**: USD/CNY历史汇率数据
- 🛡️ **错误处理**: 完善的异常捕获和重试机制

---

## 🔧 故障排除

**常见问题**:

**Q: 推送到GitHub失败？**
A: 检查Git用户名配置: `git config --global user.name "Your Name"`

**Q: 收不到测试邮件？**
A: 
- 确认QQ邮箱已开启SMTP服务
- 确认使用的是授权码而非登录密码
- 检查垃圾邮件箱

**Q: Actions运行失败？**
A:
- 查看Actions日志获取详细错误
- 确认Secrets配置正确
- 检查网络连接

---

## 📞 技术支持

完成步骤后如有任何问题，请提供:
- GitHub Actions运行日志截图
- 错误信息详细内容
- 运行时间和现象描述

**我随时为您提供技术支持！** 🚀

---

*本部署方案已为昊哥自动完成代码增强和配置，确保生产就绪。*
