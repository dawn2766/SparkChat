import { api } from "../api.js";
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
  dialog.onclick = (event) => {
    if (event.target === dialog) dialog.close();
  };
}

export function renderProfile({ bindShell, onLogout }) {
  const adminEntry = state.user.isAdmin ? '<button class="profile-link" id="manage-users"><span><strong>用户管理</strong><small>添加用户、设置密码或删除账号</small></span><span aria-hidden="true">›</span></button>' : "";
  const managerDialog = state.user.isAdmin ? `<dialog class="app-dialog user-manager-dialog" id="user-manager-dialog"><div class="dialog-panel"><header class="dialog-header"><div><h2>用户管理</h2></div><button class="icon-button" type="button" data-close-users aria-label="关闭">×</button></header><div class="dialog-body"><form class="user-create-form" id="user-create-form"><div class="field"><label for="new-username">新用户账号</label><input class="text-input" id="new-username" name="username" minlength="3" maxlength="24" required autocomplete="off"></div><div class="field"><label for="new-password">初始密码</label><input class="text-input" id="new-password" name="password" type="password" minlength="4" maxlength="128" required autocomplete="new-password"></div><button class="primary-button" type="submit">添加用户</button></form><div class="user-list-head"><span class="field-label">现有用户</span></div><ul class="user-admin-list" data-user-list><li class="history-empty">正在加载用户…</li></ul></div></div></dialog>` : "";
  app.innerHTML = shell(`<section class="page-heading"><div><h1>我的</h1></div></section><section class="section profile-section"><div class="profile-card">${avatar({ name: state.user.username }, true)}<div><span class="profile-label">${state.user.isAdmin ? "管理员账号" : "当前账号"}</span><h2>${esc(state.user.username)}</h2></div></div>${adminEntry}<button class="danger-button full-width" id="logout">退出当前账号</button></section>${managerDialog}`, "profile");
  bindShell();
  if (state.user.isAdmin) {
    const dialog = document.querySelector("#user-manager-dialog");
    document.querySelector("#manage-users").onclick = async () => {
      dialog.showModal();
      try { await bindUserManager(dialog); } catch (error) { notify(error.message); dialog.close(); }
    };
    dialog.querySelector("[data-close-users]").onclick = () => dialog.close();
    dialog.querySelector("#user-create-form").onsubmit = async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      try {
        await api("/api/admin/users", { method: "POST", body: JSON.stringify(Object.fromEntries(new FormData(form))) });
        form.reset();
        notify("新用户已添加");
        await bindUserManager(dialog);
      } catch (error) { notify(error.message); }
    };
  }
  document.querySelector("#logout").onclick = async () => {
    await api("/api/auth/logout", { method: "POST" });
    state.user = null;
    onLogout();
  };
}