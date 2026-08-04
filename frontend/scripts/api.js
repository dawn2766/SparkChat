const appBase = location.pathname.replace(/\/?(?:index\.html)?$/i, "").replace(/\/$/, "");

export const apiUrl = (path) => `${appBase}${path}`;

export async function api(url, options = {}) {
  const response = await fetch(apiUrl(url), {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (data.actionUrl) window.open(data.actionUrl, "_blank", "noopener,noreferrer");
    const error = Error(data.error || "请求失败");
    error.actionUrl = data.actionUrl;
    error.logId = data.logId;
    throw error;
  }
  return data;
}

export async function streamChat(characterId, content, onDelta, messageId = null, conversationId = null, rewrite = false) {
  const path = rewrite
    ? `/api/characters/${characterId}/messages/${messageId}/rewrite`
    : messageId
      ? `/api/characters/${characterId}/messages/${messageId}/regenerate`
      : `/api/characters/${characterId}/chat`;
  const response = await fetch(apiUrl(path), {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content, conversationId }),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw Error(data.error || `请求失败 (${response.status})`);
  }
  if (!response.body) throw Error("浏览器不支持流式响应");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let answer = "";
  let resultMessageId = messageId;
  let userMessageId = rewrite ? messageId : null;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() || "";
    for (const chunk of chunks) {
      if (!chunk.startsWith("data: ")) continue;
      const data = JSON.parse(chunk.slice(6));
      if (data.type === "delta") {
        answer += data.text;
        onDelta(answer);
      }
      if (data.type === "done") {
        resultMessageId = data.messageId;
        userMessageId = data.userMessageId ?? userMessageId;
      }
      if (data.type === "error") throw Error(data.message);
    }
  }
  if (!answer.trim()) throw Error("角色没有返回有效内容");
  return { answer, messageId: resultMessageId, userMessageId };
}