import { api, apiUrl } from "./api.js";

function pcm16FromFloat32(samples) {
  const pcm = new ArrayBuffer(samples.length * 2);
  const view = new DataView(pcm);
  samples.forEach((sample, index) => {
    const value = Math.max(-1, Math.min(1, sample));
    view.setInt16(index * 2, value < 0 ? value * 0x8000 : value * 0x7fff, true);
  });
  return pcm;
}

function resample(samples, fromRate, toRate) {
  if (fromRate === toRate) return samples;
  const length = Math.round(samples.length * toRate / fromRate);
  const output = new Float32Array(length);
  const ratio = fromRate / toRate;
  for (let index = 0; index < length; index += 1) {
    const source = index * ratio;
    const left = Math.floor(source);
    const right = Math.min(left + 1, samples.length - 1);
    const weight = source - left;
    output[index] = samples[left] * (1 - weight) + samples[right] * weight;
  }
  return output;
}

export async function createRealtimeSession(character, handlers = {}, options = {}) {
  const config = await api(`/api/token?characterId=${character.id}`);
  const url = config.websocketUrl.startsWith("ws")
    ? config.websocketUrl
    : `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${config.websocketUrl}`;
  const socket = new WebSocket(url);
  socket.binaryType = "arraybuffer";
  const audioContext = new AudioContext();
  const outputRate = 24000;
  let nextPlaybackTime = 0;
  let mediaStream;
  let source;
  let processor;
  let closed = false;

  const playPcm = (arrayBuffer) => {
    const pcm = new Int16Array(arrayBuffer);
    const buffer = audioContext.createBuffer(1, pcm.length, outputRate);
    const channel = buffer.getChannelData(0);
    for (let index = 0; index < pcm.length; index += 1) channel[index] = pcm[index] / 32768;
    const node = audioContext.createBufferSource();
    node.buffer = buffer;
    node.connect(audioContext.destination);
    nextPlaybackTime = Math.max(nextPlaybackTime, audioContext.currentTime);
    node.start(nextPlaybackTime);
    nextPlaybackTime += buffer.duration;
  };

  const stop = async () => {
    if (closed) return;
    closed = true;
    if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "finish" }));
    processor?.disconnect();
    source?.disconnect();
    mediaStream?.getTracks().forEach((track) => track.stop());
    await audioContext.close();
    socket.close();
  };

  socket.onmessage = (event) => {
    if (typeof event.data !== "string") {
      if (options.playAudio !== false) playPcm(event.data);
      return;
    }
    const message = JSON.parse(event.data);
    if (message.type === "ready") handlers.onReady?.();
    if (message.type === "error") handlers.onError?.(message);
    if (message.type === "event") {
      const data = message.data || {};
      if (message.event === 451) {
        (data.results || []).forEach((result) => handlers.onTranscript?.({ text: result.text, interim: result.is_interim }));
      }
      if (message.event === 550) handlers.onText?.(data.content || "");
      if (message.event === 150) handlers.onReady?.();
    }
  };
  socket.onerror = () => handlers.onError?.({ message: "豆包实时语音连接失败" });
  socket.onclose = () => handlers.onClose?.();
  await new Promise((resolve, reject) => {
    socket.onopen = () => {
      socket.send(JSON.stringify({
        speakerId: config.speakerId,
        name: character.name,
        persona: character.persona,
      }));
      resolve();
    };
    socket.onerror = () => reject(Error("豆包实时语音连接失败"));
  });

  const beginMicrophone = async () => {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1 } });
    source = audioContext.createMediaStreamSource(mediaStream);
    processor = audioContext.createScriptProcessor(2048, 1, 1);
    processor.onaudioprocess = (event) => {
      if (socket.readyState !== WebSocket.OPEN || closed) return;
      const samples = event.inputBuffer.getChannelData(0);
      socket.send(pcm16FromFloat32(resample(samples, audioContext.sampleRate, 16000)));
    };
    source.connect(processor);
    processor.connect(audioContext.destination);
  };

  return { beginMicrophone, stop, mute: (muted) => mediaStream?.getAudioTracks().forEach((track) => { track.enabled = !muted; }) };
}