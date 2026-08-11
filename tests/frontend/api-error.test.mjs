import assert from "node:assert/strict";

globalThis.location = { pathname: "/" };
globalThis.window = { open() {} };

const { api, uploadResponseError } = await import("../../frontend/scripts/api.js");

globalThis.fetch = async () => new Response("Bad Gateway", {
  status: 502,
  headers: { "Content-Type": "text/html" },
});

await assert.rejects(
  api("/api/token?characterId=1"),
  { message: "请求失败 (502)" },
  "非 JSON 网关错误应保留 HTTP 状态码",
);

assert.equal(
  uploadResponseError(405, "<!doctype html><title>Method Not Allowed</title>"),
  "视频接口尚未加载，请重启 SparkChat 服务后重试",
  "HTML 405 上传错误应返回可操作提示",
);
assert.equal(
  uploadResponseError(413, JSON.stringify({ error: "压缩后的视频不能超过 512 MB" })),
  "压缩后的视频不能超过 512 MB",
  "结构化上传错误应原样展示",
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