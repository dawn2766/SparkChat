import { api } from "./api.js";
import { app } from "./dom.js";
import { state } from "./state.js";
import { renderAuth } from "./views/auth.js";
import { renderCreate } from "./views/create.js";
import { openChat, stopVoiceInteraction } from "./views/chat.js";
import { renderHome } from "./views/home.js";
import { renderProfile } from "./views/profile.js";

async function loadHome() {
  const [characters, voices] = await Promise.all([api("/api/characters"), api("/api/voices")]);
  state.characters = characters.characters;
  state.voices = voices.voices;
  renderHome({ bindShell, openChat: openCharacter });
}

async function openCharacter(id) {
  await openChat(id, loadHome);
}

function bindShell() {
  document.querySelectorAll("[data-tab]").forEach((tab) => {
    tab.onclick = () => {
      stopVoiceInteraction();
      if (tab.dataset.tab === "home") renderHome({ bindShell, openChat: openCharacter });
      if (tab.dataset.tab === "create") renderCreate({ bindShell, onCreated: loadHome });
      if (tab.dataset.tab === "profile") renderProfile({ bindShell, onLogout: () => renderAuth("", loadHome) });
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