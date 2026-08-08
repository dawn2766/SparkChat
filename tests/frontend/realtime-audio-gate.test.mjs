import assert from "node:assert/strict";

globalThis.location = { pathname: "/", protocol: "http:", host: "localhost" };
globalThis.window = globalThis;

const startedNodes = [];
let socket;

class FakeWebSocket {
  static OPEN = 1;

  constructor() {
    this.readyState = FakeWebSocket.OPEN;
    socket = this;
    queueMicrotask(() => this.onopen?.());
  }

  send() {}

  close() {
    this.readyState = 3;
  }

  emit(data) {
    this.onmessage?.({ data });
  }
}

class FakeAudioNode {
  connect() {}

  disconnect() {}

  start() {
    startedNodes.push(this);
  }

  stop() {}
}

class FakeAudioContext {
  constructor() {
    this.currentTime = 0;
    this.destination = {};
    this.state = "running";
  }

  createBuffer(_channels, length, sampleRate) {
    return {
      duration: length / sampleRate,
      getChannelData: () => new Float32Array(length),
    };
  }

  createBufferSource() {
    return new FakeAudioNode();
  }

  close() {
    this.state = "closed";
    return Promise.resolve();
  }
}

globalThis.WebSocket = FakeWebSocket;
globalThis.AudioContext = FakeAudioContext;
globalThis.fetch = async () => new Response(JSON.stringify({
  websocketUrl: "ws://realtime.test",
  speakerId: "test-speaker",
  language: "zh",
  instructions: "",
  speakingStyle: "",
}), { headers: { "Content-Type": "application/json" } });

const { createRealtimeSession } = await import("../../frontend/scripts/doubao-realtime.js");
const subtitles = [];
let reportedUsage;
const session = await createRealtimeSession({ id: 1, name: "测试角色" }, {
  onText: (text) => subtitles.push(text),
  onUsage: (usage) => { reportedUsage = usage; },
});
const pcm = new Int16Array([1000, -1000]).buffer;

socket.emit(JSON.stringify({
  type: "event",
  event: 451,
  data: { results: [{ text: "你好", is_interim: false }] },
}));
socket.emit(pcm);
assert.equal(startedNodes.length, 0, "用户说话时应拦截被打断回复的残留音频");

socket.emit(JSON.stringify({ type: "event", event: 459, data: {} }));
socket.emit(pcm);
assert.equal(startedNodes.length, 1, "用户话轮结束后应立即播放新回复音频");

socket.emit(JSON.stringify({
  type: "event",
  event: 154,
  data: { usage: { input_audio_tokens: 42, output_text_tokens: 17 } },
}));
assert.deepEqual(reportedUsage, { input_audio_tokens: 42, output_text_tokens: 17 });

socket.emit(JSON.stringify({
  type: "event",
  event: 350,
  data: { question_id: "new-question", reply_id: "new-reply", text: "你好。" },
}));
socket.emit(JSON.stringify({
  type: "event",
  event: 550,
  data: {
    question_id: "new-question",
    reply_id: "new-reply",
    content: "（他停顿了一下。）你好。",
  },
}));
assert.equal(subtitles.at(-1), "（他停顿了一下。）你好。", "完整模型文本中的舞台提示应进入字幕");
socket.emit(pcm);
assert.equal(startedNodes.length, 2, "字幕事件晚到时不应影响后续音频播放");

await session.stop();
console.log("Realtime audio gate tests passed.");