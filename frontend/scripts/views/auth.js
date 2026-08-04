import { api } from "../api.js";
import { app, esc } from "../dom.js";
import { state } from "../state.js";

export function renderAuth(error = "", onAuthenticated) {
  const isLogin = state.authMode === "login";
  app.innerHTML = `<main class="auth-view"><div class="auth-brand"><i class="brand-mark"></i><span>SPARKCHAT</span></div><div class="auth-content"><div class="auth-heading"><h1>${isLogin ? "登录" : "创建账号"}</h1><p>${isLogin ? "登录后继续你的对话" : "创建账号，开始你的角色体验"}</p></div><form class="auth-form" id="auth-form"><div class="field"><label for="username">账号</label><input class="text-input" id="username" name="username" required autocomplete="username" placeholder="输入账号"></div><div class="field"><label for="password">密码</label><input class="text-input" id="password" name="password" type="password" required autocomplete="${isLogin ? "current-password" : "new-password"}" placeholder="输入密码"></div><p class="auth-error">${esc(error)}</p><button class="primary-button full-width">${isLogin ? "登录" : "创建账号"}</button><button class="auth-switch" id="auth-switch" type="button">${isLogin ? "没有账号？" : "已有账号？"} <strong>${isLogin ? "注册" : "登录"}</strong></button>${isLogin ? '<div class="auth-demo"><span>体验账号</span><code>CaraLin / 2766</code></div>' : ""}</form></div></main>`;

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