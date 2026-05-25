# 邮件订阅配置指南

## 部署 Cloudflare Worker（5分钟）

### 方法一：通过 Cloudflare Dashboard 部署（推荐，无需安装CLI）

1. **登录 Cloudflare Dashboard**
   - 打开 https://dash.cloudflare.com/
   - 如果没有账号，用邮箱免费注册一个

2. **创建 KV Namespace**
   - 进入 Workers & Pages → KV
   - 点击 "Create namespace"
   - 命名：`BOC_SUBSCRIBERS`
   - 记下生成的 Namespace ID

3. **创建 Worker**
   - Workers & Pages → 创建 Worker
   - 名称：`boc-subscription-api`
   - 将 `cloudflare-worker/worker.js` 的全部代码复制粘贴

4. **绑定 KV**
   - Worker 详情页 → Settings → Variables → KV Namespace Bindings
   - 点击 "Add binding"
   - Variable name: `BOC_SUBSCRIBERS`
   - KV namespace: 选择刚创建的 `BOC_SUBSCRIBERS`

5. **设置环境变量**
   - 同样在 Variables → Environment Variables 添加：
   - `SUBSCRIBER_API_KEY` = 设置一个随机字符串（如 `sk-boc-xxxx`）

6. **部署并获取 URL**
   - 点击 Deploy
   - 复制 Worker 的 URL（格式：`https://boc-subscription-api.xxxx.workers.dev`）

### 方法二：通过 Wrangler CLI 部署

```bash
# 安装 wrangler
npm install -g wrangler

# 登录 Cloudflare
wrangler login

# 创建 KV namespace
wrangler kv:namespace create BOC_SUBSCRIBERS

# 更新 wrangler.toml 中的 KV namespace ID
# 编辑 cloudflare-worker/wrangler.toml，替换 id 字段

# 部署
cd cloudflare-worker
wrangler deploy
```

## 配置网站

1. 编辑 `site/index.html`，找到 SUBSCRIBER_API 配置：
```javascript
const SUBSCRIBER_API = {
    URL: 'https://your-worker.your-subdomain.workers.dev',  // ← 替换为你的Worker地址
    TIMEOUT: 10000,
};
```

2. 将 URL 替换为你的 Worker 地址

3. 提交并推送代码：
```bash
git add site/index.html
git commit -m "配置邮件订阅Worker地址"
git push
```

## 配置 GitHub Actions 自动发送订阅邮件

1. 在 GitHub 仓库 Settings → Secrets and variables → Actions 中添加：

| Secret | 说明 |
|--------|------|
| `SUBSCRIBER_API_URL` | Cloudflare Worker 的完整URL |
| `SUBSCRIBER_API_KEY` | 你在 Worker 中设置的 API_KEY |

2. 推送代码后，每日10:30的工作流会自动：
   1. 抓取最新汇率数据
   2. 调用 Worker API 获取订阅者列表
   3. 向所有订阅者发送每日汇率邮件

## 验证

1. 访问网站，在订阅区输入邮箱
2. 检查 Cloudflare Worker 日志是否收到请求
3. 检查 GitHub Actions 下次运行时是否发送了邮件