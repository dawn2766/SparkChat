export const app = document.querySelector("#app");
export const toast = document.querySelector("#toast");

export const esc = (value) => String(value ?? "").replace(/[&<>\"]/g, (char) => ({
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
}[char]));

export function notify(text) {
  toast.textContent = text;
  toast.classList.remove("hidden");
  window.clearTimeout(notify.timer);
  notify.timer = window.setTimeout(() => toast.classList.add("hidden"), 2600);
}

export function avatar(character, small = false) {
  const name = character?.name || "?";
  return `<div class="avatar ${name === "威震天" ? "megatron" : ""} ${small ? "small" : ""}">${esc(name.slice(0, 1))}</div>`;
}

export function shell(content, active = "home") {
  return `<main class="view">${content}</main><nav class="bottom-nav"><button class="nav-item ${active === "home" ? "active" : ""}" data-tab="home"><span class="nav-icon">⌂</span>联系人</button><button class="nav-item ${active === "create" ? "active" : ""}" data-tab="create"><span class="nav-icon">＋</span>新建角色</button><button class="nav-item ${active === "profile" ? "active" : ""}" data-tab="profile"><span class="nav-icon">◉</span>我的</button></nav>`;
}

export function scrollMessages() {
  const node = document.querySelector("#messages");
  if (node) node.scrollTop = node.scrollHeight;
}