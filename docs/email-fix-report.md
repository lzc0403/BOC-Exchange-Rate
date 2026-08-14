# 每日邮件发送失败修复报告（send_daily_emails.py）

- **日期**: 2026-08-10
- **相关文件**: `send_daily_emails.py`（已修改）、`.github/workflows/daily_boc_scrape.yml`（未修改，仅参考）
- **CI 步骤**: "Send daily emails to subscribers"（`continue-on-error: true`，失败不影响数据抓取/部署）

---

## 1. 根因结论（已实锤）

CI 日志：

```
[ERROR] 获取订阅列表失败: HTTP Error 403: Forbidden
[ERROR] 邮件发送失败 (***): [Errno -3] Temporary failure in name resolution
[INFO] 发送完成: 成功 0, 失败 1, 总计 1
```

存在 **两个独立问题**：

### 问题 A：HTTP 403 —— Cloudflare bot 防护拦截 urllib 默认 UA（主因，已实锤）

**不是 Secret 值错误**。`SUBSCRIBER_API_KEY`（值已从本文档移除，见第 3 节轮换说明）与 `SUBSCRIBER_API_URL` 均已确认正确（注：该密钥后已轮换，本文档不再保留真实值）。

本地复现证据（2026-08-10）：

| 请求方式 | 结果 |
|---|---|
| urllib + `X-API-Key: <已轮换>` + **默认 UA**（`Python-urllib/3.x`） | **HTTP 403 Forbidden** |
| urllib + `X-API-Key: <已轮换>` + **浏览器 UA**（`Mozilla/5.0 ... Chrome/126`） | **HTTP 200**，`success=true`，返回 4 个订阅者 |

- 结论：Cloudflare 对 `boc-subscription-api.lg111481.workers.dev` 启用了 bot 防护，拦截 `Python-urllib/3.x` 默认 UA → 返回 403。
- `send_daily_emails.py` 的 `get_subscriber_list()` 之前只用 `X-API-Key` 头、没有显式 `User-Agent`，`urllib` 会发送默认 UA，因此在 CI 中触发 403。
- **修复**：请求头中显式携带浏览器 UA（见第 2 节）。

### 问题 B：DNS 解析失败 `[Errno -3]` —— GitHub Secret `SMTP_SERVER` 的值有问题

- 失败发生在 `send_email()` 的 `smtplib.SMTP(smtp_server, smtp_port)`。
- CI 环境 DNS 本身正常（能访问 github.com），因此是 **`SMTP_SERVER` secret 的值无法被 DNS 解析**：
  - 域名拼写错误；
  - 值里带了协议头（如 `smtp://`）或空格；
  - 指向了不存在的 host；
  - 或其他脏数据（如末尾换行/引号）。

> 注：日志中收件人显示为 `***` 是 GitHub Actions 对 secret 值（RECIPIENT_EMAIL）自动打码，不是 bug。

---

## 2. 代码改动说明（`send_daily_emails.py`）

采用最小改动原则，**未改变任何业务逻辑**（发邮件给订阅者 + `RECIPIENT_EMAIL` 兜底的行为完全不变）。

| 位置 | 改动 | 作用 |
|---|---|---|
| `get_subscriber_list()` 请求头 | **新增浏览器 `User-Agent`**（`Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36`） | **修复 403 根因**：绕过 Cloudflare 对 urllib 默认 UA 的 bot 拦截，实测返回 200 |
| 顶部 import | 新增 `import socket`、`import urllib.error` | 支持捕获 HTTPError / gaierror 并分类提示 |
| `get_subscriber_list()` | 在通用 `except Exception` 之前新增 `except urllib.error.HTTPError` | 401 / 403 / 其他状态码分别给出明确排查指引 |
| 新增 `mask_hostname()` 辅助函数 | 脱敏显示 SMTP 主机名 | DNS 失败日志中只显示打码后的域名（如 `sm**.qq.c*m`），避免泄露完整 Secret 值，同时剥离 `smtp://`/端口/空格，便于发现脏值 |
| `send_email()` | 在通用 `except Exception` 之前新增 `except socket.gaierror` | 命中 DNS 解析失败时，输出"请检查 GitHub Secret SMTP_SERVER"的明确提示 |

### 新增错误提示示例

- **401**：提示"缺少 X-API-Key 或 key 与 Worker 端不匹配，请检查 GitHub Secret SUBSCRIBER_API_KEY 是否已配置"。
- **403**：提示"Worker 返回 403，可能是 Cloudflare bot 防护拦截 urllib 默认 UA（已加浏览器 UA 修复）或 Secret SUBSCRIBER_API_KEY 与 Worker 端不一致；请更新 Secret"。**（密钥值已从本文档移除）**
- **其他 HTTP 状态码**：提示检查 `SUBSCRIBER_API_URL` 是否指向正确的 Worker 地址。
- **DNS 解析失败（gaierror）**：`邮件发送失败 (xxx): DNS 解析失败，无法解析 SMTP 服务器 <脱敏域名>。CI 环境 DNS 本身正常，大概率是 GitHub Secret SMTP_SERVER 的值有问题……请检查/修正 Secret，并在本地用 nslookup <smtp_server> 验证域名可解析。`

---

## 3. Secret 状态与修复指令

### 3.1 `SUBSCRIBER_API_KEY` —— ✅ 已确认正确（后已轮换，本文档不再保留真实值）

- 当前值：**已从本文档移除**。该密钥已按安全要求轮换，历史值作废；如需查看/重设，请通过 GitHub Secrets 与 Worker secrets 管理，勿在文档中留存真实值。

### 3.2 `SUBSCRIBER_API_URL` —— ✅ 已确认正确，无需修改

- 当前值：`https://boc-subscription-api.lg111481.workers.dev`（实测在线）。

### 3.3 `SMTP_SERVER` —— ⚠️ 需检查/修复（对应 DNS 报错）

可能的原因与排查步骤：

1. **确认域名可解析**：在本地对 secret 中的 SMTP 域名做 DNS 验证，例如 QQ 邮箱：
   ```bash
   nslookup smtp.qq.com
   # 或
   dig +short smtp.qq.com
   ```
   应返回 A 记录 IP；若 `NXDOMAIN` / 解析失败，说明域名拼写错误或 host 不存在。
2. **常见脏值检查**：
   - 值里不要带协议头（应为 `smtp.qq.com`，而不是 `smtp://smtp.qq.com`）；
   - 不要带空格、引号、结尾换行；
   - 端口单独放在 `SMTP_PORT`（workflow 里已固定为 587，一般无需改）。
3. **重设值**：
   ```bash
   gh secret set SMTP_SERVER --repo lzc0403/BOC-Exchange-Rate
   # 输入正确的 SMTP 域名，如 smtp.qq.com
   ```
4. **顺带核对**：`SENDER_EMAIL`、`SENDER_PASSWORD`、`RECIPIENT_EMAIL` 的值是否正确（若 SMTP 登录失败会有另一类报错，与本次 DNS 报错无关）。

---

## 4. 回归验证建议

1. **本地语法检查**（已完成）：`python -m py_compile send_daily_emails.py` → 通过。
2. **本地实测 UA 修复**（已完成）：urllib + `X-API-Key` + 浏览器 UA 请求 `/subscribers` → **HTTP 200，返回 4 个订阅者**；去掉 UA 复现 403，确认根因与修复均正确。
3. **手动触发 workflow**（无需等每日 cron）：
   - GitHub 仓库 → Actions → "Daily BOC Exchange Rate Scraping" → **Run workflow**（mode 选 `daily`）。
4. **检查日志预期**：
   - `从 Worker API 获取到 N 个订阅者`（不再 403）；
   - `邮件发送成功: xxx`（不再出现 DNS 报错）；
   - 最终 `发送完成: 成功 N, 失败 0`。
5. **若仍失败**：新日志会给出更明确的分类提示（401/403/其他 HTTP 状态/DNS），按提示继续排查；该步骤 `continue-on-error: true`，即使失败也不会影响数据抓取与部署。

---

## 5. 未改动的部分

- `site/cloudflare-worker/worker.js`：**未改动**。线上 Worker key 校验正常，问题不在 Worker。
- 数据抓取相关文件（`boc_scraper_pw.py` 等）：**未改动**。
- `.github/workflows/daily_boc_scrape.yml`：**未改动**（secret 传参方式正确）。
