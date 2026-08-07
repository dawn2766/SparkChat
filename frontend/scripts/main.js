import { api } from "./api.js";
import { bindCustomSelects } from "./custom-select.js";
import { app } from "./dom.js";
import { state } from "./state.js";
import { renderAuth } from "./views/auth.js";

const APP_HISTORY_KEY = "sparkchat";
let currentRoute = { name: "auth" };
let routeTransition = Promise.resolve();
let historyReady = false;

function writeHistory(route, mode = "push") {
  const method = mode === "replace" ? "replaceState" : "pushState";
  window.history[method]({ [APP_HISTORY_KEY]: true, route }, "");
}

function initializeHistory(route) {
  if (historyReady) {
    writeHistory(route, "replace");
    return;
  }
  window.history.replaceState({ [APP_HISTORY_KEY]: true, route, guard: true }, "");
  writeHistory(route);
  historyReady = true;
}

function normalizeSimpleInputs(root = document) {
  root.querySelectorAll("input, textarea").forEach((field) => {
    if (field.closest(".auth-form") || ["file", "hidden"].includes(field.type)) return;
    field.setAttribute("autocomplete", "off");
    field.setAttribute("autocapitalize", "off");
    field.setAttribute("autocorrect", "off");
    field.setAttribute("spellcheck", "false");
    field.setAttribute("data-lpignore", "true");
    field.setAttribute("data-1p-ignore", "true");
  });
}

async function loadHome(historyMode = "push") {
  const [{ renderHome }, characters, voices] = await Promise.all([
    import("./views/home.js"),
    api("/api/characters"),
    api("/api/voices"),
  ]);
  state.characters = characters.characters.map((character) => {
    const conversation = state.selectedConversations?.[character.id];
    return conversation ? {
      ...character,
      lastMessage: conversation.lastMessage || "",
      lastMessageAt: conversation.updatedAt || null,
    } : character;
  });
  state.voices = voices.voices;
  renderHome({ bindShell, openChat: openCharacter });
  currentRoute = { name: "home" };
  if (historyMode) writeHistory(currentRoute, historyMode);
}

async function loadProfile(historyMode = "push") {
  const { renderProfile } = await import("./views/profile.js");
  renderProfile({ bindShell, onLogout: () => showAuth("", "replace") });
  currentRoute = { name: "profile" };
  if (historyMode) writeHistory(currentRoute, historyMode);
}

async function openCharacter(id, historyMode = "push") {
  const { openChat } = await import("./views/chat.js");
  await openChat(id, goBack);
  currentRoute = { name: "chat", id };
  if (historyMode) writeHistory(currentRoute, historyMode);
}

async function loadCreate(historyMode = "push") {
  const { renderCreate } = await import("./views/create.js");
  renderCreate({ bindShell, onCreated: () => loadHome("replace") });
  currentRoute = { name: "create" };
  if (historyMode) writeHistory(currentRoute, historyMode);
}

function showAuth(error = "", historyMode = "replace") {
  renderAuth(error, () => loadHome("replace"));
  currentRoute = { name: "auth" };
  if (historyMode) writeHistory(currentRoute, historyMode);
}

async function renderRoute(route) {
  if (!state.user || route.name === "auth") {
    showAuth("", null);
    return;
  }
  if (route.name === "chat" && route.id) return openCharacter(route.id, null);
  if (route.name === "create") return loadCreate(null);
  if (route.name === "profile") return loadProfile(null);
  return loadHome(null);
}

function goBack() {
  const dialog = document.querySelector("dialog[open]");
  if (dialog) {
    dialog.close();
    return;
  }
  if (currentRoute.name === "home" || currentRoute.name === "auth") return;
  window.history.back();
}

function bindShell() {
  document.querySelectorAll("[data-tab]").forEach((tab) => {
    tab.onclick = () => {
      if (tab.dataset.tab === "home") loadHome();
      if (tab.dataset.tab === "create") loadCreate();
      if (tab.dataset.tab === "profile") loadProfile();
    };
  });
}

function bindNavigationGestures() {
  const edgeWidth = 28;
  const triggerDistance = 72;
  let gesture = null;

  document.addEventListener("touchstart", (event) => {
    if (event.touches.length !== 1 || currentRoute.name === "home" || currentRoute.name === "auth") return;
    const touch = event.touches[0];
    const fromLeft = touch.clientX <= edgeWidth;
    const fromRight = touch.clientX >= window.innerWidth - edgeWidth;
    if (fromLeft || fromRight) gesture = { x: touch.clientX, y: touch.clientY, direction: fromLeft ? 1 : -1 };
  }, { passive: true });

  document.addEventListener("touchmove", (event) => {
    if (!gesture || event.touches.length !== 1) return;
    const touch = event.touches[0];
    const deltaX = (touch.clientX - gesture.x) * gesture.direction;
    const deltaY = Math.abs(touch.clientY - gesture.y);
    if (deltaY > Math.max(20, deltaX)) {
      gesture = null;
      return;
    }
    if (deltaX > 10) event.preventDefault();
  }, { passive: false });

  document.addEventListener("touchend", (event) => {
    if (!gesture) return;
    const touch = event.changedTouches[0];
    const deltaX = (touch.clientX - gesture.x) * gesture.direction;
    const deltaY = Math.abs(touch.clientY - gesture.y);
    gesture = null;
    if (deltaX >= triggerDistance && deltaX > deltaY * 1.25) goBack();
  }, { passive: true });

  document.addEventListener("touchcancel", () => { gesture = null; }, { passive: true });
}

async function boot() {
  try {
    const result = await api("/api/auth/me");
    state.user = result.user;
    if (!state.user) {
      showAuth("", null);
      initializeHistory(currentRoute);
      return;
    }
    await loadHome(null);
    initializeHistory(currentRoute);
  } catch (error) {
    showAuth(error.message, null);
    initializeHistory(currentRoute);
  }
}

app.setAttribute("data-app", "sparkchat");
bindCustomSelects(app);
normalizeSimpleInputs(app);
new MutationObserver(() => normalizeSimpleInputs(app)).observe(app, { childList: true, subtree: true });
window.addEventListener("popstate", (event) => {
  if (event.state?.guard) {
    writeHistory(currentRoute);
    return;
  }
  const route = event.state?.[APP_HISTORY_KEY] ? event.state.route : { name: "home" };
  routeTransition = routeTransition.then(() => renderRoute(route)).catch((error) => showAuth(error.message));
});
bindNavigationGestures();
boot();

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("./service-worker.js").catch((error) => {
    console.warn("Service worker registration failed", error);
  });
}