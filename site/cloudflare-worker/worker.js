// Cloudflare Worker: BOC Exchange Rate Email Subscription API
// Service Worker format - 通过 Cloudflare Dashboard / API 部署
// KV Namespace: BOC_SUBSCRIBERS
//
// ============================================================================
// 退订 Token（HMAC-SHA256 签名）方案 —— Python 端对接公式（重要）
// ----------------------------------------------------------------------------
// 退订链接：https://<domain>/unsubscribe?email=<email>&token=<token>
// 其中 <email> 必须 URL 编码，<token> 为下面公式生成的签名串。
//
// 【Python 端生成 token（send_daily_emails.py）】
//   1) 取密钥（与 Worker 端解析顺序完全一致）：
//        secret = os.environ.get("UNSUBSCRIBE_SECRET") or os.environ["SUBSCRIBER_API_KEY"]
//      Worker 端优先使用 UNSUBSCRIBE_SECRET，未配置时才回退 SUBSCRIBER_API_KEY；
//      Python 端必须采用同样的优先级，否则签名不匹配。
//
//   2) 构造 payload（JSON 键顺序必须固定为 email, exp, v, nonce）：
//        import json, time, secrets, hmac, hashlib, base64, urllib.parse
//        email = email.strip().lower()                  # 必须与订阅时一致（小写）
//        exp   = int(time.time()) + 7 * 24 * 3600       # 过期时间戳（Unix 秒）
//        v, nonce = 1, secrets.token_hex(8)             # 版本号 + 随机 nonce
//        payload = {"email": email, "exp": exp, "v": v, "nonce": nonce}
//
//   3) 规范签名串（严格顺序，竖线分隔，无空格）：
//        canonical = f"{email}|{exp}|{v}|{nonce}"
//
//   4) HMAC-SHA256 + base64url（无 padding）：
//        p64 = base64.urlsafe_b64encode(
//                  json.dumps(payload, separators=(",", ":")).encode()
//              ).rstrip(b"=").decode()
//        s64 = base64.urlsafe_b64encode(
//                  hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).digest()
//              ).rstrip(b"=").decode()
//
//   5) token = f"{p64}.{s64}"
//
// 退订链接：f"https://<domain>/unsubscribe?email={urllib.parse.quote(email)}&token={token}"
//
// 【Worker 端校验（verifyToken）】
//   解析 payload → 用 crypto.subtle.verify 做恒时签名校验 → 校验 payload.email 与
//   query 中的 email 一致 → 校验未过期（exp > now）→ 通过后才按 email 幂等退订。
// ============================================================================

const KV_KEY = "subscribers";

// Token 有效期：7 天（单位：秒）
const TOKEN_TTL_SECONDS = 7 * 24 * 3600;
// Token 版本号
const TOKEN_VERSION = 1;
// 最小密钥长度（fail-closed 阈值）
const MIN_SECRET_LENGTH = 16;

// CORS headers
const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, X-API-Key",
};

// 所有 HTML 响应统一附加的安全响应头
const HTML_SECURITY_HEADERS = {
  "Content-Type": "text/html; charset=utf-8",
  "X-Content-Type-Options": "nosniff",
  "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
  "Referrer-Policy": "no-referrer",
};

// ---------------------------------------------------------------------------
// 工具函数
// ---------------------------------------------------------------------------

/**
 * 读取 Service Worker 全局注入的环境变量。
 * Service Worker 格式下环境变量以全局绑定形式存在，需用 typeof 防未定义抛错。
 * @param {"SUBSCRIBER_API_KEY" | "UNSUBSCRIBE_SECRET"} name 变量名
 * @returns {string|null} 已配置则返回字符串，否则返回 null
 */
function getEnvValue(name) {
  if (name === "SUBSCRIBER_API_KEY") {
    return typeof SUBSCRIBER_API_KEY !== "undefined" && SUBSCRIBER_API_KEY
      ? String(SUBSCRIBER_API_KEY)
      : null;
  }
  if (name === "UNSUBSCRIBE_SECRET") {
    return typeof UNSUBSCRIBE_SECRET !== "undefined" && UNSUBSCRIBE_SECRET
      ? String(UNSUBSCRIBE_SECRET)
      : null;
  }
  return null;
}

/**
 * 解析两个密钥：
 *   - apiKey：保护 GET /subscribers（X-API-Key 鉴权），必须配置且长度 >= 16，否则 503。
 *   - tokenSecret：用于退订 token 的 HMAC 签名密钥，优先 UNSUBSCRIBE_SECRET，回退 SUBSCRIBER_API_KEY。
 * @returns {{apiKey: string|null, tokenSecret: string|null}}
 */
function resolveSecrets() {
  const apiKey = getEnvValue("SUBSCRIBER_API_KEY");
  const unsubSecret = getEnvValue("UNSUBSCRIBE_SECRET");

  const tokenSecret =
    unsubSecret && unsubSecret.length >= MIN_SECRET_LENGTH
      ? unsubSecret
      : apiKey && apiKey.length >= MIN_SECRET_LENGTH
        ? apiKey
        : null;

  return { apiKey, tokenSecret };
}

/**
 * 字节数组 -> base64url（无 padding）。
 * @param {Uint8Array} bytes
 * @returns {string}
 */
function bytesToBase64Url(bytes) {
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
  }
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/**
 * base64url（无 padding）-> 字节数组。
 * @param {string} b64u
 * @returns {Uint8Array}
 */
function base64UrlToBytes(b64u) {
  let b64 = b64u.replace(/-/g, "+").replace(/_/g, "/");
  while (b64.length % 4 !== 0) {
    b64 += "=";
  }
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

/**
 * 生成随机十六进制字符串（用于 token 的 nonce）。
 * @param {number} byteLength 随机字节数
 * @returns {string}
 */
function randomHex(byteLength) {
  const arr = new Uint8Array(byteLength);
  crypto.getRandomValues(arr);
  return Array.from(arr, (b) => b.toString(16).padStart(2, "0")).join("");
}

/**
 * 计算 HMAC-SHA256 摘要。
 * @param {string} secret 密钥
 * @param {string} data 待签名的规范字符串
 * @returns {Promise<Uint8Array>} 摘要字节
 */
async function hmacSha256(secret, data) {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  return new Uint8Array(
    await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(data))
  );
}

/**
 * 恒时比较两个字符串（SHA-256 摘要后逐字节比较，规避长度侧信道）。
 * @param {string} a
 * @param {string} b
 * @returns {Promise<boolean>}
 */
async function safeEqual(a, b) {
  const ha = new Uint8Array(
    await crypto.subtle.digest("SHA-256", new TextEncoder().encode(a))
  );
  const hb = new Uint8Array(
    await crypto.subtle.digest("SHA-256", new TextEncoder().encode(b))
  );
  let diff = 0;
  for (let i = 0; i < ha.length; i++) {
    diff |= ha[i] ^ hb[i];
  }
  return diff === 0;
}

/**
 * 校验邮箱格式（基础正则）。
 * @param {string} email
 * @returns {boolean}
 */
function validateEmail(email) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

/**
 * 构造 HTML 响应（统一附加安全响应头；不附加 CORS，纯导航页面无需跨域）。
 * 注意：body 必须是固定文案，任何用户可控输入必须先经 htmlEscape 或干脆不回显。
 * @param {string} body HTML 字符串
 * @param {number} status 状态码
 * @returns {Response}
 */
function htmlResponse(body, status = 200) {
  return new Response(body, {
    status,
    headers: { ...HTML_SECURITY_HEADERS },
  });
}

/**
 * 转义 HTML 特殊字符，防止反射型 XSS。
 * @param {string} value
 * @returns {string}
 */
function htmlEscape(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// ---------------------------------------------------------------------------
// 退订 Token：生成 / 校验
// ---------------------------------------------------------------------------

/**
 * 生成退订 token（主要供 Python 端按上方公式生成，本函数保留用于测试/文档）。
 * 格式：base64url(json{email,exp,v,nonce}) + "." + base64url(hmac)
 * @param {string} email 订阅邮箱（小写）
 * @param {string} secret HMAC 密钥
 * @returns {Promise<string>}
 */
async function generateToken(email, secret) {
  const exp = Math.floor(Date.now() / 1000) + TOKEN_TTL_SECONDS;
  const v = TOKEN_VERSION;
  const nonce = randomHex(8);
  // 键顺序必须与 Python 端 json.dumps 一致：email, exp, v, nonce
  const payloadStr =
    '{"email":' +
    JSON.stringify(email) +
    ',"exp":' +
    exp +
    ',"v":' +
    v +
    ',"nonce":' +
    JSON.stringify(nonce) +
    "}";
  const canonical = `${email}|${exp}|${v}|${nonce}`;
  const payloadB64 = bytesToBase64Url(new TextEncoder().encode(payloadStr));
  const sigB64 = bytesToBase64Url(await hmacSha256(secret, canonical));
  return payloadB64 + "." + sigB64;
}

/**
 * 校验退订 token。
 * 校验顺序：格式 → payload 解析 → 字段类型 → 未过期 → email 与请求参数一致 → 签名恒时校验。
 * @param {string} token 退订 token
 * @param {string} email 请求 query 中的邮箱（小写）
 * @param {string} secret HMAC 密钥
 * @returns {Promise<boolean>}
 */
async function verifyToken(token, email, secret) {
  if (!token || typeof token !== "string") {
    return false;
  }
  const parts = token.split(".");
  if (parts.length !== 2 || !parts[0] || !parts[1]) {
    return false;
  }

  // 1) 解析 payload
  let payload;
  try {
    const payloadStr = new TextDecoder().decode(base64UrlToBytes(parts[0]));
    payload = JSON.parse(payloadStr);
  } catch (e) {
    return false;
  }
  if (!payload || typeof payload !== "object") {
    return false;
  }
  const pEmail = payload.email;
  const exp = payload.exp;
  const v = payload.v;
  const nonce = payload.nonce;
  if (
    typeof pEmail !== "string" ||
    typeof exp !== "number" ||
    v !== TOKEN_VERSION ||
    typeof nonce !== "string"
  ) {
    return false;
  }

  // 2) 校验未过期
  const now = Math.floor(Date.now() / 1000);
  if (!Number.isFinite(exp) || exp <= now) {
    return false;
  }

  // 3) 校验 email 与请求参数一致（两侧均小写化）
  if (pEmail.toLowerCase() !== email.toLowerCase()) {
    return false;
  }

  // 4) 恒时校验 HMAC 签名（crypto.subtle.verify 内部按恒时实现）
  const canonical = `${pEmail}|${exp}|${v}|${nonce}`;
  try {
    const key = await crypto.subtle.importKey(
      "raw",
      new TextEncoder().encode(secret),
      { name: "HMAC", hash: "SHA-256" },
      false,
      ["verify"]
    );
    const ok = await crypto.subtle.verify(
      "HMAC",
      key,
      base64UrlToBytes(parts[1]),
      new TextEncoder().encode(canonical)
    );
    return ok === true;
  } catch (e) {
    return false;
  }
}

// ---------------------------------------------------------------------------
// 固定文案页面（不含任何用户输入回显，杜绝反射型 XSS）
// ---------------------------------------------------------------------------

// 退订成功页
const UNSUBSCRIBE_SUCCESS_HTML = `<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>退订成功</title></head>
<body style="font-family:sans-serif;text-align:center;padding:40px;background:#f5f7fa;color:#222">
  <div style="max-width:480px;margin:0 auto;background:#fff;border-radius:12px;padding:40px 24px;box-shadow:0 2px 12px rgba(0,0,0,.08)">
    <div style="font-size:48px">✅</div>
    <h2 style="margin:16px 0 8px">退订成功</h2>
    <p style="color:#666;line-height:1.6">您已成功退订每日汇率推送。</p>
    <p style="color:#999;font-size:12px;margin-top:24px">如需重新订阅，请访问本站订阅页面。</p>
  </div>
</body></html>`;

// 退订链接无效 / 缺失 / 过期 / 不匹配 固定文案页（不回显任何用户输入）
const UNSUBSCRIBE_INVALID_HTML = `<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>退订链接无效</title></head>
<body style="font-family:sans-serif;text-align:center;padding:40px;background:#f5f7fa;color:#222">
  <div style="max-width:480px;margin:0 auto;background:#fff;border-radius:12px;padding:40px 24px;box-shadow:0 2px 12px rgba(0,0,0,.08)">
    <div style="font-size:48px">⚠️</div>
    <h2 style="margin:16px 0 8px">退订链接无效</h2>
    <p style="color:#666;line-height:1.6">该退订链接无效、已过期或与您的邮箱不匹配。</p>
    <p style="color:#666;line-height:1.6">请从您收到的订阅邮件中点击退订链接。</p>
    <p style="color:#999;font-size:12px;margin-top:24px">如仍有问题，请联系管理员处理。</p>
  </div>
</body></html>`;

// 服务未配置密钥（fail-closed）固定文案页
const UNSUBSCRIBE_UNAVAILABLE_HTML = `<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>服务暂不可用</title></head>
<body style="font-family:sans-serif;text-align:center;padding:40px;background:#f5f7fa;color:#222">
  <div style="max-width:480px;margin:0 auto;background:#fff;border-radius:12px;padding:40px 24px;box-shadow:0 2px 12px rgba(0,0,0,.08)">
    <h2 style="margin:16px 0 8px">服务暂不可用</h2>
    <p style="color:#666;line-height:1.6">退订服务暂不可用，请稍后再试。</p>
    <p style="color:#999;font-size:12px;margin-top:24px">您也可以直接联系我们处理退订。</p>
  </div>
</body></html>`;

// ---------------------------------------------------------------------------
// JSON 响应
// ---------------------------------------------------------------------------

function jsonResponse(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "Content-Type": "application/json",
      ...corsHeaders,
    },
  });
}

// ---------------------------------------------------------------------------
// 主路由
// ---------------------------------------------------------------------------

async function handleRequest(request) {
  // Handle CORS preflight
  if (request.method === "OPTIONS") {
    return new Response(null, { headers: corsHeaders });
  }

  const url = new URL(request.url);
  const path = url.pathname;

  try {
    // POST /subscribe - Add email（无鉴权，公开注册接口）
    if (request.method === "POST" && path === "/subscribe") {
      const body = await request.json();
      const email = (body.email || "").trim().toLowerCase();

      if (!email) {
        return jsonResponse({ error: "请提供邮箱地址" }, 400);
      }
      if (!validateEmail(email)) {
        return jsonResponse({ error: "邮箱格式不正确" }, 400);
      }

      let subscribers = [];
      const stored = await BOC_SUBSCRIBERS.get(KV_KEY, "text");
      if (stored) {
        try {
          subscribers = JSON.parse(stored);
        } catch (e) {
          subscribers = [];
        }
      }

      if (subscribers.some((s) => s.email === email)) {
        return jsonResponse({ success: true, message: "该邮箱已订阅" });
      }

      subscribers.push({ email, subscribed_at: new Date().toISOString(), active: true });
      await BOC_SUBSCRIBERS.put(KV_KEY, JSON.stringify(subscribers));

      return jsonResponse({ success: true, message: "订阅成功！每日汇率数据将推送到您的邮箱" });
    }

    // GET /subscribers - Get list (protected, fail-closed)
    if (request.method === "GET" && path === "/subscribers") {
      const { apiKey } = resolveSecrets();

      // fail-closed：密钥未配置或长度不足时一律拒绝，绝不放行
      if (!apiKey || apiKey.length < MIN_SECRET_LENGTH) {
        console.error(
          "[/subscribers] SUBSCRIBER_API_KEY 未配置或长度不足，拒绝访问（fail-closed）"
        );
        return jsonResponse({ error: "Service unavailable" }, 503);
      }

      const reqApiKey = request.headers.get("X-API-Key");
      // 请求密钥必须非空，且与 env 值安全比较
      if (!reqApiKey || !(await safeEqual(reqApiKey, apiKey))) {
        return jsonResponse({ error: "Unauthorized" }, 401);
      }

      const stored = await BOC_SUBSCRIBERS.get(KV_KEY, "text");
      let subscribers = [];
      if (stored) {
        try {
          subscribers = JSON.parse(stored);
        } catch (e) {
          subscribers = [];
        }
      }

      return jsonResponse({
        success: true,
        subscribers: subscribers.filter((s) => s.active === true).map((s) => s.email),
        total: subscribers.length,
        active: subscribers.filter((s) => s.active === true).length,
      });
    }

    // GET /unsubscribe?email=xxx&token=yyy - 带签名退订（HMAC 校验）
    if (request.method === "GET" && path === "/unsubscribe") {
      const email = (url.searchParams.get("email") || "").trim().toLowerCase();
      const token = (url.searchParams.get("token") || "").trim();

      const { tokenSecret } = resolveSecrets();
      if (!tokenSecret) {
        console.error(
          "[/unsubscribe] UNSUBSCRIBE_SECRET / SUBSCRIBER_API_KEY 均未配置或长度不足（fail-closed）"
        );
        return htmlResponse(UNSUBSCRIBE_UNAVAILABLE_HTML, 503);
      }

      // 参数缺失 → 固定文案，不回显
      if (!email || !token) {
        return htmlResponse(UNSUBSCRIBE_INVALID_HTML, 400);
      }

      // 签名校验失败（伪造/过期/邮箱不匹配）→ 固定文案，不回显，不执行退订
      const valid = await verifyToken(token, email, tokenSecret);
      if (!valid) {
        return htmlResponse(UNSUBSCRIBE_INVALID_HTML, 403);
      }

      // 仅验证通过后执行幂等退订：已退订/不存在时不再重复写 KV
      const stored = await BOC_SUBSCRIBERS.get(KV_KEY, "text");
      if (stored) {
        try {
          const subscribers = JSON.parse(stored);
          let changed = false;
          for (const s of subscribers) {
            if (s.email === email && s.active === true) {
              s.active = false;
              s.unsubscribed_at = new Date().toISOString();
              changed = true;
            }
          }
          if (changed) {
            await BOC_SUBSCRIBERS.put(KV_KEY, JSON.stringify(subscribers));
          }
        } catch (e) {
          console.error("[/unsubscribe] 更新 KV 失败:", e);
        }
      }

      // 成功页只显示固定文案，不回显邮箱
      return htmlResponse(UNSUBSCRIBE_SUCCESS_HTML, 200);
    }

    return jsonResponse({ error: "Not found" }, 404);
  } catch (error) {
    console.error("handleRequest error:", error);
    return jsonResponse({ error: error.message }, 500);
  }
}

// Service Worker entry point
addEventListener("fetch", (event) => {
  event.respondWith(handleRequest(event.request));
});
