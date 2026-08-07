import { createIcons, Eye, EyeOff } from "https://cdn.jsdelivr.net/npm/lucide@0.468.0/+esm";
import { api } from "../api.js";
import { app, esc } from "../dom.js";
import { state } from "../state.js";

const AUTH_RULES = {
  username: { min: 3, max: 24 },
  password: { min: 4, max: 128 },
};

export function validateAuthForm(username, password, isLogin) {
  const errors = {};
  if (!username) errors.username = "请输入账号";
  else if (username.length > AUTH_RULES.username.max) errors.username = "账号不能超过 24 个字符";
  else if (!isLogin && username.length < AUTH_RULES.username.min) errors.username = "账号至少需要 3 个字符";

  if (!password) errors.password = "请输入密码";
  else if (password.length > AUTH_RULES.password.max) errors.password = "密码不能超过 128 个字符";
  else if (!isLogin && password.length < AUTH_RULES.password.min) errors.password = "密码至少需要 4 个字符";
  return errors;
}

export function renderAuth(error = "", onAuthenticated) {
  const isLogin = state.authMode === "login";
  const submitLabel = isLogin ? "登录" : "创建账号";
  const submittingLabel = isLogin ? "正在登录…" : "正在创建…";
  app.innerHTML = `<main class="auth-view"><section class="auth-content"><header class="auth-brand"><img src="assets/images/sparkchat-logo.png" alt=""><span>SPARKCHAT</span></header><div class="auth-heading"><h1>${isLogin ? "欢迎回来" : "创建你的账号"}</h1><p>${isLogin ? "登录以继续你的对话" : "一个账号，保存你的角色与对话"}</p></div><form class="auth-form" id="auth-form" novalidate><div class="field"><label for="username">账号</label><input class="text-input" id="username" name="username" required minlength="${isLogin ? 1 : AUTH_RULES.username.min}" maxlength="${AUTH_RULES.username.max}" autocomplete="username" autocapitalize="none" spellcheck="false" placeholder="${isLogin ? "输入你的账号" : "3–24 个字符"}" aria-describedby="username-error"><p class="field-error" id="username-error"></p></div><div class="field"><label for="password">密码</label><div class="password-control"><input class="text-input" id="password" name="password" type="password" required minlength="${isLogin ? 1 : AUTH_RULES.password.min}" maxlength="${AUTH_RULES.password.max}" autocomplete="${isLogin ? "current-password" : "new-password"}" placeholder="${isLogin ? "输入你的密码" : "至少 4 个字符"}" aria-describedby="password-error"><button class="icon-button password-toggle" id="password-toggle" type="button" aria-label="显示密码" aria-pressed="false"><i data-lucide="eye" aria-hidden="true"></i></button></div><p class="field-error" id="password-error"></p></div><div class="auth-message${error ? " is-visible" : ""}" id="auth-message" role="alert" aria-live="polite">${esc(error)}</div><button class="primary-button full-width auth-submit" id="auth-submit">${submitLabel}</button><div class="auth-divider"><span>或</span></div><button class="auth-switch" id="auth-switch" type="button">${isLogin ? "还没有账号？" : "已有账号？"} <strong>${isLogin ? "创建账号" : "直接登录"}</strong></button></form></section><footer class="auth-footer"><a href="http://beian.miit.gov.cn/" target="_blank" rel="noopener noreferrer">闽ICP备2024055854号</a></footer></main>`;

  const formElement = document.querySelector("#auth-form");
  const submitButton = document.querySelector("#auth-submit");
  const messageElement = document.querySelector("#auth-message");
  const passwordToggle = document.querySelector("#password-toggle");
  const fields = {
    username: document.querySelector("#username"),
    password: document.querySelector("#password"),
  };

  const setFieldError = (name, message = "") => {
    const input = fields[name];
    const errorElement = document.querySelector(`#${name}-error`);
    input.setAttribute("aria-invalid", String(Boolean(message)));
    errorElement.textContent = message;
  };

  const setFormMessage = (message = "") => {
    messageElement.textContent = message;
    messageElement.classList.toggle("is-visible", Boolean(message));
  };

  createIcons({ icons: { Eye, EyeOff } });

  Object.entries(fields).forEach(([name, input]) => {
    input.addEventListener("input", () => {
      setFieldError(name);
      setFormMessage();
    });
  });

  passwordToggle.onclick = (event) => {
    const showPassword = fields.password.type === "password";
    fields.password.type = showPassword ? "text" : "password";
    event.currentTarget.setAttribute("aria-label", showPassword ? "隐藏密码" : "显示密码");
    event.currentTarget.setAttribute("aria-pressed", String(showPassword));
    event.currentTarget.innerHTML = `<i data-lucide="${showPassword ? "eye-off" : "eye"}" aria-hidden="true"></i>`;
    createIcons({ icons: { Eye, EyeOff } });
    fields.password.focus({ preventScroll: true });
  };

  document.querySelector("#auth-switch").onclick = () => {
    state.authMode = isLogin ? "register" : "login";
    renderAuth("", onAuthenticated);
  };
  formElement.onsubmit = async (event) => {
    event.preventDefault();
    const formData = new FormData(formElement);
    const username = String(formData.get("username") || "").trim();
    const password = String(formData.get("password") || "");
    const errors = validateAuthForm(username, password, isLogin);
    Object.keys(fields).forEach((name) => setFieldError(name, errors[name]));
    if (Object.keys(errors).length) {
      fields[Object.keys(errors)[0]].focus();
      return;
    }

    submitButton.disabled = true;
    submitButton.textContent = submittingLabel;
    setFormMessage();
    try {
      const result = await api(`/api/auth/${state.authMode}`, {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      state.user = result.user;
      await onAuthenticated();
    } catch (submitError) {
      setFormMessage(submitError.message || "暂时无法连接，请稍后重试");
      fields[submitError.message === "该账号已存在" ? "username" : "password"].focus();
    } finally {
      submitButton.disabled = false;
      submitButton.textContent = submitLabel;
    }
  };
}