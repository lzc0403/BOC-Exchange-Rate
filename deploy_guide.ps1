# GitHub部署自动化脚本 - 昊哥专用
# 一键创建仓库、推送代码、配置Secrets

Write-Host "`n🚀 开始GitHub自动化部署" -ForegroundColor Cyan
Write-Host "📁 工作目录: $(Get-Location)"

# 检查gh命令
$ghPath = "C:\Program Files\GitHub CLI\gh.exe"
if (-not (Test-Path $ghPath)) {
    Write-Host "`n❌ 未找到GitHub CLI，请先安装: https://cli.github.com/" -ForegroundColor Red
    exit 1
}

Write-Host "✅ GitHub CLI已找到" -ForegroundColor Green

# 获取用户名
Write-Host "`n👤 获取GitHub用户名..." -ForegroundColor Yellow
$username = & $ghPath api user --jq '.login'
Write-Host "✅ 用户名: $username" -ForegroundColor Green

# 创建仓库
Write-Host "`n📦 创建GitHub仓库: $username/boc-scraper" -ForegroundColor Yellow
try {
    & $ghPath repo create "$username/boc-scraper" --public --source=. --remote=origin --push
    Write-Host "✅ 仓库创建成功!" -ForegroundColor Green
} catch {
    Write-Host "`n⚠️ 自动创建失败，可能原因:" -ForegroundColor Yellow
    Write-Host "   1. Token权限不足（需要repo scope）" -ForegroundColor Yellow
    Write-Host "   2. 仓库已存在" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "请手动创建后继续执行以下步骤:" -ForegroundColor Cyan
    Write-Host "   1. 访问: https://github.com/new"
    Write-Host "   2. 创建仓库: boc-scraper (Public)"
    Write-Host "   3. 完成后重新运行此脚本"
    exit 1
}

# 配置Secrets
Write-Host "`n🔑 配置GitHub Secrets..." -ForegroundColor Yellow
$secrets = @{
    "SMTP_SERVER" = "smtp.qq.com"
    "SMTP_PORT" = "587"
    "SENDER_EMAIL" = "21618822@qq.com"
    "SENDER_PASSWORD" = "pgzznzltqyfebhic"
    "RECIPIENT_EMAIL" = "21618822@qq.com"
}

foreach ($key in $secrets.Keys) {
    $value = $secrets[$key]
    Write-Host "   设置 $key ..." -NoNewline
    & $ghPath secret set $key --repo "$username/boc-scraper" --body "$value"
    Write-Host " ✅" -ForegroundColor Green
}

Write-Host "`n🎉 部署完成！" -ForegroundColor Green
Write-Host "`n📍 仓库地址: https://github.com/$username/boc-scraper"
Write-Host "📍 Actions页面: https://github.com/$username/boc-scraper/actions"

Write-Host "`n🧪 测试步骤:" -ForegroundColor Cyan
Write-Host "1. 打开Actions页面"
Write-Host "2. 点击左侧 'Daily BOC Scraping'"
Write-Host "3. 点击 'Run workflow'"
Write-Host "4. 等待运行完成（5-10分钟）"
Write-Host "5. 检查邮箱是否收到测试邮件"

Write-Host "`n📊 系统功能:" -ForegroundColor Cyan
Write-Host "   ⏰ 定时运行: 每天北京时间10:30"
Write-Host "   📧 邮件通知: 自动发送CSV文件和摘要"
Write-Host "   📊 数据完整: USD/CNY历史汇率"
Write-Host "   🛡️ 错误处理: 异常自动捕获和重试"

Write-Host "`n📞 如有问题，请提供:" -ForegroundColor Yellow
Write-Host "   - GitHub Actions运行日志截图"
Write-Host "   - 错误信息详细内容"
Write-Host "   - 运行时间和现象描述"
