import { api } from "./api.js";
import { bindCustomSelects } from "./custom-select.js";
import { app } from "./dom.js";
import { state } from "./state.js";
import { renderAuth } from "./views/auth.js";
import { initializeGlobalScrollbars } from "./global-scrollbars.js";

const APP_HISTORY_KEY = "sparkchat";
let currentRoute = { name: "auth" };
let routeTransition = Promise.resolve();
let historyReady = false;
const resizableTextareas = new WeakSet();

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
    if (["file", "hidden"].includes(field.type)) return;
    field.setAttribute("autocomplete", "off");
    field.setAttribute("autocapitalize", "off");
    field.setAttribute("autocorrect", "off");
    field.setAttribute("spellcheck", "false");
    field.setAttribute("data-lpignore", "true");
    field.setAttribute("data-1p-ignore", "true");
    field.setAttribute("data-bwignore", "true");
    field.setAttribute("data-protonpass-ignore", "true");
  });
}

function bindResizableTextareas(root = document) {
  root.querySelectorAll("textarea.character-prompt").forEach((textarea) => {
    if (resizableTextareas.has(textarea)) return;
    resizableTextareas.add(textarea);

    const shell = document.createElement("div");
    shell.className = "textarea-resize-shell";
    textarea.before(shell);
    shell.append(textarea);

    const handle = document.createElement("div");
    handle.className = "textarea-resize-handle";
    handle.setAttribute("aria-hidden", "true");
    shell.append(handle);

    handle.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      const startY = event.clientY;
      const startHeight = textarea.getBoundingClientRect().height;
      const minHeight = Number.parseFloat(getComputedStyle(textarea).minHeight) || 0;
      handle.setPointerCapture(event.pointerId);
      document.body.classList.add("is-resizing-textarea");

      const resize = (moveEvent) => {
        textarea.style.height = `${Math.max(minHeight, startHeight + moveEvent.clientY - startY)}px`;
      };
      const stop = () => {
        handle.removeEventListener("pointermove", resize);
        handle.removeEventListener("pointerup", stop);
        handle.removeEventListener("pointercancel", stop);
        document.body.classList.remove("is-resizing-textarea");
      };

      handle.addEventListener("pointermove", resize);
      handle.addEventListener("pointerup", stop);
      handle.addEventListener("pointercancel", stop);
      handle.addEventListener("lostpointercapture", stop, { once: true });
    });
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
  const { openChat } = await import("./views/chat.js?v=110");
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
  if (currentRoute.name === "chat" && route.name !== "chat") {
    const { stopVoiceInteraction } = await import("./views/chat.js?v=110");
    await stopVoiceInteraction();
  }
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

function bindNativeInteractionGuards() {
  document.addEventListener("contextmenu", (event) => event.preventDefault());
  document.addEventListener("dragstart", (event) => {
    if (event.target instanceof HTMLImageElement) event.preventDefault();
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
bindNativeInteractionGuards();
bindCustomSelects(app);
normalizeSimpleInputs(app);
bindResizableTextareas(app);
new MutationObserver(() => {
  normalizeSimpleInputs(app);
  bindResizableTextareas(app);
}).observe(app, { childList: true, subtree: true });
window.addEventListener("popstate", (event) => {
  if (event.state?.guard) {
    writeHistory(currentRoute);
    return;
  }
  const route = event.state?.[APP_HISTORY_KEY] ? event.state.route : { name: "home" };
  routeTransition = routeTransition.then(() => renderRoute(route)).catch((error) => showAuth(error.message));
});
bindNavigationGestures();
initializeGlobalScrollbars();
boot();

const SERVICE_WORKER_ENABLED = false;

if ("serviceWorker" in navigator) {
  if (SERVICE_WORKER_ENABLED) {
    navigator.serviceWorker.register("./service-worker.js?enabled=1").catch((error) => {
      console.warn("Service worker registration failed", error);
    });
  } else {
    navigator.serviceWorker.getRegistrations()
      .then((registrations) => Promise.all(registrations.map((registration) => registration.unregister())))
      .catch((error) => console.warn("Service worker cleanup failed", error));

    if ("caches" in window) {
      caches.keys()
        .then((keys) => Promise.all(keys.filter((key) => key.startsWith("sparkchat-")).map((key) => caches.delete(key))))
        .catch((error) => console.warn("Service worker cache cleanup failed", error));
    }
  }
}