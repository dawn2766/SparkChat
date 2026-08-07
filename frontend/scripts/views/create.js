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

export function renderCreate({ bindShell, onCreated }) {
  const selected = state.voices[0];
  const content = `<section class="page-heading"><div><h1>新建角色</h1></div></section><form class="main-page-body scroll-container" id="create-form">
    <section class="section character-fields">
      ${avatarFieldMarkup({ id: "create-avatar" })}
      <div class="field"><label for="character-name">角色名称</label><input class="text-input" id="character-name" name="name" required maxlength="40" placeholder="例如：阿尔茜"></div>
      <div class="field"><label for="persona">身份背景</label><textarea class="text-area character-prompt" id="persona" name="persona" required maxlength="2400" placeholder="角色的身份、经历、性格、价值观与表达方式"></textarea></div>
      <div class="field"><label for="language">回答语言</label><select class="select-input" id="language" name="language"><option value="zh" selected>中文</option><option value="en">英文</option></select></div>
      <div class="field"><label for="voice-select">角色音色</label><select class="select-input" id="voice-select" name="voiceId">${voiceOptions(selected?.id)}</select><input type="hidden" name="voiceName" value="${esc(selected?.name || "")}"></div>
    </section>
    <div class="form-actions character-form-actions"><button class="primary-button full-width" type="submit">创建角色</button></div>
  </form>`;
  app.innerHTML = shell(content, "create");
  bindShell();
  bindAvatarEditor(document.querySelector("#create-form"));
  bindVoiceSelection();
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
      await onCreated();
    } catch (error) {
      notify(error.message);
      submitButton.disabled = false;
      submitButton.textContent = "创建角色并保存";
    }
  };
}