import { api } from "../api.js";
import { avatarFieldMarkup, bindAvatarEditor } from "../avatar-cropper.js";
import { app, avatar, confirmDeletion, esc, notify, shell } from "../dom.js";
import { state } from "../state.js";

function userRowsMarkup(users) {
  return users.map((user) => `<li class="user-admin-row" data-user-id="${user.id}"><div class="user-admin-identity"><strong>${esc(user.username)}</strong><span>${user.isAdmin ? "管理员" : "普通用户"}</span></div><div class="user-admin-actions">${user.id === state.user.id ? '<span class="current-user-tag">当前账号</span>' : `<button class="secondary-button compact-button" type="button" data-reset-password>设置密码</button><button class="danger-button compact-button" type="button" data-delete-user>删除</button>`}</div></li>`).join("");
}

async function bindUserManager(dialog) {
  const body = dialog.querySelector("[data-user-list]");
  const result = await api("/api/admin/users");
  body.innerHTML = userRowsMarkup(result.users);
  body.querySelectorAll("[data-reset-password]").forEach((button) => {
    button.onclick = () => {
      const row = button.closest("[data-user-id]");
      const userId = Number(row.dataset.userId);
      row.innerHTML = `<form class="user-password-form"><label class="field-label" for="password-${userId}">设置新密码</label><div><input class="text-input" id="password-${userId}" name="password" type="password" minlength="4" maxlength="128" autocomplete="new-password" required><button class="primary-button compact-button" type="submit">保存</button><button class="secondary-button compact-button" type="button" data-cancel-password>取消</button></div></form>`;
      const form = row.querySelector("form");
      form.querySelector("[data-cancel-password]").onclick = () => bindUserManager(dialog);
      form.onsubmit = async (event) => {
        event.preventDefault();
        try {
          await api(`/api/admin/users/${userId}/password`, { method: "PATCH", body: JSON.stringify({ password: form.password.value }) });
          notify("用户密码已更新");
          await bindUserManager(dialog);
        } catch (error) { notify(error.message); }
      };
      form.password.focus();
    };
  });
  body.querySelectorAll("[data-delete-user]").forEach((button) => {
    button.onclick = async (event) => {
      event.stopPropagation();
      const row = button.closest("[data-user-id]");
      const username = row.querySelector(".user-admin-identity strong").textContent;
      if (!await confirmDeletion({ title: "删除用户", name: username, message: "该用户账号及相关数据将被删除，且无法恢复。" })) return;
      button.disabled = true;
      try {
        await api(`/api/admin/users/${row.dataset.userId}`, { method: "DELETE" });
        notify("用户已删除");
        await bindUserManager(dialog);
      } catch (error) { notify(error.message); button.disabled = false; }
    };
  });
}

function voiceEditorMarkup(voice = null) {
  return `<form class="voice-admin-form" data-original-id="${esc(voice?.id || "")}">
    <div class="field"><label>音色名称</label><input class="text-input" name="name" maxlength="40" required value="${esc(voice?.name || "")}" placeholder="例如：沉稳男声"></div>
    <div class="field"><label>speaker_id</label><input class="text-input mono-input" name="id" maxlength="120" required value="${esc(voice?.id || "S_EOMpJ2Da2")}"></div>
    <div class="field"><label>音色描述</label><input class="text-input" name="description" maxlength="120" value="${esc(voice?.description || "")}" placeholder="例如：低沉、克制、适合叙事"></div>
    <div class="field"><label>回复语言</label><select class="select-input" name="language"><option value="zh" ${voice?.language !== "en" ? "selected" : ""}>中文</option><option value="en" ${voice?.language === "en" ? "selected" : ""}>英文</option></select></div>
    <div class="resource-form-actions"><button class="primary-button" type="submit">${voice ? "保存修改" : "添加音色"}</button></div>
  </form>`;
}

async function bindVoiceManager(dialog, selectedId = null) {
  const result = await api("/api/voices");
  state.voices = result.voices;
  const selected = selectedId === "new" ? null : result.voices.find((voice) => voice.id === selectedId) || result.voices[0] || null;
  const controls = dialog.querySelector("[data-voice-controls]");
  controls.innerHTML = `<button class="admin-create-button" type="button" data-new-voice><span aria-hidden="true">＋</span>添加音色</button><div class="field admin-manager-select"><label for="admin-voice-select">预置音色</label><select class="select-input" id="admin-voice-select" data-voice-select ${result.voices.length ? "" : "disabled"}>${result.voices.map((voice) => `<option value="${esc(voice.id)}" ${voice.id === selected?.id ? "selected" : ""}>${esc(voice.name)} · ${esc(voice.description || "暂无声音特点")}</option>`).join("")}</select></div>`;
  const editor = dialog.querySelector("[data-voice-editor]");
  editor.innerHTML = voiceEditorMarkup(selected);
  controls.querySelector("[data-new-voice]").onclick = () => bindVoiceManager(dialog, "new");
  const select = controls.querySelector("[data-voice-select]");
  if (select) select.onchange = () => bindVoiceManager(dialog, select.value);
  const form = editor.querySelector("form");
  form.onsubmit = async (event) => {
    event.preventDefault();
    const originalId = form.dataset.originalId;
    try {
      const response = await api(originalId ? `/api/admin/voices/${encodeURIComponent(originalId)}` : "/api/admin/voices", { method: originalId ? "PATCH" : "POST", body: JSON.stringify(Object.fromEntries(new FormData(form))) });
      notify(originalId ? "音色配置已更新" : "新音色已添加");
      await bindVoiceManager(dialog, response.voice.id);
    } catch (error) { notify(error.message); }
  };
}

function voiceOptions(selectedId) {
  return state.voices.map((voice) => `<option value="${esc(voice.id)}" ${voice.id === selectedId ? "selected" : ""}>${esc(voice.name)} · ${esc(voice.description || "暂无声音特点")}</option>`).join("");
}

function roleEditorMarkup(character = null) {
  return `<form class="role-admin-form" data-character-id="${character?.id || ""}">
    ${avatarFieldMarkup({ currentUrl: character?.avatarUrl || "", id: `admin-avatar-${character?.id || "new"}` })}
    <div class="field-grid"><div class="field"><label>角色名称</label><input class="text-input" name="name" maxlength="40" required value="${esc(character?.name || "")}"></div><div class="field"><label>回复语言</label><select class="select-input" name="language"><option value="zh" ${character?.language !== "en" ? "selected" : ""}>中文</option><option value="en" ${character?.language === "en" ? "selected" : ""}>英文</option></select></div><div class="field field-wide"><label>预置音色</label><select class="select-input" name="voiceId" required>${voiceOptions(character?.voiceId)}</select></div><div class="field field-wide"><label>默认设定</label><textarea class="text-area role-persona-input" name="persona" maxlength="2400" required>${esc(character?.persona || "")}</textarea></div></div>
    <div class="role-form-actions">${character ? '<button class="danger-button" type="button" data-delete-role>删除角色</button>' : "<span></span>"}<button class="primary-button" type="submit">${character ? "保存并同步" : "新增并同步"}</button></div>
  </form>`;
}

async function bindRoleManager(dialog, selectedId = null) {
  const [{ characters }, { voices }] = await Promise.all([api("/api/admin/characters"), api("/api/voices")]);
  state.voices = voices;
  const selected = selectedId === "new" ? null : characters.find((character) => character.id === selectedId) || characters[0] || null;
  const controls = dialog.querySelector("[data-role-controls]");
  controls.innerHTML = `<button class="admin-create-button" type="button" data-new-role><span aria-hidden="true">＋</span>新增角色</button><div class="field admin-manager-select"><label for="admin-role-select">预置角色</label><select class="select-input" id="admin-role-select" data-role-select ${characters.length ? "" : "disabled"}>${characters.map((character) => `<option value="${character.id}" ${character.id === selected?.id ? "selected" : ""}>${esc(character.name)}</option>`).join("")}</select></div>`;
  const editor = dialog.querySelector("[data-role-editor]");
  editor.innerHTML = roleEditorMarkup(selected);
  bindAvatarEditor(editor);
  controls.querySelector("[data-new-role]").onclick = () => bindRoleManager(dialog, "new");
  const select = controls.querySelector("[data-role-select]");
  if (select) select.onchange = () => bindRoleManager(dialog, Number(select.value));
  const form = editor.querySelector("form");
  form.onsubmit = async (event) => {
    event.preventDefault();
    const characterId = form.dataset.characterId;
    try {
      const result = await api(characterId ? `/api/admin/characters/${characterId}` : "/api/admin/characters", { method: characterId ? "PATCH" : "POST", body: JSON.stringify(Object.fromEntries(new FormData(form))) });
      notify(characterId ? "预置角色已更新并同步" : "预置角色已新增并同步");
      await bindRoleManager(dialog, result.character.id);
    } catch (error) { notify(error.message); }
  };
  const deleteButton = form.querySelector("[data-delete-role]");
  if (deleteButton) deleteButton.onclick = async () => {
    if (!await confirmDeletion({ title: "删除预置角色", name: selected.name, message: "该角色会从所有用户联系人中移除，相关对话也会删除。" })) return;
    try {
      await api(`/api/admin/characters/${selected.id}`, { method: "DELETE" });
      notify("预置角色已删除并同步");
      await bindRoleManager(dialog);
    } catch (error) { notify(error.message); }
  };
}

const managerDialogMarkup = (id, title, body, className = "") => `<dialog class="app-dialog admin-manager-dialog ${className}" id="${id}"><div class="dialog-panel"><header class="dialog-header"><h2>${title}</h2><button class="icon-button" type="button" data-dialog-close aria-label="关闭">×</button></header>${body}</div></dialog>`;

export function renderProfile({ bindShell, onLogout }) {
  const adminEntries = state.user.isAdmin ? `<div class="admin-profile-links"><button class="profile-link" id="manage-users"><span><strong>用户管理</strong><small>添加用户、设置密码或删除账号</small></span><span aria-hidden="true">›</span></button><button class="profile-link" id="manage-voices"><span><strong>音色管理</strong><small>维护名称与 speaker_id</small></span><span aria-hidden="true">›</span></button><button class="profile-link" id="manage-roles"><span><strong>角色管理</strong><small>维护全局预置角色与默认设定</small></span><span aria-hidden="true">›</span></button></div>` : "";
  const userDialog = managerDialogMarkup("user-manager-dialog", "用户管理", `<div class="dialog-body"><form class="user-create-form" id="user-create-form"><div class="field"><label for="new-username">新用户账号</label><input class="text-input" id="new-username" name="username" minlength="3" maxlength="24" required autocomplete="off"></div><div class="field"><label for="new-password">初始密码</label><input class="text-input" id="new-password" name="password" type="password" minlength="4" maxlength="128" required autocomplete="new-password"></div><button class="primary-button" type="submit">添加用户</button></form><div class="user-list-head"><span class="field-label">现有用户</span></div><ul class="user-admin-list" data-user-list><li class="history-empty">正在加载用户…</li></ul></div>`, "user-manager-dialog");
  const voiceDialog = managerDialogMarkup("voice-manager-dialog", "音色管理", `<div class="admin-manager-body"><div class="admin-manager-controls" data-voice-controls></div><section class="admin-voice-editor" data-voice-editor></section></div>`, "voice-manager-dialog");
  const roleDialog = managerDialogMarkup("role-manager-dialog", "角色管理", `<div class="admin-manager-body"><div class="admin-manager-controls" data-role-controls></div><section class="admin-role-editor" data-role-editor></section></div>`, "role-manager-dialog");
  app.innerHTML = shell(`<section class="page-heading"><div><h1>我的</h1></div></section><section class="section profile-section"><div class="profile-card">${avatar({ name: state.user.username }, true)}<div><span class="profile-label">${state.user.isAdmin ? "管理员账号" : "当前账号"}</span><h2>${esc(state.user.username)}</h2></div></div>${adminEntries}<button class="danger-button full-width" id="logout">退出当前账号</button></section>${state.user.isAdmin ? userDialog + voiceDialog + roleDialog : ""}`, "profile");
  bindShell();
  if (state.user.isAdmin) {
    const openManager = async (buttonId, dialogId, binder) => {
      const dialog = document.querySelector(dialogId);
      dialog.querySelector("[data-dialog-close]").onclick = () => dialog.close();
      dialog.onclick = (event) => { if (event.target === dialog) dialog.close(); };
      document.querySelector(buttonId).onclick = async () => {
        dialog.showModal();
        try { await binder(dialog); } catch (error) { notify(error.message); dialog.close(); }
      };
    };
    openManager("#manage-users", "#user-manager-dialog", bindUserManager);
    openManager("#manage-voices", "#voice-manager-dialog", bindVoiceManager);
    openManager("#manage-roles", "#role-manager-dialog", bindRoleManager);
    document.querySelector("#user-create-form").onsubmit = async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      try {
        await api("/api/admin/users", { method: "POST", body: JSON.stringify(Object.fromEntries(new FormData(form))) });
        notify("新用户已添加");
        form.reset();
        await bindUserManager(document.querySelector("#user-manager-dialog"));
      } catch (error) { notify(error.message); }
    };
  }
  document.querySelector("#logout").onclick = async () => { await api("/api/auth/logout", { method: "POST" }); state.user = null; onLogout(); };
}