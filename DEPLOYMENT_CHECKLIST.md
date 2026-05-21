# 部署检查清单 - QQ邮箱版

## ✅ 已完成配置

### 📁 项目文件
- [x] `boc_scraper_v6.1.py` - 增强版爬虫（含邮件通知）
- [x] `.env` - QQ邮箱配置完成 ✓
- [x] `requirements.txt` - 依赖列表
- [x] `.github/workflows/daily_boc_scrape.yml` - GitHub Actions配置
- [x] `README.md` - 使用文档
- [x] `DEPLOYMENT_GUIDE.md` - 部署指南
- [x] `test_basic.py` - 测试脚本

### 🔐 安全配置
- [x] QQ邮箱SMTP已开启
- [x] 应用专用密码已提供: `pgzznzltqyfebhic`
- [x] `.env`文件已创建并配置

## 🚀 下一步操作

### 本地环境设置
```bash
# 安装Python依赖
pip install -r requirements.txt

# 运行基础测试
python test_basic.py
```

### Git仓库推送
```bash
git init
git add .
git commit -m "feat: 完成QQ邮箱自动化部署配置"
git remote add origin https://github.com/yourusername/boc-scraper.git
git push -u origin main
```

### GitHub Secrets配置
在 **Settings > Secrets and variables > Actions** 中添加:

| Secret Name | Value |
|-------------|-------|
| `SMTP_SERVER` | `smtp.qq.com` |
| `SENDER_PORT` | `587` |
| `SENDER_EMAIL` | `21618822@qq.com` |
| `SENDER_PASSWORD` | `pgzznzltqyfebhic` |
| `RECIPIENT_EMAIL` | **你的接收邮箱** |

## 📋 验证流程

### 步骤1: 本地测试 (5分钟)
- [ ] `python test_basic.py` - 无错误输出
- [ ] `python boc_scraper_v6.1.py` - 正常运行，检查日志

### 步骤2: GitHub推送 (2分钟)  
- [ ] Git提交成功
- [ ] 代码推送到远程仓库

### 步骤3: GitHub配置 (3分钟)
- [ ] Secrets添加完成
- [ ] Actions权限正常

### 步骤4: 自动化测试 (10-15分钟)
- [ ] Actions自动触发运行
- [ ] 查看运行日志
- [ ] 收到测试邮件（带CSV附件）

## 🎯 预期结果

### 成功标准
- ✅ 每天北京时间10:30自动运行
- ✅ 发送邮件到指定收件人
- ✅ CSV数据文件作为附件
- ✅ 邮件包含最新数据摘要
- ✅ 运行日志完整记录

### 监控指标
- **运行频率**: 每天1次
- **运行时间**: 通常5-30分钟
- **邮件大小**: < 25MB (QQ邮箱限制)
- **成功率**: > 95%

## 🚨 故障处理

### 常见错误及解决方案

#### 1. Actions运行失败
```
错误: Could not authenticate
解决方案: 检查Secrets配置是否正确，确认授权码有效
```

#### 2. 邮件发送失败  
```
错误: SMTPAuthenticationError
解决方案: 
- 确认QQ邮箱开启了SMTP服务
- 确认使用了应用专用密码而非登录密码
- 检查网络连接
```

#### 3. 数据抓取异常
```
错误: Connection timeout
解决方案:
- 查看boc.log获取详细错误
- 增加MAX_DAY_ATTEMPTS重试次数
- 检查网络稳定性
```

## 📞 技术支持

如果遇到问题，请提供：
1. 错误发生的时间点
2. Actions运行日志截图  
3. boc.log文件的最后部分
4. 你看到的具体错误信息

---

**部署状态**: 准备就绪 ✅  
**预计完成时间**: 20-30分钟  
**维护周期**: 每日自动运行  
**最后更新**: 2026年5月21日