# MEMORY.md - 长期记忆

## 项目信息
- **项目名称**: 中国银行外汇牌价自动抓取系统
- **代码仓库**: D:/boc_scraper (GitHub: D-boc_scraper)
- **主程序**: boc_scraper_v6.1.py
- **数据文件**: boc_usd_cny.csv

## 网站信息
- **网站名称**: Monica的经验分享
- **网站目录**: site/
- **部署方式**: GitHub Pages
- **技术栈**: HTML/CSS/JS + Chart.js
- **功能**: 汇率展示、走势图表、CSV下载

## 自动化流程
1. GitHub Actions 每日10:30 (UTC 2:30) 运行Python抓取
2. 数据同步到 site/ 目录
3. 自动推送并部署到GitHub Pages

## 重要配置
- SMTP邮件通知配置在GitHub Secrets中
- 验证码识别使用 ddddocr 库
- 数据范围：2025-01-01 至今

## 已知问题
- 2026-05-21 数据缺失（需要补抓）
- GitHub Pages 国内访问可能较慢
