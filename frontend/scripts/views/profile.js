import { api } from "../api.js";
import { app, avatar, esc, shell } from "../dom.js";
import { state } from "../state.js";

export function renderProfile({ bindShell, onLogout }) {
  app.innerHTML = shell(`<section class="page-heading"><div><h1>我的</h1></div></section><section class="section profile-section"><div class="profile-card">${avatar({ name: state.user.username }, true)}<div><span class="profile-label">当前账号</span><h2>${esc(state.user.username)}</h2></div></div><button class="danger-button full-width" id="logout">退出当前账号</button></section>`, "profile");
  bindShell();
  document.querySelector("#logout").onclick = async () => {
    await api("/api/auth/logout", { method: "POST" });
    state.user = null;
    onLogout();
  };
}