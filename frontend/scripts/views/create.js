import { createIcons, SlidersHorizontal } from "https://cdn.jsdelivr.net/npm/lucide@0.468.0/+esm";
import { api } from "../api.js";
import { avatarFieldMarkup, bindAvatarEditor } from "../avatar-cropper.js";
import { app, esc, notify, shell } from "../dom.js";
import { state } from "../state.js";

function voiceOptions(selectedId) {
  return state.voices.map((voice, index) => {
    const selected = selectedId ? voice.id === selectedId : index === 0;
    return `<option value="${esc(voice.id)}" data-name="${esc(voice.name)}" ${selected ? "selected" : ""}>${esc(voice.name)} · ${esc(voice.description)}</option>`;
  }).join("");
}

const refreshIcons = () => createIcons({ icons: { SlidersHorizontal } });

function bindCounters() {
  document.querySelectorAll("[data-count]").forEach((input) => {
    const counter = document.querySelector(`[data-counter="${input.id}"]`);
    const update = () => { counter.textContent = `${input.value.length}/${input.maxLength}`; };
    input.addEventListener("input", update);
    update();
  });
}

function bindVoiceSelection() {
  const select = document.querySelector("#voice-select");
  const sync = () => { document.querySelector("[name=voiceName]").value = select.selectedOptions[0]?.dataset.name || ""; };
  select.onchange = sync;
  sync();
}

function bindVoiceStudio() {
  const dialog = document.querySelector("#voice-studio-dialog");
  const nameInput = dialog.querySelector("#voice-name");
  const promptInput = dialog.querySelector("#voice-prompt");
  const button = dialog.querySelector("#design-voice");
  const status = dialog.querySelector("#studio-status");
  const counter = dialog.querySelector('[data-counter="voice-prompt"]');
  const resetTextareaSize = () => {
    promptInput.style.height = "";
    promptInput.style.overflowY = "";
  };
  const closeStudio = () => {
    resetTextareaSize();
    dialog.close();
  };
  document.querySelector("#open-voice-studio").onclick = () => {
    resetTextareaSize();
    dialog.showModal();
  };
  dialog.querySelectorAll("[data-dialog-close]").forEach((item) => { item.onclick = closeStudio; });
  dialog.onclick = (event) => { if (event.target === dialog) closeStudio(); };
  dialog.oncancel = (event) => {
    event.preventDefault();
    closeStudio();
  };
  const validate = () => {
    button.disabled = nameInput.value.trim().length < 2 || promptInput.value.trim().length < 10;
    counter.textContent = `${promptInput.value.length}/500`;
  };
  nameInput.addEventListener("input", validate);
  promptInput.addEventListener("input", validate);
  validate();

  button.onclick = async () => {
    const name = nameInput.value.trim();
    const prompt = promptInput.value.trim();
    button.disabled = true;
    button.innerHTML = '<span class="loading-text">正在生成音色</span>';
    status.style.color = "";
    status.textContent = "正在设计并保存音色，请保持页面开启。";
    try {
      const result = await api("/api/voices/design", {
        method: "POST",
        body: JSON.stringify({ name, prompt }),
      });
      state.voices.unshift(result.voice);
      const select = document.querySelector("#voice-select");
      select.innerHTML = voiceOptions(result.voice.id);
      bindVoiceSelection();
      nameInput.value = "";
      promptInput.value = "";
      document.querySelector('[data-counter="voice-prompt"]').textContent = "0/500";
      status.textContent = "新音色已加入音色库，并设为当前角色音色。";
      button.textContent = "生成音色";
      validate();
      notify("新音色已生成并选中");
    } catch (error) {
      status.textContent = error.message;
      status.style.color = "var(--warning)";
      button.textContent = "重新生成";
      validate();
    }
  };
}

function studioMarkup() {
  return `<dialog class="app-dialog" id="voice-studio-dialog">
    <div class="dialog-panel">
      <header class="dialog-header"><h2>自定义音色</h2></header>
      <div class="dialog-body">
        <div class="field"><label for="voice-name">音色名称</label><input class="text-input" id="voice-name" maxlength="40" placeholder="例如：远航领航员"></div>
        <div class="field"><label for="voice-prompt">声音描述</label><textarea class="text-area" id="voice-prompt" maxlength="500" placeholder="例如：成熟清晰的中文女声，语速从容，音色温暖但有力量…"></textarea><span class="char-count" data-counter="voice-prompt"></span></div>
        <p class="studio-status" id="studio-status"></p>
      </div>
      <footer class="dialog-actions"><button type="button" class="secondary-button" data-dialog-close>取消</button><button type="button" class="primary-button" id="design-voice">生成音色</button></footer>
    </div>
  </dialog>`;
}

export function renderCreate({ bindShell, onCreated }) {
  const selected = state.voices[0];
  const content = `<form id="create-form">
    <section class="page-heading"><div><h1>新建角色</h1></div></section>
    <section class="section">${avatarFieldMarkup({ id: "create-avatar" })}</section>
    <section class="section"><div class="field"><label for="character-name">角色名称</label><input class="text-input" id="character-name" name="name" required maxlength="40" placeholder="例如：阿尔茜"></div></section>
    <section class="section"><div class="field"><label for="persona">身份背景</label><textarea class="text-area" id="persona" name="persona" required maxlength="2400" placeholder="角色的身份、经历、性格、价值观与表达方式"></textarea></div></section>
    <section class="section"><div class="field"><label for="language">回答语言</label><select class="select-input" id="language" name="language"><option value="zh" selected>中文</option><option value="en">英文</option></select></div></section>
    <section class="section"><div class="section-header"><div class="section-title"><h2>角色音色</h2></div></div><div class="voice-picker"><div class="field"><label for="voice-select">音色</label><select class="select-input" id="voice-select" name="voiceId">${voiceOptions(selected?.id)}</select><input type="hidden" name="voiceName" value="${esc(selected?.name || "")}"></div><button class="secondary-button studio-launch" type="button" id="open-voice-studio"><i data-lucide="sliders-horizontal"></i><span>自定义音色</span></button></div></section>
    <div class="form-actions"><button class="primary-button full-width" type="submit">创建角色</button></div>
  </form>${studioMarkup()}`;
  app.innerHTML = shell(content, "create");
  bindShell();
  bindAvatarEditor(document.querySelector("#create-form"));
  bindVoiceSelection();
  bindVoiceStudio();
  refreshIcons();
  document.querySelector("#create-form").onsubmit = async (event) => {
    event.preventDefault();
    const submitButton = event.submitter;
    submitButton.disabled = true;
    submitButton.textContent = "正在创建角色";
    try {
      await api("/api/characters", {
        method: "POST",
        body: JSON.stringify(Object.fromEntries(new FormData(event.currentTarget))),
      });
      notify("角色已加入联系人");
      await onCreated();
    } catch (error) {
      notify(error.message);
      submitButton.disabled = false;
      submitButton.textContent = "创建角色并保存";
    }
  };
}