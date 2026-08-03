import { app, avatar, esc, shell } from "../dom.js";
import { state } from "../state.js";

function formatTime(value) {
  if (!value) return "待连接";
  return new Date(`${value}Z`).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

export function renderHome({ bindShell, openChat }) {
  const rows = state.characters.map((character) => `<button class="contact" data-character="${character.id}">${avatar(character)}<div class="contact-main"><div class="contact-top"><span class="contact-name">${esc(character.name)}</span><span class="contact-time">${formatTime(character.lastMessageAt)}</span></div><div class="contact-preview">${esc(character.lastMessage || "尚未建立对话")}</div></div></button>`).join("");
  app.innerHTML = shell(`<section class="page-heading"><div><h1>联系人</h1></div></section><label class="search-box" for="search"><span aria-hidden="true">⌕</span><input id="search" placeholder="搜索角色或最近消息" autocomplete="off"></label><div class="contact-list">${rows || '<div class="empty-state">暂无角色</div>'}</div>`, "home");
  bindShell();
  document.querySelectorAll("[data-character]").forEach((item) => {
    item.onclick = () => openChat(Number(item.dataset.character));
  });
  document.querySelector("#search").oninput = (event) => {
    const keyword = event.target.value.toLowerCase();
    document.querySelectorAll(".contact").forEach((row) => {
      row.classList.toggle("hidden", !row.textContent.toLowerCase().includes(keyword));
    });
  };
}