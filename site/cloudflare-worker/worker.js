// Cloudflare Worker: BOC Exchange Rate Email Subscription API
// Service Worker format - 通过 Cloudflare Dashboard / API 部署
// KV Namespace: BOC_SUBSCRIBERS

const KV_KEY = "subscribers";

// CORS headers
const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, X-API-Key",
};

function jsonResponse(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "Content-Type": "application/json",
      ...corsHeaders,
    },
  });
}

function validateEmail(email) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

async function handleRequest(request) {
  // Handle CORS preflight
  if (request.method === "OPTIONS") {
    return new Response(null, { headers: corsHeaders });
  }

  const url = new URL(request.url);
  const path = url.pathname;

  try {
    // POST /subscribe - Add email
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
        try { subscribers = JSON.parse(stored); } catch (e) { subscribers = []; }
      }

      if (subscribers.some((s) => s.email === email)) {
        return jsonResponse({ success: true, message: "该邮箱已订阅" });
      }

      subscribers.push({ email, subscribed_at: new Date().toISOString(), active: true });
      await BOC_SUBSCRIBERS.put(KV_KEY, JSON.stringify(subscribers));

      return jsonResponse({ success: true, message: "订阅成功！每日汇率数据将推送到您的邮箱" });
    }

    // GET /subscribers - Get list (protected)
    if (request.method === "GET" && path === "/subscribers") {
      const apiKey = request.headers.get("X-API-Key");
      const envKey = (typeof SUBSCRIBER_API_KEY !== 'undefined') ? SUBSCRIBER_API_KEY : "";
      if (apiKey !== envKey) {
        return jsonResponse({ error: "Unauthorized" }, 401);
      }

      const stored = await BOC_SUBSCRIBERS.get(KV_KEY, "text");
      let subscribers = [];
      if (stored) {
        try { subscribers = JSON.parse(stored); } catch (e) { subscribers = []; }
      }

      return jsonResponse({
        success: true,
        subscribers: subscribers.filter((s) => s.active === true).map((s) => s.email),
        total: subscribers.length,
        active: subscribers.filter((s) => s.active === true).length,
      });
    }

    // GET /unsubscribe?email=xxx
    if (request.method === "GET" && path === "/unsubscribe") {
      const email = (url.searchParams.get("email") || "").trim().toLowerCase();
      if (!email) {
        return new Response(
          `<html><body style="font-family:sans-serif;text-align:center;padding:40px">
            <h2>退订失败</h2><p>缺少邮箱参数</p></body></html>`,
          { status: 400, headers: { "Content-Type": "text/html; charset=utf-8" } }
        );
      }

      const stored = await BOC_SUBSCRIBERS.get(KV_KEY, "text");
      if (stored) {
        try {
          let subscribers = JSON.parse(stored);
          const idx = subscribers.findIndex((s) => s.email === email);
          if (idx >= 0) {
            subscribers[idx].active = false;
            subscribers[idx].unsubscribed_at = new Date().toISOString();
            await BOC_SUBSCRIBERS.put(KV_KEY, JSON.stringify(subscribers));
          }
        } catch (e) {}
      }

      return new Response(
        `<html><body style="font-family:sans-serif;text-align:center;padding:40px">
          <h2>✅ 退订成功</h2>
          <p>${email} 已成功退订每日汇率推送</p>
        </body></html>`,
        { status: 200, headers: { "Content-Type": "text/html; charset=utf-8" } }
      );
    }

    return jsonResponse({ error: "Not found" }, 404);
  } catch (error) {
    return jsonResponse({ error: error.message }, 500);
  }
}

// Service Worker entry point
addEventListener("fetch", (event) => {
  event.respondWith(handleRequest(event.request));
});