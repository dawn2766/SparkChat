import assert from "node:assert/strict";

globalThis.location = { pathname: "/" };
globalThis.window = { open() {} };

const { api } = await import("../../frontend/scripts/api.js");

globalThis.fetch = async () => new Response("Bad Gateway", {
  status: 502,
  headers: { "Content-Type": "text/html" },
});

await assert.rejects(
  api("/api/token?characterId=1"),
  { message: "请求失败 (502)" },
  "非 JSON 网关错误应保留 HTTP 状态码",
);

globalThis.fetch = async () => new Response(JSON.stringify({ error: "登录已过期" }), {
  status: 401,
  headers: { "Content-Type": "application/json" },
});

await assert.rejects(
  api("/api/token?characterId=1"),
  { message: "登录已过期" },
  "结构化服务端错误应原样展示",
);

console.log("API error handling tests passed.");