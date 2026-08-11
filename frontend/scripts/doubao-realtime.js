import { api, apiUrl } from "./api.js";
import { mergeRealtimeText } from "./realtime-text.js";

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

function assistantText(data) {
  if (!data) return "";
  if (typeof data === "string") return data;
  if (typeof data !== "object") return "";
  return String(data.content || data.text || "");
}

export async function createRealtimeSession(character, handlers = {}, options = {}) {
  const voiceConversationParam = options.voiceConversationId
    ? `&voiceConversationId=${encodeURIComponent(options.voiceConversationId)}`
    : "";
  const config = await api(`/api/token?characterId=${character.id}${voiceConversationParam}`);
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
  let playbackTimer = 0;
  let assistantChatText = "";
  let assistantSpokenText = "";
  let assistantQuestionId = "";
  let assistantReplyId = "";
  let userTurnText = "";
  let userQuestionId = "";
  let interruptedQuestionId = "";
  let playbackInterrupted = false;
  let capturingAssistantAudio = false;
  let currentAssistantAudio = [];
  let lastCompletedAssistantAudio = [];
  let assistantTurnCompleted = false;
  let replayingLastTurn = false;
  let replayNode = null;
  let replayOffset = 0;
  let replayStartedAt = 0;
  const completedUserTurns = new Set();
  const completedAssistantTurns = new Set();
  const withdrawnTurns = new Set();
  const playbackNodes = new Set();

  const interruptPlayback = () => {
    clearTimeout(playbackTimer);
    playbackNodes.forEach((node) => {
      node.onended = null;
      try { node.stop(); } catch (_error) { /* The source may already have ended. */ }
      node.disconnect();
    });
    playbackNodes.clear();
    nextPlaybackTime = audioContext.currentTime;
    replayingLastTurn = false;
    replayNode = null;
    replayOffset = 0;
    handlers.onReplayChange?.(false);
    handlers.onPlaybackChange?.(false);
  };

  const pauseLastTurnPlayback = () => {
    if (!replayingLastTurn || !replayNode) return false;
    replayOffset += Math.max(0, audioContext.currentTime - replayStartedAt);
    replayingLastTurn = false;
    replayNode.onended = null;
    playbackNodes.delete(replayNode);
    try { replayNode.stop(); } catch (_error) { /* The source may already have ended. */ }
    replayNode.disconnect();
    replayNode = null;
    clearTimeout(playbackTimer);
    handlers.onReplayChange?.(false);
    handlers.onPlaybackChange?.(false);
    return false;
  };

  const resumeLastTurnPlayback = () => {
    const samples = lastCompletedAssistantAudio.reduce((total, chunk) => total + chunk.byteLength / 2, 0);
    if (!samples) return false;
    const buffer = audioContext.createBuffer(1, samples, outputRate);
    const channel = buffer.getChannelData(0);
    let offset = 0;
    lastCompletedAssistantAudio.forEach((chunk) => {
      const pcm = new Int16Array(chunk);
      for (let index = 0; index < pcm.length; index += 1) channel[offset + index] = pcm[index] / 32768;
      offset += pcm.length;
    });
    if (replayOffset >= buffer.duration) replayOffset = 0;
    const node = audioContext.createBufferSource();
    node.buffer = buffer;
    node.connect(audioContext.destination);
    replayNode = node;
    replayingLastTurn = true;
    replayStartedAt = audioContext.currentTime;
    playbackNodes.add(node);
    node.onended = () => {
      playbackNodes.delete(node);
      node.disconnect();
      if (replayNode !== node) return;
      replayNode = null;
      replayingLastTurn = false;
      replayOffset = 0;
      handlers.onReplayChange?.(false);
      handlers.onPlaybackChange?.(false);
    };
    node.start(audioContext.currentTime, replayOffset);
    clearTimeout(playbackTimer);
    handlers.onReplayChange?.(true);
    handlers.onPlaybackChange?.(true);
    return true;
  };

  const reportPlaybackState = () => {
    clearTimeout(playbackTimer);
    handlers.onPlaybackChange?.(true);
    const remainingMs = Math.max(0, (nextPlaybackTime - audioContext.currentTime) * 1000);
    playbackTimer = window.setTimeout(() => {
      if (!closed && playbackNodes.size === 0) handlers.onPlaybackChange?.(false);
    }, remainingMs + 80);
  };

  const playPcm = (arrayBuffer, replay = false) => {
    if (closed || playbackInterrupted || audioContext.state === "closed") return;
    if (!replay && capturingAssistantAudio) {
      currentAssistantAudio.push(arrayBuffer.slice(0));
      if (assistantTurnCompleted) handlers.onTurnAudioAvailable?.();
    }
    const pcm = new Int16Array(arrayBuffer);
    const buffer = audioContext.createBuffer(1, pcm.length, outputRate);
    const channel = buffer.getChannelData(0);
    for (let index = 0; index < pcm.length; index += 1) channel[index] = pcm[index] / 32768;
    const node = audioContext.createBufferSource();
    node.buffer = buffer;
    node.connect(audioContext.destination);
    playbackNodes.add(node);
    node.onended = () => {
      playbackNodes.delete(node);
      node.disconnect();
      if (!closed && playbackNodes.size === 0) {
        replayingLastTurn = false;
        handlers.onPlaybackChange?.(false);
      }
    };
    nextPlaybackTime = Math.max(nextPlaybackTime, audioContext.currentTime);
    node.start(nextPlaybackTime);
    nextPlaybackTime += buffer.duration;
    reportPlaybackState();
  };

  const stop = async () => {
    if (closed) return;
    closed = true;
    interruptPlayback();
    if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "finish" }));
    processor?.disconnect();
    source?.disconnect();
    mediaStream?.getTracks().forEach((track) => track.stop());
    if (audioContext.state !== "closed") await audioContext.close();
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
      if (message.event === 153 || message.event === 599) {
        handlers.onError?.({ message: data.error || data.message || "豆包实时语音响应失败" });
        return;
      }
      if (message.event === 154 && data.usage) {
        handlers.onUsage?.(data.usage, {
          turnId: String(data.question_id || assistantQuestionId || userQuestionId || ""),
        });
      }
      if (message.event === 450) {
        userQuestionId = String(data.question_id || userQuestionId);
        interruptedQuestionId = userQuestionId;
        playbackInterrupted = true;
        interruptPlayback();
        capturingAssistantAudio = false;
        currentAssistantAudio = [];
        lastCompletedAssistantAudio = [];
        assistantTurnCompleted = false;
        handlers.onSpeechStart?.({ turnId: userQuestionId });
      }
      if (message.event === 451) {
        (data.results || []).forEach((result) => {
          const transcript = String(result.text || "");
          if (transcript.trim() && !playbackInterrupted) {
            playbackInterrupted = true;
            interruptPlayback();
          }
          userTurnText = transcript;
          handlers.onTranscript?.({
            text: userTurnText,
            interim: result.is_interim,
            turnId: userQuestionId,
          });
        });
      }
      if (message.event === 459) {
        const content = userTurnText.trim();
        if (content && (!userQuestionId || !completedUserTurns.has(userQuestionId))) {
          if (userQuestionId) completedUserTurns.add(userQuestionId);
          handlers.onTurnComplete?.({ role: "user", content, turnId: userQuestionId });
        }
        userTurnText = "";
        playbackInterrupted = false;
        interruptedQuestionId = "";
        capturingAssistantAudio = true;
        currentAssistantAudio = [];
        assistantTurnCompleted = false;
      }
      if (message.event === 350 || message.event === 550) {
        const questionId = String(data.question_id || "");
        const replyId = String(data.reply_id || "");
        if (questionId && withdrawnTurns.has(questionId)) return;
        const startsNewReply = (questionId && questionId !== assistantQuestionId)
          || (replyId && replyId !== assistantReplyId);
        if (startsNewReply) {
          assistantQuestionId = questionId;
          assistantReplyId = replyId;
          assistantChatText = "";
          assistantSpokenText = "";
        }
        const text = assistantText(data);
        if (message.event === 550 && text) {
          assistantChatText = mergeRealtimeText(assistantChatText, text);
          handlers.onText?.(assistantChatText);
        }
        if (message.event === 350 && text) {
          const resumesAfterInterrupt = startsNewReply
            || Boolean(interruptedQuestionId && questionId && questionId !== interruptedQuestionId);
          if (playbackInterrupted && resumesAfterInterrupt) {
            playbackInterrupted = false;
            interruptedQuestionId = "";
          }
          const mergedText = mergeRealtimeText(assistantSpokenText, text);
          if (mergedText !== assistantSpokenText) {
            assistantSpokenText = mergedText;
            if (!assistantChatText) handlers.onText?.(assistantSpokenText);
          }
        }
      }
      if (message.event === 559) {
        const content = (assistantChatText || assistantSpokenText).trim();
        const questionId = String(data.question_id || assistantQuestionId || "");
        if (questionId && withdrawnTurns.has(questionId)) {
          socket.send(JSON.stringify({ type: "withdraw", turnId: questionId }));
          return;
        }
        if (content && (!questionId || !completedAssistantTurns.has(questionId))) {
          if (questionId) completedAssistantTurns.add(questionId);
          lastCompletedAssistantAudio = currentAssistantAudio;
          assistantTurnCompleted = true;
          handlers.onTurnComplete?.({
            role: "assistant",
            content,
            turnId: questionId,
            replyId: String(data.reply_id || assistantReplyId || ""),
          });
        }
      }
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
        language: config.language,
        instructions: config.instructions,
      }));
      resolve();
    };
    socket.onerror = () => reject(Error("豆包实时语音连接失败"));
  });

  const beginMicrophone = async () => {
    if (closed) throw Error("语音会话已结束");
    if (!navigator.mediaDevices?.getUserMedia) throw Error("当前浏览器不支持麦克风输入");
    await audioContext.resume();
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: { ideal: 1 },
        echoCancellation: { ideal: true },
        noiseSuppression: { ideal: true },
        autoGainControl: { ideal: true },
      },
    });
    source = audioContext.createMediaStreamSource(mediaStream);
    processor = audioContext.createScriptProcessor(1024, 1, 1);
    let pendingSamples = new Float32Array(0);
    const packetSamples = 320;
    processor.onaudioprocess = (event) => {
      if (socket.readyState !== WebSocket.OPEN || closed) return;
      const samples = event.inputBuffer.getChannelData(0);
      const converted = resample(samples, audioContext.sampleRate, 16000);
      const combined = new Float32Array(pendingSamples.length + converted.length);
      combined.set(pendingSamples);
      combined.set(converted, pendingSamples.length);
      let offset = 0;
      while (combined.length - offset >= packetSamples) {
        socket.send(pcm16FromFloat32(combined.subarray(offset, offset + packetSamples)));
        offset += packetSamples;
      }
      pendingSamples = combined.slice(offset);
    };
    source.connect(processor);
    const silentGain = audioContext.createGain();
    silentGain.gain.value = 0;
    processor.connect(silentGain);
    silentGain.connect(audioContext.destination);
  };

  const withdrawTurn = (turnId) => {
    const normalizedTurnId = String(turnId || "");
    if (!normalizedTurnId || closed || socket.readyState !== WebSocket.OPEN) return false;
    withdrawnTurns.add(normalizedTurnId);
    playbackInterrupted = true;
    assistantChatText = "";
    assistantSpokenText = "";
    capturingAssistantAudio = false;
    currentAssistantAudio = [];
    lastCompletedAssistantAudio = [];
    assistantTurnCompleted = false;
    interruptPlayback();
    socket.send(JSON.stringify({ type: "withdraw", turnId: normalizedTurnId }));
    return true;
  };

  return {
    beginMicrophone,
    stop,
    withdrawTurn,
    hasLastTurnAudio: () => lastCompletedAssistantAudio.length > 0,
    toggleLastTurnPlayback: () => {
      if (closed || !lastCompletedAssistantAudio.length) return false;
      if (replayingLastTurn) return pauseLastTurnPlayback();
      playbackInterrupted = false;
      return resumeLastTurnPlayback();
    },
    mute: (muted) => mediaStream?.getAudioTracks().forEach((track) => { track.enabled = !muted; }),
  };
}