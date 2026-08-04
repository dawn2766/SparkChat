import { ArrowLeft, createIcons, Check, Clock3, Copy, Ellipsis, Languages, Mic, MicOff, Pencil, Pause, Phone, PhoneOff, Play, Plus, RefreshCw, Send, Settings2, Trash2, Volume2, X } from "https://cdn.jsdelivr.net/npm/lucide@0.468.0/+esm";
import { api, apiUrl, streamChat } from "../api.js";
import { createRealtimeSession } from "../doubao-realtime.js";
import { mergeRealtimeText } from "../realtime-text.js";
import { avatarFieldMarkup, bindAvatarEditor } from "../avatar-cropper.js";
import { app, avatar, confirmDeletion, esc, notify, scrollMessages } from "../dom.js";
import { state } from "../state.js";

const refreshIcons = () => createIcons({ icons: { ArrowLeft, Check, Clock3, Copy, Ellipsis, Languages, Mic, MicOff, Pencil, Pause, Phone, PhoneOff, Play, Plus, RefreshCw, Send, Settings2, Trash2, Volume2, X } });
let speechAudio = null;
let speechUrl = null;
let speechRequest = null;
let speechButton = null;
let dictationGeneration = 0;
let pendingDictationConversation = null;

function stopSpeechAudio() {
  speechRequest?.abort();
  speechRequest = null;
  if (speechAudio) {
    speechAudio.pause();
    speechAudio.removeAttribute("src");
    speechAudio.load();
  }
  if (speechUrl) URL.revokeObjectURL(speechUrl);
  const previousButton = speechButton;
  speechAudio = null;
  speechUrl = null;
  speechButton = null;
  updateSpeechButton(previousButton, false);
  document.querySelectorAll(".speak-button.playing").forEach((item) => item.classList.remove("playing"));
}

function updateSpeechButton(button, playing) {
  if (!button) return;
  button.classList.toggle("playing", playing);
  button.setAttribute("aria-label", playing ? "暂停朗读" : "继续朗读");
  button.innerHTML = `<i data-lucide="${playing ? "pause" : "play"}"></i>`;
  refreshIcons();
}

export async function stopVoiceInteraction() {
  dictationGeneration += 1;
  stopSpeechAudio();
  const conversation = state.conversation;
  const pendingConversation = pendingDictationConversation;
  state.conversation = null;
  pendingDictationConversation = null;
  state.listening = false;
  setDictationState("idle");
  await Promise.all([
    conversation?.stop(),
    pendingConversation && pendingConversation !== conversation ? pendingConversation.stop() : null,
  ]);
  document.querySelector(".phone-overlay")?.remove();
}

function setDictationState(mode) {
  const button = document.querySelector("#dictate");
  if (!button) return;
  const recording = mode === "recording";
  button.disabled = mode === "starting";
  button.classList.toggle("recording", recording);
  button.setAttribute("aria-label", mode === "starting" ? "正在启动语音输入" : recording ? "停止语音输入" : "语音输入");
}

function resizeComposer(textarea) {
  textarea.style.height = "auto";
  textarea.style.height = `${Math.min(textarea.scrollHeight, 110)}px`;
  textarea.style.overflowY = textarea.scrollHeight > 110 ? "auto" : "hidden";
}

function resetTextareaSize(textarea) {
  textarea.style.height = "";
  textarea.style.overflowY = "";
}

function updateComposerState(textarea) {
  const sendButton = textarea.form?.querySelector(".send");
  if (!sendButton) return;
  const hasContent = textarea.value.trim().length > 0;
  textarea.form.classList.toggle("send-hidden", !hasContent);
  sendButton.setAttribute("aria-hidden", String(!hasContent));
  sendButton.disabled = state.sending || !hasContent;
}

function messageActionsMarkup(message, isAssistant, canRegenerate = false) {
  if (!isAssistant) return "";
  const regenerateButton = canRegenerate
    ? `<button class="message-action" data-regenerate="${message.id || ""}" aria-label="重新生成这条回复"><i data-lucide="refresh-cw"></i></button>`
    : "";
  return `<span class="message-actions"><button class="message-action" data-copy aria-label="复制这条回复"><i data-lucide="copy"></i></button><button class="message-action translate-button" data-translate="${message.id || ""}" aria-label="翻译这条回复"><i data-lucide="languages"></i></button>${regenerateButton}<button class="speak-button" data-speak aria-label="朗读这条回复"><i data-lucide="volume-2"></i></button></span>`;
}

function assistantStampMarkup(message, character, canRegenerate = false) {
  return `<span class="stamp">${messageActionsMarkup(message, true, canRegenerate)}</span>`;
}

function messageMarkup(message, character, canRegenerate = false) {
  const isAssistant = message.role === "assistant";
  const stamp = isAssistant ? assistantStampMarkup(message, character, canRegenerate) : messageActionsMarkup(message, false);
  const bubble = isAssistant
    ? `<div class="bubble">${esc(message.content)}</div>`
    : `<button class="bubble user-bubble" type="button" data-edit-user-message aria-label="编辑并重新发送这条消息">${esc(message.content)}</button>`;
  return `<div class="message ${message.role === "user" ? "user" : ""}" data-message-id="${message.id || ""}" data-original-content="${esc(message.content)}"><div class="message-content">${bubble}${stamp}</div></div>`;
}

async function rewriteUserMessage(message, content) {
  if (state.sending) return;
  const messageId = Number(message.dataset.messageId);
  if (!messageId) {
    notify("消息仍在保存，请稍后再编辑");
    return;
  }
  state.sending = true;
  const originalMessages = state.messages.slice();
  const contentNode = message.querySelector(".message-content");
  contentNode.innerHTML = `<div class="bubble">${esc(content)}</div><span class="stamp loading-text">正在更新对话…</span>`;
  try {
    await streamChat(state.active.id, content, () => {}, messageId, state.activeConversation.id, true);
    state.messages = (await api(`/api/characters/${state.active.id}/conversations/${state.activeConversation.id}/messages`)).messages;
    state.conversations = (await api(`/api/characters/${state.active.id}/conversations`)).conversations;
    state.activeConversation = state.conversations.find((item) => item.id === state.activeConversation.id) || state.activeConversation;
    notify("聊天历史已更新");
    renderChat({ onBack: window.__sparkchatBack });
  } catch (error) {
    state.messages = originalMessages;
    notify(error.message);
    renderChat({ onBack: window.__sparkchatBack });
  } finally {
    state.sending = false;
  }
}

function beginUserMessageEdit(message) {
  if (state.sending || message.querySelector(".message-edit-form")) return;
  const original = message.dataset.originalContent || message.querySelector(".bubble")?.textContent || "";
  const contentNode = message.querySelector(".message-content");
  contentNode.innerHTML = `<form class="message-edit-form"><textarea class="text-area" name="content" maxlength="4000" required aria-label="编辑消息"></textarea><div class="message-edit-actions"><button class="secondary-button" type="button" data-cancel-edit>取消</button><button class="primary-button" type="submit">更新并发送</button></div></form>`;
  const form = contentNode.querySelector("form");
  form.content.value = original;
  form.querySelector("[data-cancel-edit]").onclick = () => renderChat({ onBack: window.__sparkchatBack });
  form.onsubmit = async (event) => {
    event.preventDefault();
    const content = form.content.value.trim();
    if (!content || content === original) {
      if (content === original) renderChat({ onBack: window.__sparkchatBack });
      return;
    }
    await rewriteUserMessage(message, content);
  };
  form.content.focus();
  form.content.setSelectionRange(form.content.value.length, form.content.value.length);
}

function bindSpeechButtons() {
  document.querySelectorAll("[data-speak]").forEach((button) => {
    button.onclick = () => speak(button.closest(".message")?.querySelector(".bubble")?.textContent || "", button);
  });
  refreshIcons();
}

function bindMessageActions() {
  const container = document.querySelector("#messages");
  if (!container) return;
  container.onclick = async (event) => {
    const userBubble = event.target.closest("[data-edit-user-message]");
    if (userBubble) {
      beginUserMessageEdit(userBubble.closest(".message"));
      return;
    }
    const copyButton = event.target.closest("[data-copy]");
    if (copyButton) {
      try {
        await navigator.clipboard.writeText(copyButton.closest(".message").querySelector(".bubble").textContent);
        notify("已复制");
      } catch (_error) {
        notify("复制失败，请检查浏览器剪贴板权限");
      }
      return;
    }
    const translateButton = event.target.closest("[data-translate]");
    if (translateButton?.dataset.translate) {
      if (translateButton.disabled || state.sending) return;
      const message = translateButton.closest(".message");
      const bubble = message.querySelector(".bubble");
      if (message.dataset.translated === "true") {
        stopSpeechAudio();
        bubble.textContent = message.dataset.originalContent;
        message.dataset.translated = "false";
        translateButton.setAttribute("aria-label", "翻译这条回复");
        translateButton.classList.remove("active");
        return;
      }
      translateButton.disabled = true;
      try {
        const result = await api(`/api/characters/${state.active.id}/messages/${translateButton.dataset.translate}/translate`, { method: "POST" });
        bubble.textContent = result.translation;
        message.dataset.translated = "true";
        translateButton.setAttribute("aria-label", "显示原文");
        translateButton.classList.add("active");
        stopSpeechAudio();
      } catch (error) {
        notify(error.message);
      } finally {
        translateButton.disabled = false;
      }
      return;
    }
    const regenerateButton = event.target.closest("[data-regenerate]");
    if (!regenerateButton?.dataset.regenerate) return;
    if (state.sending) return;
    const message = regenerateButton.closest(".message");
    const bubble = message.querySelector(".bubble");
    const oldText = bubble.textContent;
    const oldOriginalContent = message.dataset.originalContent || oldText;
    state.sending = true;
    regenerateButton.disabled = true;
    message.classList.add("pending");
    message.dataset.translated = "false";
    message.dataset.originalContent = oldOriginalContent;
    const regenerateTranslateButton = message.querySelector("[data-translate]");
    regenerateTranslateButton?.classList.remove("active");
    regenerateTranslateButton?.setAttribute("aria-label", "翻译这条回复");
    try {
      const result = await streamChat(state.active.id, "", (partial) => {
        bubble.textContent = partial;
        message.classList.remove("pending");
        scrollMessages();
      }, Number(regenerateButton.dataset.regenerate), state.activeConversation.id);
      bubble.textContent = result.answer;
      message.dataset.messageId = result.messageId;
      const index = state.messages.findIndex((item) => item.id === Number(result.messageId));
      if (index >= 0) state.messages[index].content = result.answer;
      message.dataset.originalContent = result.answer;
      message.classList.remove("pending");
      notify("已生成新的回复");
    } catch (error) {
      bubble.textContent = oldText;
      const wasTranslated = oldText !== oldOriginalContent;
      message.dataset.translated = wasTranslated ? "true" : "false";
      regenerateTranslateButton?.classList.toggle("active", wasTranslated);
      regenerateTranslateButton?.setAttribute("aria-label", wasTranslated ? "显示原文" : "翻译这条回复");
      notify(error.message);
    } finally {
      state.sending = false;
      regenerateButton.disabled = false;
      message.classList.remove("pending");
    }
  };
}

async function speak(text, button = null) {
  if (!state.active || !text) return;
  if (speechAudio && speechButton === button) {
    if (speechAudio.paused) {
      await speechAudio.play();
      updateSpeechButton(button, true);
    } else {
      speechAudio.pause();
      updateSpeechButton(button, false);
    }
    return;
  }
  stopSpeechAudio();
  speechButton = button;
  updateSpeechButton(button, true);
  try {
    speechRequest = new AbortController();
    const messageId = button?.closest(".message")?.dataset.messageId;
    const path = messageId
      ? `/api/characters/${state.active.id}/messages/${messageId}/speak`
      : `/api/characters/${state.active.id}/speak`;
    const response = await fetch(apiUrl(path), { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }), signal: speechRequest.signal });
    speechRequest = null;
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw Error(data.error || "语音生成失败");
    }
    const contentType = response.headers.get("Content-Type") || "";
    if (!contentType.startsWith("audio/")) throw Error("语音服务返回了无效音频格式");
    speechUrl = URL.createObjectURL(await response.blob());
    speechAudio = new Audio(speechUrl);
    speechAudio.onended = stopSpeechAudio;
    speechAudio.onerror = () => { stopSpeechAudio(); notify("音频播放失败"); };
    await speechAudio.play();
  } catch (error) {
    if (speechButton === button) stopSpeechAudio();
    if (error.name !== "AbortError") {
      if (error.name === "NotAllowedError") notify("浏览器阻止了音频播放，请再次点击朗读按钮");
      else notify(error.message);
    }
  }
}

async function toggleDictation() {
  const button = document.querySelector("#dictate");
  if (!button || button.disabled) return;
  if (state.conversation) {
    dictationGeneration += 1;
    const conversation = state.conversation;
    state.conversation = null;
    state.listening = false;
    setDictationState("idle");
    await conversation.stop();
    return;
  }
  const generation = ++dictationGeneration;
  try {
    state.listening = true;
    setDictationState("starting");
    const textarea = document.querySelector("#composer textarea");
    const initialText = textarea.value;
    let committedText = "";
    const conversation = await createRealtimeSession(state.active, {
      onTranscript: (data) => {
        if (generation !== dictationGeneration) return;
        if (!data.text) return;
        const mergedText = mergeRealtimeText(committedText, data.text);
        textarea.value = `${initialText}${initialText && mergedText ? " " : ""}${mergedText}`;
        if (!data.interim) committedText = mergedText;
        resizeComposer(textarea);
        updateComposerState(textarea);
      },
      onError: (error) => notify(error.message || "未能识别语音"),
      onClose: () => {
        if (generation !== dictationGeneration) return;
        state.listening = false;
        setDictationState("idle");
        if (state.conversation === conversation) state.conversation = null;
      },
    }, { playAudio: false });
    pendingDictationConversation = conversation;
    if (generation !== dictationGeneration) {
      await conversation.stop();
      if (pendingDictationConversation === conversation) pendingDictationConversation = null;
      return;
    }
    state.conversation = conversation;
    await conversation.beginMicrophone();
    if (generation !== dictationGeneration || state.conversation !== conversation) {
      await conversation.stop();
      if (pendingDictationConversation === conversation) pendingDictationConversation = null;
      return;
    }
    pendingDictationConversation = null;
    setDictationState("recording");
  } catch (error) {
    if (generation !== dictationGeneration) return;
    const conversation = state.conversation;
    state.conversation = null;
    pendingDictationConversation = null;
    await conversation?.stop();
    notify(error.message || "无法启动豆包语音识别");
    state.listening = false;
    setDictationState("idle");
  }
}

async function sendMessage(event) {
  event.preventDefault();
  if (state.sending) return;
  const form = event.currentTarget;
  const textarea = form.content;
  state.sending = true;
  await stopVoiceInteraction();
  const content = textarea.value.trim();
  if (!content) {
    state.sending = false;
    updateComposerState(textarea);
    return;
  }
  textarea.value = "";
  resizeComposer(textarea);
  updateComposerState(textarea);
  const userMessage = { role: "user", content };
  state.messages.push(userMessage);
  const container = document.querySelector("#messages");
  const assistant = document.createElement("div");
  assistant.className = "message pending";
  assistant.innerHTML = `<div><div class="bubble">正在回应…</div><span class="stamp"></span></div>`;
  container.insertAdjacentHTML("beforeend", messageMarkup({ role: "user", content }, state.active));
  container.append(assistant);
  const bubble = assistant.querySelector(".bubble");
  scrollMessages();
  try {
    const result = await streamChat(state.active.id, content, (partial) => { bubble.textContent = partial; assistant.classList.remove("pending"); scrollMessages(); }, null, state.activeConversation.id);
    userMessage.id = result.userMessageId;
    const userElement = container.querySelector(`.message.user:not([data-message-id]), .message.user[data-message-id=""]`);
    if (userElement) userElement.dataset.messageId = String(result.userMessageId || "");
    if (state.messages.length === 1 && !state.activeConversation.titleCustom) {
      state.activeConversation.title = content.slice(0, 80);
      document.querySelector(".chat-meta span").textContent = state.activeConversation.title;
    }
    state.messages.push({ id: result.messageId, role: "assistant", content: result.answer });
    assistant.classList.remove("pending");
    assistant.dataset.messageId = result.messageId;
    container.querySelectorAll("[data-regenerate]").forEach((button) => button.remove());
    assistant.querySelector(".stamp").outerHTML = assistantStampMarkup({ id: result.messageId, content: result.answer }, state.active, true);
    bindSpeechButtons();
  } catch (error) {
    assistant.classList.remove("pending");
    assistant.classList.add("failed");
    bubble.textContent = `未能送达回复：${error.message}`;
    textarea.value = content;
    resizeComposer(textarea);
    updateComposerState(textarea);
    notify("发送失败，消息已保留，可再次发送");
  } finally {
    state.sending = false;
    updateComposerState(textarea);
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
        ${avatarFieldMarkup({ currentUrl: character.avatarUrl, id: "edit-avatar" })}
        <div class="field"><label for="edit-name">角色名称</label><input class="text-input" id="edit-name" name="name" maxlength="40" required value="${esc(character.name)}"></div>
        <div class="field"><label for="edit-persona">身份背景</label><textarea class="text-area character-prompt" id="edit-persona" name="persona" maxlength="2400" required>${esc(character.persona)}</textarea></div>
        <div class="field"><label for="edit-language">回答语言</label><select class="select-input" id="edit-language" name="language"><option value="zh" ${character.language === "zh" ? "selected" : ""}>中文</option><option value="en" ${character.language === "en" ? "selected" : ""}>英文</option></select></div>
        <div class="field"><label for="edit-voice">角色音色</label><select class="select-input" id="edit-voice" name="voiceId">${voiceOptions(character.voiceId)}</select><input type="hidden" name="voiceName" value="${esc(character.voiceName)}"></div>
      </div>
      <footer class="dialog-actions ${character.isPreset ? "" : "dialog-actions-split"}">${character.isPreset ? "" : '<button type="button" class="danger-button" data-delete-character>删除角色</button>'}<span class="dialog-action-group"><button type="button" class="secondary-button" data-dialog-close>取消</button><button class="primary-button" type="submit">保存配置</button></span></footer>
    </form>
  </dialog>`;
}

function bindSettings(onBack) {
  const dialog = document.querySelector("#character-dialog");
  const form = document.querySelector("#character-form");
  bindAvatarEditor(form);
  const resetForm = () => {
    form.name.value = state.active.name;
    form.persona.value = state.active.persona;
    form.voiceId.value = state.active.voiceId;
    form.voiceName.value = state.active.voiceName;
    form.language.value = state.active.language || "zh";
    form.avatarUrl.value = state.active.avatarUrl || "";
    form.querySelector("[data-avatar-editor]").resetAvatar(state.active.avatarUrl || "");
    resetTextareaSize(form.persona);
  };
  const cancelSettings = () => {
    resetForm();
    dialog.close();
  };
  document.querySelector("#settings").onclick = () => {
    resetForm();
    dialog.showModal();
  };
  dialog.querySelectorAll("[data-dialog-close]").forEach((button) => { button.onclick = cancelSettings; });
  const deleteButton = dialog.querySelector("[data-delete-character]");
  if (deleteButton) {
    deleteButton.onclick = async () => {
      if (!await confirmDeletion({ title: "删除角色", name: state.active.name, message: "角色及其聊天记录都将被删除，且无法恢复。" })) return;
      deleteButton.disabled = true;
      try {
        await api(`/api/characters/${state.active.id}`, { method: "DELETE" });
        dialog.close();
        state.characters = state.characters.filter((item) => item.id !== state.active.id);
        notify("角色及其聊天记录已删除");
        await onBack();
      } catch (error) {
        notify(error.message);
        deleteButton.disabled = false;
      }
    };
  }
  dialog.onclick = (event) => {
    if (event.target === dialog) cancelSettings();
  };
  dialog.oncancel = (event) => {
    event.preventDefault();
    cancelSettings();
  };
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
  phone.innerHTML = `<main class="phone-stage"><div class="voice-orbit"><div class="voice-bars" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></div>${avatar(state.active)}</div><h1>${esc(state.active.name)}</h1><div class="phone-status" id="phone-status"><span class="status-signal"></span><span id="phone-status-text">正在连接</span></div><div class="phone-subtitles"><div class="phone-subtitle user-subtitle" id="user-subtitle"></div><div class="phone-subtitle assistant-subtitle" id="assistant-subtitle"></div></div></main>
    <footer class="phone-controls"><button class="call-control mic-control" id="toggle-mic" aria-label="关闭麦克风" disabled><i data-lucide="mic"></i></button><button class="call-control end-call" id="end-call" aria-label="挂断"><i data-lucide="phone-off"></i></button></footer>`;
  document.body.append(phone);
  refreshIcons();
  const statusText = phone.querySelector("#phone-status-text");
  const userSubtitle = phone.querySelector("#user-subtitle");
  const assistantSubtitle = phone.querySelector("#assistant-subtitle");
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
    if (conversation) await conversation.stop();
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
    if (!state.conversation?.mute) return;
    muted = !muted;
    state.conversation.mute(muted);
    micButton.classList.toggle("muted", muted);
    micButton.setAttribute("aria-label", muted ? "打开麦克风" : "关闭麦克风");
    micButton.innerHTML = `<i data-lucide="${muted ? "mic-off" : "mic"}"></i>`;
    refreshIcons();
  };
  try {
    const conversation = await createRealtimeSession(state.active, {
      onReady: () => setMode("listening"),
      onText: (text) => {
        if (!text) return;
        assistantSubtitle.textContent = text;
      },
      onTranscript: (data) => {
        userSubtitle.textContent = data.text || "";
        userSubtitle.classList.toggle("interim", Boolean(data.interim));
        if (!data.interim && data.text) assistantSubtitle.textContent = "";
        setMode("listening");
      },
      onPlaybackChange: (playing) => setMode(playing ? "speaking" : "listening"),
      onError: (error) => { assistantSubtitle.textContent = error?.message || "语音连接发生错误"; },
    });
    if (cancelled) {
      await conversation.stop();
      return;
    }
    state.conversation = conversation;
    micButton.disabled = false;
    await conversation.beginMicrophone();
  } catch (error) {
    if (cancelled) return;
    phone.classList.remove("connecting", "listening", "speaking");
    phone.classList.add("call-error");
    statusText.textContent = "连接失败";
    assistantSubtitle.textContent = error.message || "无法接通语音模式";
  }
}

function formatConversationTime(value) {
  if (!value) return "";
  const date = new Date(`${value.replace(" ", "T")}Z`);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleDateString("zh-CN", { month: "short", day: "numeric" });
}

function historyBodyMarkup() {
  const rows = state.conversations.map((conversation) => `<li class="conversation-row ${conversation.id === state.activeConversation?.id ? "active" : ""}" data-conversation="${conversation.id}"><button class="conversation-open" type="button"><span class="conversation-copy"><strong>${esc(conversation.title)}</strong><small>${esc(conversation.lastMessage || "空对话")}</small></span><time>${formatConversationTime(conversation.updatedAt)}</time></button><div class="conversation-options"><button class="conversation-options-button" type="button" data-conversation-options aria-label="对话选项"><i data-lucide="ellipsis"></i></button><div class="conversation-menu" role="menu"><button type="button" data-rename-conversation="${conversation.id}"><i data-lucide="pencil"></i><span>修改名称</span></button><button type="button" data-delete-conversation="${conversation.id}" class="danger"><i data-lucide="trash-2"></i><span>删除对话</span></button></div></div></li>`).join("");
  return `<button class="new-conversation-button" type="button" id="new-conversation"><i data-lucide="plus"></i><span>创建新对话</span></button><ul class="conversation-list">${rows || `<li class="history-empty">还没有历史对话</li>`}</ul>`;
}

function historyMarkup() {
  return `<dialog class="app-dialog history-dialog" id="history-dialog"><div class="dialog-panel"><header class="dialog-header"><div><h2>历史对话</h2></div><button class="icon-button" type="button" data-history-close aria-label="关闭历史对话"><i data-lucide="x"></i></button></header><div class="history-body">${historyBodyMarkup()}</div></div></dialog>`;
}

async function loadConversation(conversation) {
  await stopVoiceInteraction();
  state.activeConversation = conversation;
  const result = await api(`/api/characters/${state.active.id}/conversations/${conversation.id}/messages`);
  state.messages = result.messages;
  renderChat({ onBack: window.__sparkchatBack });
}

async function createConversation() {
  const result = await api(`/api/characters/${state.active.id}/conversations`, { method: "POST" });
  await loadConversation(result.conversation);
}

function renderHistoryBody(dialog) {
  dialog.querySelector(".history-body").innerHTML = historyBodyMarkup();
  dialog.querySelector("#new-conversation").onclick = async () => { dialog.close(); await createConversation(); };
  dialog.querySelectorAll("[data-conversation]").forEach((row) => {
    row.querySelector(".conversation-open").onclick = async () => { dialog.close(); await loadConversation(state.conversations.find((item) => item.id === Number(row.dataset.conversation))); };
  });
  dialog.querySelectorAll("[data-conversation-options]").forEach((button) => {
    button.onclick = (event) => {
      event.stopPropagation();
      const menu = button.nextElementSibling;
      dialog.querySelectorAll(".conversation-menu.open").forEach((item) => { if (item !== menu) item.classList.remove("open"); });
      menu.classList.toggle("open");
      if (menu.classList.contains("open")) {
        const buttonRect = button.getBoundingClientRect();
        const menuWidth = menu.offsetWidth;
        const menuHeight = menu.offsetHeight;
        const edge = 8;
        const left = Math.max(edge, Math.min(buttonRect.right - menuWidth, window.innerWidth - menuWidth - edge));
        const below = buttonRect.bottom + 6;
        const above = buttonRect.top - menuHeight - 6;
        const top = below + menuHeight <= window.innerHeight - edge || above < edge ? below : above;
        menu.style.left = `${left}px`;
        menu.style.top = `${Math.max(edge, Math.min(top, window.innerHeight - menuHeight - edge))}px`;
      }
    };
  });
  dialog.querySelectorAll("[data-rename-conversation]").forEach((button) => {
    button.onclick = async () => {
      const conversation = state.conversations.find((item) => item.id === Number(button.dataset.renameConversation));
      const row = button.closest(".conversation-row");
      row.innerHTML = `<form class="conversation-edit"><input class="text-input" name="title" maxlength="80" required value="${esc(conversation.title)}" aria-label="对话名称"><button type="submit" aria-label="保存对话名称"><i data-lucide="check"></i></button><button type="button" data-cancel-rename aria-label="取消重命名"><i data-lucide="x"></i></button></form>`;
      const form = row.querySelector("form");
      form.querySelector("[data-cancel-rename]").onclick = () => renderHistoryBody(dialog);
      form.onsubmit = async (event) => {
        event.preventDefault();
        const title = form.title.value.trim();
        if (!title) return;
        try {
          const result = await api(`/api/characters/${state.active.id}/conversations/${conversation.id}`, { method: "PATCH", body: JSON.stringify({ title }) });
          Object.assign(conversation, result.conversation);
          if (state.activeConversation?.id === conversation.id) {
            state.activeConversation = conversation;
            document.querySelector(".chat-meta span").textContent = conversation.title;
          }
          renderHistoryBody(dialog);
        } catch (error) { notify(error.message); }
      };
      form.title.focus();
      form.title.select();
      refreshIcons();
    };
  });
  dialog.querySelectorAll("[data-delete-conversation]").forEach((button) => {
    button.onclick = async () => {
      const conversation = state.conversations.find((item) => item.id === Number(button.dataset.deleteConversation));
      if (!conversation) return;
      if (!await confirmDeletion({ title: "删除对话", name: conversation.title, message: "这段对话及其消息记录将被删除，且无法恢复。" })) return;
      try {
        await api(`/api/characters/${state.active.id}/conversations/${conversation.id}`, { method: "DELETE" });
        state.conversations = state.conversations.filter((item) => item.id !== conversation.id);
        if (state.activeConversation?.id === conversation.id) {
          if (!state.conversations.length) {
            dialog.close();
            await createConversation();
            return;
          }
          dialog.close();
          await loadConversation(state.conversations[0]);
          return;
        }
        renderHistoryBody(dialog);
      } catch (error) { notify(error.message); }
    };
  });
  dialog.onclick = (event) => {
    if (event.target === dialog) {
      dialog.close();
      return;
    }
    if (!event.target.closest(".conversation-options")) dialog.querySelectorAll(".conversation-menu.open").forEach((menu) => menu.classList.remove("open"));
  };
  refreshIcons();
}

function bindHistory() {
  const dialog = document.querySelector("#history-dialog");
  document.querySelector("#history").onclick = async () => {
    state.conversations = (await api(`/api/characters/${state.active.id}/conversations`)).conversations;
    renderHistoryBody(dialog);
    dialog.showModal();
  };
  dialog.querySelector("[data-history-close]").onclick = () => dialog.close();
  dialog.onclick = (event) => { if (event.target === dialog) dialog.close(); };
  renderHistoryBody(dialog);
}

export async function openChat(id, onBack) {
  state.active = state.characters.find((item) => item.id === id);
  window.__sparkchatBack = onBack;
  const result = await api(`/api/characters/${id}/conversations`);
  state.conversations = result.conversations;
  if (!state.conversations.length) {
    const created = await api(`/api/characters/${id}/conversations`, { method: "POST" });
    state.conversations = [created.conversation];
  }
  state.activeConversation = state.conversations[0];
  state.messages = (await api(`/api/characters/${id}/conversations/${state.activeConversation.id}/messages`)).messages;
  renderChat({ onBack });
}

export function renderChat({ onBack }) {
  const character = state.active;
  const latestAssistantIndex = state.messages.reduce((latest, message, index) => message.role === "assistant" ? index : latest, -1);
  const messages = state.messages.map((message, index) => messageMarkup(message, character, index === latestAssistantIndex)).join("");
  app.innerHTML = `<section class="chat-view"><header class="chat-header"><button class="icon-button chat-tool" id="back" aria-label="返回联系人"><i data-lucide="arrow-left"></i></button>${avatar(character, true)}<div class="chat-meta"><strong>${esc(character.name)}</strong><span>${esc(state.activeConversation?.title || "新对话")}</span></div><div class="chat-actions"><button class="icon-button chat-tool" id="history" aria-label="历史对话"><i data-lucide="clock-3"></i></button><button class="icon-button chat-tool chat-settings" id="settings" aria-label="修改角色配置"><i data-lucide="settings-2"></i></button><button class="icon-button chat-tool call-button" id="call" aria-label="语音通话"><i data-lucide="phone"></i></button></div></header><div class="messages" id="messages">${messages}</div><form class="composer send-hidden" id="composer"><button class="composer-button" type="button" id="dictate" aria-label="语音输入"><i data-lucide="mic"></i></button><textarea class="text-area" name="content" rows="1" placeholder="输入消息…" required></textarea><button class="composer-button send" type="submit" aria-label="发送" aria-hidden="true" disabled><i data-lucide="send"></i></button></form></section>${settingsMarkup(character)}${historyMarkup()}`;
  document.querySelector("#back").onclick = async () => {
    await stopVoiceInteraction();
    onBack();
  };
  document.querySelector("#call").onclick = startPhone;
  bindHistory();
  document.querySelector("#composer").onsubmit = sendMessage;
  const composer = document.querySelector("#composer textarea");
  composer.onkeydown = handleComposerKeydown;
  composer.oninput = () => {
    resizeComposer(composer);
    updateComposerState(composer);
  };
  resizeComposer(composer);
  updateComposerState(composer);
  document.querySelector("#dictate").onclick = toggleDictation;
  bindSettings(onBack);
  bindSpeechButtons();
  bindMessageActions();
  scrollMessages();
}