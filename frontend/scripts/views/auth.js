import { api } from "../api.js";
import { app, esc } from "../dom.js";
import { state } from "../state.js";

export function renderAuth(error = "", onAuthenticated) {
  const isLogin = state.authMode === "login";
  app.innerHTML = `<main class="auth-view"><section class="auth-content" aria-labelledby="auth-title"><header class="auth-brand"><img src="assets/images/sparkchat-logo.png" alt=""><span>SPARKCHAT</span></header><div class="auth-heading"><h1 id="auth-title">让每个角色，真实可聊</h1><p>${isLogin ? "登录以继续你的对话" : "创建账号，开始新的对话"}</p></div><form class="auth-form" id="auth-form"><div class="field"><label for="username">账号</label><input class="text-input" id="username" name="username" required autocomplete="username" placeholder="输入账号"></div><div class="field"><label for="password">密码</label><input class="text-input" id="password" name="password" type="password" required autocomplete="${isLogin ? "current-password" : "new-password"}" placeholder="输入密码"></div><p class="auth-error" role="alert">${esc(error)}</p><button class="primary-button full-width">${isLogin ? "登录" : "创建账号"}</button><button class="auth-switch" id="auth-switch" type="button">${isLogin ? "还没有账号？" : "已有账号？"} <strong>${isLogin ? "创建账号" : "登录"}</strong></button></form></section></main>`;

  document.querySelector("#auth-switch").onclick = () => {
    state.authMode = isLogin ? "register" : "login";
    renderAuth("", onAuthenticated);
  };
  document.querySelector("#auth-form").onsubmit = async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      const result = await api(`/api/auth/${state.authMode}`, {
        method: "POST",
        body: JSON.stringify({ username: form.get("username"), password: form.get("password") }),
      });
      state.user = result.user;
      await onAuthenticated();
    } catch (submitError) {
      renderAuth(submitError.message, onAuthenticated);
    }
  };
}