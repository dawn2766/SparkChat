import assert from "node:assert/strict";

globalThis.location = { pathname: "/", protocol: "http:", host: "localhost" };
globalThis.window = globalThis;

const startedNodes = [];
const sentMessages = [];
let microphoneConstraints;
let socket;

class FakeWebSocket {
  static OPEN = 1;

  constructor() {
    this.readyState = FakeWebSocket.OPEN;
    socket = this;
    queueMicrotask(() => this.onopen?.());
  }

  send(message) {
    sentMessages.push(message);
  }

  close() {
    this.readyState = 3;
  }

  emit(data) {
    this.onmessage?.({ data });
  }
}

class FakeAudioNode {
  constructor() {
    this.gain = { value: 1 };
  }

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

  createMediaStreamSource() {
    return new FakeAudioNode();
  }

  createScriptProcessor() {
    return new FakeAudioNode();
  }

  createGain() {
    return new FakeAudioNode();
  }

  resume() {
    return Promise.resolve();
  }

  close() {
    this.state = "closed";
    return Promise.resolve();
  }
}

globalThis.WebSocket = FakeWebSocket;
globalThis.AudioContext = FakeAudioContext;
Object.defineProperty(globalThis, "navigator", {
  configurable: true,
  value: {
    mediaDevices: {
      getUserMedia: async (constraints) => {
        microphoneConstraints = constraints;
        return { getTracks: () => [{ stop() {} }], getAudioTracks: () => [] };
      },
    },
  },
});
globalThis.fetch = async () => new Response(JSON.stringify({
  websocketUrl: "ws://realtime.test",
  speakerId: "test-speaker",
  language: "zh",
  instructions: "",
}), { headers: { "Content-Type": "application/json" } });

const { createRealtimeSession } = await import("../../frontend/scripts/doubao-realtime.js");
const subtitles = [];
const transcripts = [];
const completedTurns = [];
let reportedUsage;
const session = await createRealtimeSession({ id: 1, name: "测试角色" }, {
  onText: (text) => subtitles.push(text),
  onTranscript: (data) => transcripts.push(data.text),
  onTurnComplete: (turn) => completedTurns.push(turn),
  onUsage: (usage) => { reportedUsage = usage; },
});
const pcm = new Int16Array([1000, -1000]).buffer;

await session.beginMicrophone();
assert.deepEqual(microphoneConstraints, {
  audio: {
    channelCount: { ideal: 1 },
    echoCancellation: { ideal: true },
    noiseSuppression: { ideal: true },
    autoGainControl: { ideal: true },
  },
});

socket.emit(JSON.stringify({
  type: "event",
  event: 450,
  data: { question_id: "user-question" },
}));
socket.emit(JSON.stringify({
  type: "event",
  event: 451,
  data: { results: [{ text: "你", is_interim: true }] },
}));
socket.emit(JSON.stringify({
  type: "event",
  event: 451,
  data: { results: [{ text: "你叫", is_interim: true }] },
}));
socket.emit(JSON.stringify({
  type: "event",
  event: 451,
  data: { results: [{ text: "你叫什么名字？", is_interim: false }] },
}));
assert.deepEqual(transcripts, ["你", "你叫", "你叫什么名字？"]);
socket.emit(pcm);
assert.equal(startedNodes.length, 0, "用户说话时应拦截被打断回复的残留音频");

socket.emit(JSON.stringify({ type: "event", event: 459, data: {} }));
socket.emit(JSON.stringify({ type: "event", event: 459, data: {} }));
assert.deepEqual(completedTurns, [{
  role: "user",
  content: "你叫什么名字？",
  turnId: "user-question",
}]);
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
  data: { question_id: "user-question", reply_id: "new-reply", text: "你好。" },
}));
socket.emit(JSON.stringify({
  type: "event",
  event: 550,
  data: {
    question_id: "user-question",
    reply_id: "new-reply",
    content: "（他停顿了一下。）你好。",
  },
}));
assert.equal(subtitles.at(-1), "（他停顿了一下。）你好。", "完整模型文本中的舞台提示应进入字幕");
socket.emit(JSON.stringify({
  type: "event",
  event: 559,
  data: { question_id: "user-question", reply_id: "new-reply" },
}));
socket.emit(JSON.stringify({
  type: "event",
  event: 559,
  data: { question_id: "user-question", reply_id: "new-reply" },
}));
assert.deepEqual(completedTurns.at(-1), {
  role: "assistant",
  content: "（他停顿了一下。）你好。",
  turnId: "user-question",
  replyId: "new-reply",
});
assert.equal(completedTurns.length, 2, "重复的回合结束事件不应重复保存消息");
socket.emit(pcm);
assert.equal(startedNodes.length, 2, "字幕事件晚到时不应影响后续音频播放");

assert.equal(session.withdrawTurn("user-question"), true);
assert.equal(
  sentMessages.at(-1),
  JSON.stringify({ type: "withdraw", turnId: "user-question" }),
  "撤回应通知代理删除同一上游回合",
);
socket.emit(pcm);
assert.equal(startedNodes.length, 2, "撤回后不应继续播放该轮残留音频");
socket.emit(JSON.stringify({
  type: "event",
  event: 559,
  data: { question_id: "user-question", reply_id: "new-reply" },
}));
assert.equal(completedTurns.length, 2, "撤回后不应再次提交该轮角色消息");

await session.stop();
console.log("Realtime audio gate tests passed.");