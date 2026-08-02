import { api } from "../api.js";
import { app, esc } from "../dom.js";
import { state } from "../state.js";

export function renderAuth(error = "", onAuthenticated) {
  const isLogin = state.authMode === "login";
  app.innerHTML = `<main class="auth-view"><div class="auth-brand"><i class="brand-mark"></i><span>SPARKCHAT</span></div><div class="auth-content"><div class="eyebrow">Character communication system</div><h1>与你的<br><span>数字角色</span>持续连接。</h1><p class="auth-copy">创建具有人设与独立音色的角色，在文字与实时语音之间自然切换。</p><form class="auth-form" id="auth-form"><div class="field"><div class="field-head"><label for="username">账号</label><span class="field-note">3 - 24 字符</span></div><input class="text-input" id="username" name="username" required autocomplete="username" placeholder="输入账号"></div><div class="field"><div class="field-head"><label for="password">密码</label><span class="field-note">至少 4 字符</span></div><input class="text-input" id="password" name="password" type="password" required autocomplete="${isLogin ? "current-password" : "new-password"}" placeholder="输入密码"></div><p class="auth-error">${esc(error)}</p><button class="primary-button full-width">${isLogin ? "进入 SparkChat" : "创建账号并进入"}</button><button class="auth-switch" id="auth-switch" type="button">${isLogin ? "还没有账号？" : "已有账号？"} <strong>${isLogin ? "立即注册" : "返回登录"}</strong></button><p class="auth-demo">体验账号 CaraLin / 2766</p></form></div><div class="auth-footer">Private character network / v1.0</div></main>`;

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