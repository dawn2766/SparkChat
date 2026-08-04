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

export function confirmDeletion({ title = "确认删除", name, message = "删除后将无法恢复。" }) {
  const dialog = document.createElement("dialog");
  dialog.className = "app-dialog confirm-dialog";
  dialog.innerHTML = `<form method="dialog" class="dialog-panel"><header class="dialog-header"><h2>${esc(title)}</h2><button class="icon-button" type="submit" value="cancel" aria-label="关闭确认弹窗">×</button></header><div class="dialog-body"><p class="confirm-dialog-message">确定要删除“<strong>${esc(name)}</strong>”吗？${esc(message)}</p></div><footer class="dialog-actions"><button class="secondary-button" type="submit" value="cancel">取消</button><button class="danger-button" type="submit" value="confirm">确认删除</button></footer></form>`;
  document.body.append(dialog);
  dialog.showModal();
  dialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    dialog.close("cancel");
  });
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close("cancel");
  });
  return new Promise((resolve) => {
    dialog.addEventListener("close", () => {
      resolve(dialog.returnValue === "confirm");
      dialog.remove();
    }, { once: true });
  });
}

export function avatar(character, small = false) {
  const name = character?.name || "?";
  const image = character?.avatarUrl ? `<img src="${esc(character.avatarUrl)}" alt="">` : esc(name.slice(0, 1));
  return `<div class="avatar ${!character?.avatarUrl && name === "威震天" ? "megatron" : ""} ${small ? "small" : ""}">${image}</div>`;
}

export function shell(content, active = "home") {
  return `<main class="view">${content}</main><nav class="bottom-nav"><button class="nav-item ${active === "home" ? "active" : ""}" data-tab="home"><span class="nav-icon">⌂</span>联系人</button><button class="nav-item ${active === "create" ? "active" : ""}" data-tab="create"><span class="nav-icon">＋</span>新建角色</button><button class="nav-item ${active === "profile" ? "active" : ""}" data-tab="profile"><span class="nav-icon">◉</span>我的</button></nav>`;
}

export function scrollMessages() {
  const node = document.querySelector("#messages");
  if (node) node.scrollTop = node.scrollHeight;
}