import { api } from "./api.js";
import { app } from "./dom.js";
import { state } from "./state.js";
import { renderAuth } from "./views/auth.js";

async function loadHome() {
  const [{ renderHome }, characters, voices] = await Promise.all([
    import("./views/home.js"),
    api("/api/characters"),
    api("/api/voices"),
  ]);
  state.characters = characters.characters;
  state.voices = voices.voices;
  renderHome({ bindShell, openChat: openCharacter });
}

async function loadProfile() {
  const { renderProfile } = await import("./views/profile.js");
  renderProfile({ bindShell, onLogout: () => renderAuth("", loadHome) });
}

async function openCharacter(id) {
  const { openChat } = await import("./views/chat.js");
  await openChat(id, loadHome);
}

function bindShell() {
  document.querySelectorAll("[data-tab]").forEach((tab) => {
    tab.onclick = () => {
      if (tab.dataset.tab === "home") loadHome();
      if (tab.dataset.tab === "create") import("./views/create.js").then(({ renderCreate }) => renderCreate({ bindShell, onCreated: loadHome }));
      if (tab.dataset.tab === "profile") loadProfile();
    };
  });
}

async function boot() {
  try {
    const result = await api("/api/auth/me");
    state.user = result.user;
    if (!state.user) {
      renderAuth("", loadHome);
      return;
    }
    await loadHome();
  } catch (error) {
    renderAuth(error.message, loadHome);
  }
}

app.setAttribute("data-app", "sparkchat");
boot();

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("./service-worker.js").catch((error) => {
      console.warn("Service worker registration failed", error);
    });
  });
}