const appBase = location.pathname.replace(/\/?(?:index\.html)?$/i, "").replace(/\/$/, "");

export const apiUrl = (path) => `${appBase}${path}`;

function responseErrorMessage(response, data) {
  return data?.error || `请求失败 (${response.status})`;
}

export async function api(url, options = {}) {
  const response = await fetch(apiUrl(url), {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (data.actionUrl) window.open(data.actionUrl, "_blank", "noopener,noreferrer");
    const error = Error(responseErrorMessage(response, data));
    error.actionUrl = data.actionUrl;
    error.logId = data.logId;
    throw error;
  }
  return data;
}

async function streamResponse(path, body, onDelta, emptyMessage) {
  const response = await fetch(apiUrl(path), {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw Error(responseErrorMessage(response, data));
  }
  if (!response.body) throw Error("浏览器不支持流式响应");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let answer = "";
  let reasoning = "";
  let result = {};
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
        onDelta(answer, reasoning);
      }
      if (data.type === "reasoning_delta") {
        reasoning += data.text;
        onDelta(answer, reasoning);
      }
      if (data.type === "done") {
        result = data;
      }
      if (data.type === "error") throw Error(data.message);
    }
  }
  if (!answer.trim()) throw Error(emptyMessage);
  return { answer, reasoning, ...result };
}

export async function streamChat(characterId, content, onDelta, messageId = null, conversationId = null, rewrite = false) {
  const path = rewrite
    ? `/api/characters/${characterId}/messages/${messageId}/rewrite`
    : messageId
      ? `/api/characters/${characterId}/messages/${messageId}/regenerate`
      : `/api/characters/${characterId}/chat`;
  const result = await streamResponse(path, { content, conversationId }, onDelta, "角色没有返回有效内容");
  return {
    answer: result.answer,
    reasoning: result.reasoning,
    messageId: result.messageId ?? messageId,
    userMessageId: result.userMessageId ?? (rewrite ? messageId : null),
  };
}

export async function streamTranslation(characterId, messageId, onDelta) {
  const path = `/api/characters/${characterId}/messages/${messageId}/translate`;
  const result = await streamResponse(path, {}, onDelta, "翻译服务未返回有效内容");
  return result.answer;
}

export async function streamVoiceTranslation(characterId, messageId, onDelta) {
  const path = `/api/characters/${characterId}/voice-messages/${messageId}/translate`;
  const result = await streamResponse(path, {}, onDelta, "翻译服务未返回有效内容");
  return result.answer;
}

export function uploadResponseError(status, responseText) {
  let data = {};
  try {
    data = JSON.parse(responseText || "{}");
  } catch (_error) {
    data = {};
  }
  if (data.error) return data.error;
  if (status === 405) return "视频接口尚未加载，请重启 SparkChat 服务后重试";
  if (status === 413) return "服务器拒绝了过大的上传，请检查代理上传限制";
  return `请求失败 (${status})`;
}

export function transcribeVideo(file, onProgress, { signal } = {}) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    let processingProgress = 35;
    let displayedProgress = 0;
    const reportProgress = (percent, message) => {
      displayedProgress = Math.max(displayedProgress, percent);
      onProgress(displayedProgress, message);
    };
    xhr.open("POST", apiUrl("/api/video-transcriptions"));
    xhr.withCredentials = true;
    xhr.timeout = 60 * 60 * 1000;
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) reportProgress(Math.round((event.loaded / event.total) * 35), "正在上传视频");
    };
    xhr.upload.onload = () => reportProgress(35, "视频已上传，正在处理");
    xhr.onerror = () => reject(Error("视频上传失败，请检查网络连接"));
    xhr.onabort = () => reject(Error("视频上传已取消"));
    xhr.ontimeout = () => reject(Error("视频处理超时，请缩短视频后重试"));
    xhr.onload = () => {
      let data;
      try {
        data = JSON.parse(xhr.responseText || "{}");
      } catch (_error) {
        data = {};
      }
      if (xhr.status < 200 || xhr.status >= 300) {
        reject(Error(uploadResponseError(xhr.status, xhr.responseText)));
        return;
      }
      reportProgress(100, "识别完成");
      resolve(data);
    };
    const formData = new FormData();
    formData.append("video", file, file.name || "compressed-video.mp4");
    const abort = () => xhr.abort();
    if (signal?.aborted) {
      reject(signal.reason || new DOMException("操作已取消", "AbortError"));
      return;
    }
    signal?.addEventListener("abort", abort, { once: true });
    reportProgress(1, "准备上传视频");
    xhr.send(formData);
    const processingTimer = window.setInterval(() => {
      processingProgress = Math.min(90, processingProgress + 3);
      const message = processingProgress >= 75 ? "模型正在还原完整文字" : "正在抽帧并理解视频";
      reportProgress(processingProgress, message);
    }, 900);
    xhr.addEventListener("loadend", () => {
      window.clearInterval(processingTimer);
      signal?.removeEventListener("abort", abort);
    }, { once: true });
  });
}