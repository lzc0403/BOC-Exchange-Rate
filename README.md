# BOC Exchange Rate

[中文版](README_CN.md)

Automated Bank of China USD/CNY exchange rate scraper with web dashboard, email notifications, and WeChat Mini Program.

## Features

- **Automated Data Collection** — Daily scraping via GitHub Actions (Beijing time 09:30)
- **Web Dashboard** — Responsive chart with historical trends, custom date range filtering
- **Email Subscriptions** — Cloudflare Worker backend, daily rate notifications to subscribers
- **WeChat Mini Program** — Native mobile experience with real-time rates and charts
- **1200+ Historical Records** — Complete data from 2023-01-01 to present

## Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│  GitHub Actions │───▶│  Python Scraper  │───▶│  CSV Data File  │
│  (Daily 09:30)  │    │  (CAPTCHA OCR)   │    │  (1200+ rows)   │
└─────────────────┘    └──────────────────┘    └────────┬────────┘
                                                        │
                        ┌───────────────────────────────┼───────────────────────────────┐
                        ▼                               ▼                               ▼
               ┌─────────────────┐            ┌─────────────────┐            ┌─────────────────┐
               │  GitHub Pages   │            │  Email Service  │            │ WeChat Mini App │
               │  (Chart.js)     │            │  (Cloudflare)   │            │  (Native)       │
               └─────────────────┘            └─────────────────┘            └─────────────────┘
```

## Tech Stack

| Component | Technology |
|-----------|------------|
| Scraper | Python 3.13, ddddocr (CAPTCHA solving) |
| CI/CD | GitHub Actions, cron scheduling |
| Web | HTML5, CSS3, Chart.js, GitHub Pages |
| Backend | Cloudflare Worker, KV storage |
| Email | SMTP (QQ Mail), HTML templates |
| Mini Program | WeChat native, Canvas API |

## Quick Start

### 1. Clone & Configure

```bash
git clone https://github.com/lzc0403/BOC-Exchange-Rate.git
cd BOC-Exchange-Rate
pip install -r requirements.txt
```

### 2. Set GitHub Secrets

| Secret | Description |
|--------|-------------|
| `SMTP_SERVER` | SMTP server (default: smtp.qq.com) |
| `SMTP_PORT` | SMTP port (default: 587) |
| `SENDER_EMAIL` | Sender email address |
| `SENDER_PASSWORD` | SMTP authorization code |
| `RECIPIENT_EMAIL` | Notification recipient |

### Security — Secret Leakage Auto-Block (must read)

To prevent credentials from leaking to the public repo, this project has **two layers** of automatic interception:

1. **CI scan (`gitleaks`)** — runs on every push/PR to `master`/`main`. If any secret is detected in the **entire history or current changes**, the push is **blocked** (non-zero exit). This is authoritative — it cannot be bypassed by local commits.

2. **Local pre-commit hook** — runs the instant you `git commit`. Catches secrets in the **staged files** before they ever reach history, giving you fast feedback.

**One-time setup after cloning on a new machine** (the hook path is a local git config, not part of the repo):

```bash
git config core.hooksPath .githooks
```

**Important rules:**
- Never `git add -f .env` — force-adding bypasses `.gitignore`.
- `.env` (real secrets) must stay ignored; only `.env.example` (placeholders) is committed.
- If the hook blocks a commit with a **false positive** (e.g. a placeholder like `your_password`), it's a whitelist issue — fix the pattern in `.githooks/pre-commit`, don't bypass with `--no-verify`.

> **Repo is public.** Any secret committed at any point is exposed to the world instantly. The two layers above are what prevent that from happening again.

### 3. Deploy

Push to GitHub — Actions will automatically:
- Run daily at 09:30 Beijing time
- Scrape latest rates from Bank of China
- Update CSV data file
- Deploy web dashboard to GitHub Pages
- Send email notifications to subscribers

## Data Format

CSV file with columns:
- 货币名称 (Currency)
- 现汇买入价 (Telegraphic Transfer Buy)
- 现钞买入价 (Cash Buy)
- 现汇卖出价 (Telegraphic Transfer Sell)
- 现钞卖出价 (Cash Sell)
- 中行折算价 (BOC Mid-Rate)
- 发布时间 (Publish Time)
- 查询日期 (Query Date)

## Live Demo

- **Web Dashboard**: https://lzc0403.github.io/BOC-Exchange-Rate/
- **API Endpoint**: https://boc-subscription-api.lg111481.workers.dev

## Project Structure

```
├── boc_scraper_v6.1.py      # Main scraper script
├── send_daily_emails.py     # Email notification service
├── boc_usd_cny.csv          # Historical data (1200+ records)
├── site/                    # GitHub Pages web dashboard
│   ├── index.html           # Responsive dashboard with Chart.js
│   └── boc_usd_cny.csv      # Synced data for web
├── miniprogram/             # WeChat Mini Program
│   ├── pages/
│   │   ├── index/           # Home with rate cards + chart
│   │   ├── history/         # Historical data table
│   │   └── about/           # Subscription info
│   └── app.json             # Mini program config
└── .github/workflows/       # CI/CD automation
    └── daily_boc_scrape.yml # Daily scraping workflow
```

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is open source and available under the [MIT License](LICENSE).

## Acknowledgments

- Bank of China for providing public exchange rate data
- GitHub Actions for reliable CI/CD infrastructure
- Cloudflare Workers for serverless backend
- Chart.js for beautiful data visualization
