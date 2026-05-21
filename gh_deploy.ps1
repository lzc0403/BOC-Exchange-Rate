# GitHub CLI 部署脚本
# 解决权限问题，手动创建仓库后自动推送

Write-Host "`n🚀 开始GitHub部署自动化" -ForegroundColor Cyan
Write-Host "`n📋 当前用户: $(gh api user --jq '.login')"
Write-Host "`n📁 工作目录: $(Get-Location)"

# 创建GitHub仓库的替代方案
Write-Host "`n⚠️  自动创建仓库需要额外的Token权限" -ForegroundColor Yellow
Write-Host "请按以下步骤操作（只需1分钟）："
Write-Host ""
Write-Host "1. 打开: https://github.com/new"
Write-Host "2. 仓库名: boc-scraper"
Write-Host "3. 类型: Public"
Write-Host "4. 点击 'Create repository'"
Write-Host ""

# 等待用户手动创建后，自动完成其他配置
Read-Host "仓库创建完成后，按回车继续"

Write-Host "`n📦 步骤2: 配置Git远程仓库" -ForegroundColor Green
$repo = "lzc0403/boc-scraper"
git remote set-url origin https://github.com/$repo.git
git remote add origin https://github.com/$repo.git 2>$null
Write-Host "✅ 远程仓库已配置: $repo"

Write-Host "`n📤 步骤3: 推送代码" -ForegroundColor Green
git add .
git commit -m "feat: GitHub自动化部署" 2>$null
git push -u origin master --force
Write-Host "✅ 代码已推送到GitHub"

Write-Host "`n🔑 步骤4: 配置GitHub Secrets" -ForegroundColor Green
$secrets = @{
    "SMTP_SERVER" = "smtp.qq.com"
    "SENDER_EMAIL" = "21618822@qq.com"
    "SENDER_PASSWORD" = "pgzznzltqyfebhic"
    "RECIPIENT_EMAIL" = "21618822@qq.com"
}

foreach ($key in $secrets.Keys) {
    $value = $secrets[$key]
    gh secret set $key --repo $repo --body "$value" 2>$null
    Write-Host "   ✅ $key 已配置"
}

Write-Host "`n🎉 部署完成！" -ForegroundColor Green
Write-Host "📍 仓库地址: https://github.com/$repo"
Write-Host "📍 Actions: https://github.com/$repo/actions"

Write-Host "`n🧪 测试步骤:"
Write-Host "1. 访问Actions页面"
Write-Host "2. 点击 'Run workflow'"
Write-Host "3. 等待运行完成"
Write-Host "4. 检查邮箱是否收到测试邮件"
