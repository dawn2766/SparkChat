const TARGET_SELECTOR = [
  ".markdown-table-scroll",
  ".markdown-body pre",
  ".character-prompt",
  ".composer .text-area",
].join(",");
const tracked = new WeakMap();
const overlays = new Set();
const resizeObserved = new WeakSet();
const resizeObserver = new ResizeObserver((entries) => {
  entries.forEach(({ target }) => {
    scan(target);
    (tracked.get(target) || []).forEach(updateOverlay);
  });
});

function hasOverflow(element, axis) {
  if (axis === "y" && element.matches(".composer .text-area")) {
    const maxHeight = Number.parseFloat(getComputedStyle(element).maxHeight);
    if (!Number.isFinite(maxHeight) || element.clientHeight < maxHeight - 1) return false;
  }
  return axis === "x"
    ? element.scrollWidth > element.clientWidth + 1
    : element.scrollHeight > element.clientHeight + 2;
}

function trackInset(target, axis) {
  return axis === "y" && target.matches("textarea") ? 8 : 0;
}

function clippingRect(target) {
  const rect = {
    top: 0,
    right: window.innerWidth,
    bottom: window.innerHeight,
    left: 0,
  };
  for (let parent = target.parentElement; parent; parent = parent.parentElement) {
    const style = getComputedStyle(parent);
    if (!/(auto|scroll|overlay|hidden|clip)/.test(`${style.overflowX} ${style.overflowY}`)) continue;
    const parentRect = parent.getBoundingClientRect();
    rect.top = Math.max(rect.top, parentRect.top);
    rect.right = Math.min(rect.right, parentRect.right);
    rect.bottom = Math.min(rect.bottom, parentRect.bottom);
    rect.left = Math.max(rect.left, parentRect.left);
  }
  return rect;
}

function updateOverlay(overlay) {
  const { target, axis, track, thumb } = overlay;
  if (!target.isConnected) {
    track.remove();
    overlays.delete(overlay);
    return;
  }
  if (!hasOverflow(target, axis)) {
    track.hidden = true;
    return;
  }

  const rect = target.getBoundingClientRect();
  const clip = clippingRect(target);
  const horizontal = axis === "x";
  const inset = trackInset(target, axis);
  const trackRect = horizontal
    ? { top: rect.bottom - 8, right: rect.right, bottom: rect.bottom, left: rect.left }
    : { top: rect.top + inset, right: rect.right, bottom: rect.bottom - inset, left: rect.right - 8 };
  if (
    trackRect.bottom <= clip.top || trackRect.top >= clip.bottom
    || trackRect.right <= clip.left || trackRect.left >= clip.right
  ) {
    track.hidden = true;
    return;
  }
  const viewport = horizontal ? target.clientWidth : target.clientHeight;
  const content = horizontal ? target.scrollWidth : target.scrollHeight;
  const scroll = horizontal ? target.scrollLeft : target.scrollTop;
  const trackLength = horizontal ? rect.width : Math.max(0, rect.height - inset * 2);
  const thumbLength = Math.max(28, viewport * trackLength / content);
  const available = Math.max(0, trackLength - thumbLength);
  const maxScroll = content - viewport;
  const offset = available * Math.min(1, Math.max(0, scroll / maxScroll));

  track.hidden = false;
  track.style.left = `${horizontal ? rect.left : rect.right - 8}px`;
  track.style.top = `${horizontal ? rect.bottom - 8 : rect.top + inset}px`;
  track.style.width = `${horizontal ? rect.width : 8}px`;
  track.style.height = `${horizontal ? 8 : Math.max(0, rect.height - inset * 2)}px`;
  thumb.style.width = `${horizontal ? thumbLength : 4}px`;
  thumb.style.height = `${horizontal ? 4 : thumbLength}px`;
  thumb.style.transform = horizontal ? `translateX(${offset}px)` : `translateY(${offset}px)`;
}

function createOverlay(target, axis) {
  const track = document.createElement("div");
  track.className = `global-scrollbar global-scrollbar-${axis}`;
  track.setAttribute("aria-hidden", "true");
  const thumb = document.createElement("span");
  thumb.className = "global-scrollbar-thumb";
  track.append(thumb);
  (target.closest("dialog") || document.body).append(track);

  const overlay = { target, axis, track, thumb };
  const update = () => updateOverlay(overlay);
  target.addEventListener("scroll", update, { passive: true });
  track.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    track.setPointerCapture(event.pointerId);
    const rect = track.getBoundingClientRect();
    const horizontal = axis === "x";
    const viewport = horizontal ? target.clientWidth : target.clientHeight;
    const content = horizontal ? target.scrollWidth : target.scrollHeight;
    const maxScroll = content - viewport;
    const trackLength = horizontal ? rect.width : rect.height;
    const thumbLength = Math.max(28, viewport * trackLength / content);
    const available = Math.max(0, trackLength - thumbLength);
    const pointerPosition = horizontal ? event.clientX : event.clientY;
    const trackStart = horizontal ? rect.left : rect.top;
    const startScroll = horizontal ? target.scrollLeft : target.scrollTop;

    if (event.target !== thumb && available > 0) {
      const nextScroll = Math.min(maxScroll, Math.max(0, (pointerPosition - trackStart - thumbLength / 2) / available * maxScroll));
      if (horizontal) target.scrollLeft = nextScroll;
      else target.scrollTop = nextScroll;
    }

    const drag = (moveEvent) => {
      if (available <= 0) return;
      const position = horizontal ? moveEvent.clientX : moveEvent.clientY;
      const nextScroll = Math.min(maxScroll, Math.max(0, startScroll + (position - pointerPosition) / available * maxScroll));
      if (horizontal) target.scrollLeft = nextScroll;
      else target.scrollTop = nextScroll;
    };
    const stop = () => {
      track.removeEventListener("pointermove", drag);
      track.removeEventListener("pointerup", stop);
      track.removeEventListener("pointercancel", stop);
    };
    track.addEventListener("pointermove", drag);
    track.addEventListener("pointerup", stop);
    track.addEventListener("pointercancel", stop);
  });
  overlays.add(overlay);
  tracked.set(target, (tracked.get(target) || []).concat(overlay));
  requestAnimationFrame(update);
}

function scan(root) {
  const elements = root.matches?.(TARGET_SELECTOR)
    ? [root, ...root.querySelectorAll(TARGET_SELECTOR)]
    : [...root.querySelectorAll(TARGET_SELECTOR)];
  elements.forEach((target) => {
    if (!resizeObserved.has(target)) {
      resizeObserved.add(target);
      resizeObserver.observe(target);
    }
    const axes = new Set((tracked.get(target) || []).map((overlay) => overlay.axis));
    if (!axes.has("x") && hasOverflow(target, "x")) createOverlay(target, "x");
    if (!axes.has("y") && hasOverflow(target, "y")) createOverlay(target, "y");
  });
}

export function initializeGlobalScrollbars(root = document) {
  scan(root);
}

document.addEventListener("input", (event) => {
  if (event.target.matches?.(TARGET_SELECTOR)) scan(event.target);
});

window.addEventListener("resize", () => overlays.forEach(updateOverlay));
window.addEventListener("scroll", () => overlays.forEach(updateOverlay), true);

const observer = new MutationObserver((records) => {
  records.forEach(({ addedNodes }) => addedNodes.forEach((node) => {
    if (node.nodeType === Node.ELEMENT_NODE) scan(node);
  }));
  scan(document);
  overlays.forEach(updateOverlay);
});
observer.observe(document.body, { childList: true, subtree: true });