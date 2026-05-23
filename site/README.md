# Monica的经验分享 - 中国银行外汇牌价追踪网站

## 网站说明

这是一个自动追踪中国银行美元兑人民币汇率的静态网站，数据每日自动更新。

### 功能特点

- 实时显示最新汇率数据
- 交互式走势图表（支持30天/3月/6月/1年/全部时间范围切换）
- 一键下载完整CSV数据
- 响应式设计，支持手机/平板/电脑访问
- 每日北京时间10:30自动更新数据

### 数据来源

中国银行外汇牌价官方数据

### 技术栈

- 前端：HTML5 + CSS3 + JavaScript
- 图表：Chart.js
- 字体：Playfair Display + Noto Sans SC
- 部署：GitHub Pages

### 本地预览

```bash
cd site
python -m http.server 8080
# 访问 http://localhost:8080
```

### 自动更新流程

1. GitHub Actions 每日10:30运行Python脚本抓取数据
2. 数据自动同步到 `site/` 目录
3. 自动推送到GitHub仓库
4. GitHub Pages 自动部署更新网站
