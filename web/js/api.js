const appBase = location.pathname.replace(/\/?(?:index\.html)?$/i, "").replace(/\/$/, "");

export const apiUrl = (path) => `${appBase}${path}`;

export async function api(url, options = {}) {
  const response = await fetch(apiUrl(url), {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw Error(data.error || "请求失败");
  return data;
}

export async function streamChat(characterId, content, onDelta) {
  const response = await fetch(apiUrl(`/api/characters/${characterId}/chat`), {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
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
      if (data.type === "error") throw Error(data.message);
    }
  }
  if (!answer.trim()) throw Error("角色没有返回有效内容");
  return answer;
}