# MEMORY.md - 长期记忆

## 项目信息
- **项目名称**: 中国银行外汇牌价自动抓取系统
- **代码仓库**: D:/boc_scraper (GitHub: lzc0403/BOC-Exchange-Rate)
- **主程序**: boc_scraper_v6.1.py (Python 3.13)
- **重要**: Git Bash 中 `python3` 指向 Windows Store stub，需用 `C:/Users/昊哥/AppData/Local/Programs/Python/Python313/python.exe` 显式调用
- **Python路径已修正**: `~/.bashrc` 中设置了 alias

## 网站信息
- **网站名称**: Monica的经验分享
- **网站目录**: site/
- **部署方式**: GitHub Pages
- **线上地址**: https://lzc0403.github.io/BOC-Exchange-Rate/
- **技术栈**: HTML/CSS/JS + Chart.js
- **功能**: 汇率展示、走势图表、CSV下载

## 自动化流程
1. GitHub Actions 每日10:30 (UTC 2:30) 运行Python抓取
2. 数据同步到 site/ 目录
3. 自动推送并部署到GitHub Pages

## 邮件订阅功能
- **后端**: Cloudflare Worker + KV (代码在 site/cloudflare-worker/)
- **前端**: 网站底部订阅表单
- **发送脚本**: send_daily_emails.py (HTML精美邮件，含最近10条汇率数据)
- **部署**: 需要手动部署Worker + 配置GitHub Secrets

## 重要配置
- SMTP邮件通知配置在GitHub Secrets中
- Cloudflare Worker API密钥: SUBSCRIBER_API_URL, SUBSCRIBER_API_KEY
- 验证码识别使用 ddddocr 库
- 数据范围：2025-01-01 至今 (2023-2024数据正在补抓中)

## 已知问题
- 2026-05-21 数据缺失（正在后台补抓中）
- GitHub Pages 国内访问可能较慢
- Cloudflare Worker需要手动部署（Dashboard粘贴代码即可）

## 修复记录
- 2026-05-23: 清理CSV乱序数据，创建网站站点
- 2026-05-25: 添加邮件订阅功能，增强自动更新链路，修复Python路径