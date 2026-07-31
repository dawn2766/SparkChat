import { createIcons, Mic, MicOff, Phone, PhoneOff, Settings2, Volume2 } from "https://cdn.jsdelivr.net/npm/lucide@0.468.0/+esm";
import { Conversation } from "https://cdn.jsdelivr.net/npm/@elevenlabs/client/+esm";
import { api, apiUrl, streamChat } from "../api.js";
import { app, avatar, esc, notify, scrollMessages } from "../dom.js";
import { state } from "../state.js";

const refreshIcons = () => createIcons({ icons: { Mic, MicOff, Phone, PhoneOff, Settings2, Volume2 } });

function messageMarkup(message, character) {
  const stamp = message.role === "user" ? "" : `<span class="stamp">${esc(character.name.toUpperCase())} <button class="speak-button" data-speak="${esc(message.content)}" aria-label="朗读这条回复"><i data-lucide="volume-2"></i></button></span>`;
  return `<div class="message ${message.role === "user" ? "user" : ""}"><div class="message-content"><div class="bubble">${esc(message.content)}</div>${stamp}</div></div>`;
}

function bindSpeechButtons() {
  document.querySelectorAll("[data-speak]").forEach((button) => {
    button.onclick = () => speak(button.dataset.speak, button);
  });
  refreshIcons();
}

async function speak(text, button = null) {
  if (!state.active || !text) return;
  document.querySelectorAll(".speak-button.playing").forEach((item) => item.classList.remove("playing"));
  button?.classList.add("playing");
  try {
    const response = await fetch(apiUrl(`/api/characters/${state.active.id}/speak`), { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw Error(data.error || "语音生成失败");
    }
    const audio = new Audio(URL.createObjectURL(await response.blob()));
    audio.onended = () => button?.classList.remove("playing");
    audio.onerror = () => { button?.classList.remove("playing"); notify("音频播放失败"); };
    await audio.play();
  } catch (error) {
    button?.classList.remove("playing");
    notify(error.message);
  }
}

function toggleDictation() {
  const button = document.querySelector("#dictate");
  if (!("webkitSpeechRecognition" in window || "SpeechRecognition" in window)) {
    notify("当前浏览器不支持语音转文字");
    return;
  }
  if (state.listening) {
    state.recognition?.stop();
    return;
  }
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  state.recognition = new Recognition();
  state.recognition.lang = "zh-CN";
  state.recognition.continuous = false;
  state.recognition.onstart = () => { state.listening = true; button.classList.add("recording"); };
  state.recognition.onresult = (event) => { document.querySelector("#composer textarea").value += event.results[0][0].transcript; };
  state.recognition.onerror = (event) => {
    if (event.error !== "aborted") notify(event.error === "not-allowed" ? "请在浏览器设置中允许麦克风权限" : "未能识别语音");
  };
  state.recognition.onend = () => { state.listening = false; button.classList.remove("recording"); };
  state.recognition.start();
}

async function sendMessage(event) {
  event.preventDefault();
  if (state.sending) return;
  const form = event.currentTarget;
  const textarea = form.content;
  const sendButton = form.querySelector(".send");
  const content = textarea.value.trim();
  if (!content) return;
  state.sending = true;
  textarea.value = "";
  textarea.disabled = true;
  sendButton.disabled = true;
  sendButton.textContent = "·";
  state.messages.push({ role: "user", content });
  const container = document.querySelector("#messages");
  const assistant = document.createElement("div");
  assistant.className = "message pending";
  assistant.innerHTML = `<div><div class="bubble">正在回应…</div><span class="stamp">${esc(state.active.name.toUpperCase())}</span></div>`;
  container.insertAdjacentHTML("beforeend", messageMarkup({ role: "user", content }, state.active));
  container.append(assistant);
  const bubble = assistant.querySelector(".bubble");
  scrollMessages();
  try {
    const answer = await streamChat(state.active.id, content, (partial) => { bubble.textContent = partial; assistant.classList.remove("pending"); scrollMessages(); });
    state.messages.push({ role: "assistant", content: answer });
    assistant.classList.remove("pending");
    assistant.querySelector(".stamp").innerHTML = `${esc(state.active.name.toUpperCase())} <button class="speak-button" data-speak="${esc(answer)}" aria-label="朗读这条回复"><i data-lucide="volume-2"></i></button>`;
    bindSpeechButtons();
  } catch (error) {
    assistant.classList.remove("pending");
    assistant.classList.add("failed");
    bubble.textContent = `未能送达回复：${error.message}`;
    textarea.value = content;
    notify("发送失败，消息已保留，可再次发送");
  } finally {
    state.sending = false;
    textarea.disabled = false;
    sendButton.disabled = false;
    sendButton.textContent = "↑";
    textarea.focus();
  }
}

function handleComposerKeydown(event) {
  if (event.key !== "Enter" || event.shiftKey || event.isComposing || event.keyCode === 229) return;
  event.preventDefault();
  event.currentTarget.form.requestSubmit();
}

function voiceOptions(selectedId) {
  return state.voices.map((voice) => `<option value="${esc(voice.id)}" data-name="${esc(voice.name)}" ${voice.id === selectedId ? "selected" : ""}>${esc(voice.name)} · ${esc(voice.description)}</option>`).join("");
}

function settingsMarkup(character) {
  return `<dialog class="app-dialog character-dialog" id="character-dialog">
    <form class="dialog-panel" id="character-form">
      <header class="dialog-header"><div><h2>角色配置</h2></div></header>
      <div class="dialog-body">
        <div class="field"><label for="edit-name">角色名称</label><input class="text-input" id="edit-name" name="name" maxlength="40" required value="${esc(character.name)}"></div>
        <div class="field"><label for="edit-persona">身份背景</label><textarea class="text-area character-prompt" id="edit-persona" name="persona" maxlength="2400" required>${esc(character.persona)}</textarea></div>
        <div class="field"><label for="edit-voice">角色音色</label><select class="select-input" id="edit-voice" name="voiceId">${voiceOptions(character.voiceId)}</select><input type="hidden" name="voiceName" value="${esc(character.voiceName)}"></div>
      </div>
      <footer class="dialog-actions"><button type="button" class="secondary-button" data-dialog-close>取消</button><button class="primary-button" type="submit">保存配置</button></footer>
    </form>
  </dialog>`;
}

function bindSettings(onBack) {
  const dialog = document.querySelector("#character-dialog");
  const form = document.querySelector("#character-form");
  document.querySelector("#settings").onclick = () => dialog.showModal();
  dialog.querySelectorAll("[data-dialog-close]").forEach((button) => { button.onclick = () => dialog.close(); });
  dialog.onclick = (event) => { if (event.target === dialog) dialog.close(); };
  form.voiceId.onchange = () => { form.voiceName.value = form.voiceId.selectedOptions[0].dataset.name; };
  form.onsubmit = async (event) => {
    event.preventDefault();
    const button = event.submitter;
    button.disabled = true;
    button.textContent = "正在保存";
    try {
      const result = await api(`/api/characters/${state.active.id}`, { method: "PATCH", body: JSON.stringify(Object.fromEntries(new FormData(form))) });
      state.active = result.character;
      const index = state.characters.findIndex((item) => item.id === result.character.id);
      if (index >= 0) state.characters[index] = { ...state.characters[index], ...result.character };
      dialog.close();
      notify("角色配置已更新");
      renderChat({ onBack });
    } catch (error) {
      notify(error.message);
      button.disabled = false;
      button.textContent = "保存配置";
    }
  };
}

async function startPhone() {
  const phone = document.createElement("div");
  phone.className = "phone-overlay connecting";
  phone.innerHTML = `<main class="phone-stage"><div class="voice-orbit"><div class="voice-bars" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></div>${avatar(state.active)}</div><h1>${esc(state.active.name)}</h1><div class="phone-status" id="phone-status"><span class="status-signal"></span><span id="phone-status-text">正在连接</span></div><div class="phone-subtitle" id="subtitle"></div></main>
    <footer class="phone-controls"><button class="call-control mic-control" id="toggle-mic" aria-label="关闭麦克风" disabled><i data-lucide="mic"></i></button><button class="call-control end-call" id="end-call" aria-label="挂断"><i data-lucide="phone-off"></i></button></footer>`;
  document.body.append(phone);
  refreshIcons();
  const statusText = phone.querySelector("#phone-status-text");
  const subtitle = phone.querySelector("#subtitle");
  const micButton = phone.querySelector("#toggle-mic");
  let cancelled = false;
  let muted = false;
  let volumeFrame = 0;
  const close = async () => {
    if (cancelled) return;
    cancelled = true;
    cancelAnimationFrame(volumeFrame);
    const conversation = state.conversation;
    state.conversation = null;
    phone.remove();
    if (conversation) await conversation.endSession();
  };
  phone.querySelector("#end-call").onclick = close;

  const updateVolume = () => {
    if (cancelled || !state.conversation) return;
    const getter = phone.classList.contains("speaking") ? "getOutputVolume" : "getInputVolume";
    const level = Math.min(1, Math.max(0, Number(state.conversation[getter]?.() || 0)));
    phone.style.setProperty("--voice-level", level.toFixed(3));
    volumeFrame = requestAnimationFrame(updateVolume);
  };
  const setMode = (mode) => {
    const speaking = mode === "speaking";
    phone.classList.toggle("speaking", speaking);
    phone.classList.toggle("listening", !speaking);
    phone.classList.remove("connecting");
    statusText.textContent = speaking ? "角色正在回应" : "正在聆听";
  };
  micButton.onclick = () => {
    if (!state.conversation?.setMicMuted) return;
    muted = !muted;
    state.conversation.setMicMuted(muted);
    micButton.classList.toggle("muted", muted);
    micButton.setAttribute("aria-label", muted ? "打开麦克风" : "关闭麦克风");
    micButton.innerHTML = `<i data-lucide="${muted ? "mic-off" : "mic"}"></i>`;
    refreshIcons();
  };
  try {
    const token = (await api(`/api/token?characterId=${state.active.id}`)).token;
    if (cancelled) return;
    const conversation = await Conversation.startSession({
      conversationToken: token,
      onConnect: () => setMode("listening"),
      onModeChange: (mode) => setMode(mode.mode),
      onMessage: (message) => {
        if (message?.source === "ai" && message.message) subtitle.textContent = message.message.replace(/[*#_`\[\]]/g, "").slice(0, 160);
      },
      onError: (error) => { subtitle.textContent = error?.message || "语音连接发生错误"; },
    });
    if (cancelled) {
      await conversation.endSession();
      return;
    }
    state.conversation = conversation;
    micButton.disabled = typeof conversation.setMicMuted !== "function";
    updateVolume();
  } catch (error) {
    if (cancelled) return;
    phone.classList.remove("connecting", "listening", "speaking");
    phone.classList.add("call-error");
    statusText.textContent = "连接失败";
    subtitle.textContent = error.message || "无法接通语音模式";
  }
}

export async function openChat(id, onBack) {
  state.active = state.characters.find((item) => item.id === id);
  const result = await api(`/api/characters/${id}/messages`);
  state.messages = result.messages;
  renderChat({ onBack });
}

export function renderChat({ onBack }) {
  const character = state.active;
  const messages = state.messages.map((message) => messageMarkup(message, character)).join("");
  app.innerHTML = `<section class="chat-view"><header class="chat-header"><button class="icon-button chat-tool" id="back" aria-label="返回联系人">‹</button>${avatar(character, true)}<div class="chat-meta"><strong>${esc(character.name)}</strong><span><i class="status-dot"></i>${esc(character.voiceName)}</span></div><button class="icon-button chat-tool chat-settings" id="settings" aria-label="修改角色配置"><i data-lucide="settings-2"></i></button><button class="icon-button chat-tool call-button" id="call" aria-label="语音通话"><i data-lucide="phone"></i></button></header><div class="messages" id="messages">${messages || `<div class="empty-state">还没有消息</div>`}</div><form class="composer" id="composer"><button class="composer-button" type="button" id="dictate" aria-label="语音输入"><i data-lucide="mic"></i></button><textarea class="text-area" name="content" rows="1" placeholder="输入消息…" required></textarea><button class="composer-button send" aria-label="发送">↑</button></form></section>${settingsMarkup(character)}`;
  document.querySelector("#back").onclick = onBack;
  document.querySelector("#call").onclick = startPhone;
  document.querySelector("#composer").onsubmit = sendMessage;
  document.querySelector("#composer textarea").onkeydown = handleComposerKeydown;
  document.querySelector("#dictate").onclick = toggleDictation;
  bindSettings(onBack);
  bindSpeechButtons();
  scrollMessages();
}