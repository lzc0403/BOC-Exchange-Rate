# 部署指南 - GitHub Actions + 邮件通知

## 已完成的工作

### 1. 代码增强 ✅
- **boc_scraper_v6.1.py**: 已添加完整的邮件发送功能
  - 支持SMTP邮件发送（带CSV附件）
  - 自动读取环境变量配置
  - 完善的错误处理和日志记录
  - 数据摘要和最新记录展示

### 2. 依赖配置 ✅
- **requirements.txt**: 项目依赖列表
- **.env.example**: 环境变量模板文件

### 3. GitHub Actions 配置 ✅
- **.github/workflows/daily_boc_scrape.yml**: 定时任务配置文件
  - 每天北京时间10:30自动运行
  - 自动安装依赖和环境配置
  - 失败时仍会上传结果文件
  - 支持手动触发测试

### 4. 使用说明 ✅
- **README.md**: 详细的使用说明文档
- **test_basic.py**: 基础功能测试脚本
- **DEPLOYMENT_GUIDE.md**: 本部署指南

## 部署步骤

### 步骤1: 准备本地环境
```bash
# 复制环境变量模板
cp .env.example .env

# 编辑.env文件，填写你的邮箱信息
# 使用应用专用密码（如Gmail）

# 安装依赖
pip install -r requirements.txt

# 测试基本功能
python test_basic.py
```

### 步骤2: 推送到GitHub仓库
```bash
git init
git add .
git commit -m "feat: 添加自动化部署功能"
git remote add origin https://github.com/yourusername/boc-scraper.git
git push -u origin main
```

### 步骤3: 配置GitHub Secrets
在GitHub仓库的 **Settings > Secrets and variables > Actions** 中创建以下secrets:

| Secret Name | Description | Example |
|-------------|-------------|---------|
| `SMTP_SERVER` | SMTP服务器地址 | `smtp.gmail.com` |
| `SENDER_EMAIL` | 发件人邮箱 | `your_email@gmail.com` |
| `SENDER_PASSWORD` | 邮箱密码/应用密码 | `your_app_password` |
| `RECIPIENT_EMAIL` | 收件人邮箱 | `recipient@example.com` |

> **注意**: Gmail用户必须使用应用专用密码，而不是普通密码

### 步骤4: 验证部署
1. 等待GitHub Actions自动检测并运行workflow
2. 在 **Actions** 标签页查看运行状态
3. 检查是否收到测试邮件
4. 确认 `boc_usd_cny.csv` 文件已生成

## 定时任务详情

### 时间配置
- **目标时间**: 北京时间每天上午10:30
- **UTC对应时间**: 每天凌晨2:30
- **Cron表达式**: `30 2 * * *`

### 工作流程
1. 检出代码
2. 设置Python环境
3. 安装项目依赖
4. 配置环境变量
5. 运行爬虫程序
6. 发送邮件通知
7. （可选）上传结果文件

## 故障排除

### 常见问题及解决方案

#### 1. Actions运行失败
**症状**: Workflow显示failed
**解决方案**:
```yaml
# 检查Secrets配置是否正确
# 查看详细的错误日志
```

#### 2. 邮件发送失败
**症状**: "邮件发送失败"错误
**解决方案**:
- 确认SMTP配置正确
- Gmail用户使用应用专用密码
- 检查防火墙和网络连接

#### 3. 数据抓取失败
**症状**: 程序异常退出或数据为空
**解决方案**:
- 查看 `boc.log` 文件中的详细日志
- 增加重试次数配置
- 检查网络连接稳定性

### 调试建议

1. **手动触发测试**: 在Actions页面点击"Run workflow"手动运行
2. **查看详细日志**: 在Actions页面点击失败的job查看完整输出
3. **本地测试**: 先在本地运行确保基本功能正常
4. **分步验证**: 分别测试邮件功能和爬虫功能

## 监控和维护

### 定期检查
- [ ] 查看每日运行状态（Actions页面）
- [ ] 检查邮件接收情况
- [ ] 验证数据文件格式和内容
- [ ] 更新依赖版本（如有需要）

### 性能优化建议
- 调整 `MAX_DAY_ATTEMPTS` 和 `PAGE_RETRY` 参数以适应网络状况
- 监控系统资源使用情况
- 定期清理旧的日志文件

## 技术支持

如果遇到问题，请提供以下信息：
1. GitHub Actions运行日志截图
2. `boc.log` 文件的最后部分
3. 错误发生的具体时间
4. 你使用的环境信息（操作系统、Python版本等）

## 后续扩展

系统已预留扩展接口：
- 可添加数据库存储支持
- 可集成更多汇率货币对
- 可增加Web界面展示
- 可添加异常报警机制

---

**完成时间**: 2026年5月21日
**维护人员**: 技术团队
**最后更新**: 请根据实际情况更新此文档