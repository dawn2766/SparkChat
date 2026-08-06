let openSelect = null;

function closeSelect() {
  if (!openSelect) return;
  openSelect.wrapper.classList.remove("open");
  openSelect.button.setAttribute("aria-expanded", "false");
  openSelect.menu.remove();
  openSelect = null;
}

function selectedLabel(select) {
  return select.selectedOptions[0]?.textContent || "请选择";
}

function positionMenu(wrapper, menu) {
  const rect = wrapper.getBoundingClientRect();
  const edge = 8;
  const availableBelow = window.innerHeight - rect.bottom - edge;
  const availableAbove = rect.top - edge;
  const maxHeight = Math.min(280, Math.max(120, Math.max(availableBelow, availableAbove)));
  const openAbove = availableBelow < Math.min(menu.scrollHeight, maxHeight) && availableAbove > availableBelow;

  menu.style.width = `${rect.width}px`;
  menu.style.maxHeight = `${maxHeight}px`;
  menu.style.left = `${Math.max(edge, Math.min(rect.left, window.innerWidth - rect.width - edge))}px`;
  menu.style.top = openAbove
    ? `${Math.max(edge, rect.top - Math.min(menu.scrollHeight, maxHeight) - 5)}px`
    : `${Math.min(window.innerHeight - edge, rect.bottom + 5)}px`;
}

function nextFrame() {
  return new Promise((resolve) => requestAnimationFrame(resolve));
}

function scrollableAncestors(element) {
  const ancestors = [];
  for (let parent = element.parentElement; parent; parent = parent.parentElement) {
    const overflowY = getComputedStyle(parent).overflowY;
    if (/(auto|scroll|overlay)/.test(overflowY) && parent.scrollHeight > parent.clientHeight) ancestors.push(parent);
  }
  return ancestors;
}

async function revealControl(wrapper) {
  const margin = 12;
  for (const ancestor of scrollableAncestors(wrapper)) {
    const controlRect = wrapper.getBoundingClientRect();
    const ancestorRect = ancestor.getBoundingClientRect();
    const visibleTop = ancestorRect.top + margin;
    const visibleBottom = ancestorRect.bottom - margin;
    if (controlRect.top < visibleTop) ancestor.scrollTop -= visibleTop - controlRect.top;
    else if (controlRect.bottom > visibleBottom) ancestor.scrollTop += controlRect.bottom - visibleBottom;
    await nextFrame();
  }

  const controlRect = wrapper.getBoundingClientRect();
  if (controlRect.top < margin) window.scrollBy({ top: controlRect.top - margin });
  else if (controlRect.bottom > window.innerHeight - margin) {
    window.scrollBy({ top: controlRect.bottom - window.innerHeight + margin });
  }
  await nextFrame();
}

async function openMenu(select, wrapper, button) {
  if (openSelect?.select === select) {
    closeSelect();
    return;
  }
  await revealControl(wrapper);
  const controlRect = wrapper.getBoundingClientRect();
  if (!controlRect.width || !controlRect.height || button.disabled) return;
  closeSelect();

  const menu = document.createElement("div");
  menu.className = "select-menu";
  if (select.dataset.menuClass) menu.classList.add(select.dataset.menuClass);
  menu.id = `${select.id || wrapper.dataset.selectId}-menu`;
  menu.setAttribute("role", "listbox");

  [...select.options].forEach((option, index) => {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "select-option";
    item.dataset.value = option.value;
    item.setAttribute("role", "option");
    item.setAttribute("aria-selected", String(option.selected));
    item.disabled = option.disabled;
    item.textContent = option.textContent;
    const chooseOption = () => {
      if (item.disabled) return;
      select.selectedIndex = index;
      button.querySelector(".select-value").textContent = selectedLabel(select);
      select.dispatchEvent(new Event("change", { bubbles: true }));
      closeSelect();
      button.focus();
    };
    item.onclick = chooseOption;
    menu.append(item);
  });

  (wrapper.closest("dialog") || document.body).append(menu);
  wrapper.classList.add("open");
  button.setAttribute("aria-expanded", "true");
  positionMenu(wrapper, menu);
  openSelect = { select, wrapper, button, menu };
  menu.querySelector('[aria-selected="true"]:not(:disabled)')?.focus();
}

function enhanceSelect(select) {
  if (select.dataset.enhancedSelect !== undefined) return;
  select.dataset.enhancedSelect = "";
  select.tabIndex = -1;
  select.setAttribute("aria-hidden", "true");

  const wrapper = document.createElement("div");
  wrapper.className = "select-control";
  wrapper.dataset.selectId = Math.random().toString(36).slice(2);
  select.before(wrapper);
  wrapper.append(select);

  const button = document.createElement("button");
  button.type = "button";
  button.className = "select-trigger";
  button.disabled = select.disabled;
  button.setAttribute("aria-haspopup", "listbox");
  button.setAttribute("aria-expanded", "false");
  button.innerHTML = `<span class="select-value"></span><span class="select-chevron" aria-hidden="true"></span>`;
  button.querySelector(".select-value").textContent = selectedLabel(select);
  button.onclick = () => { void openMenu(select, wrapper, button); };
  button.onkeydown = (event) => {
    if (["ArrowDown", "ArrowUp", "Enter", " "].includes(event.key)) {
      event.preventDefault();
      void openMenu(select, wrapper, button);
    }
  };
  wrapper.append(button);

  const sync = () => {
    button.disabled = select.disabled;
    button.querySelector(".select-value").textContent = selectedLabel(select);
  };
  select.addEventListener("change", sync);
  select.form?.addEventListener("reset", () => requestAnimationFrame(sync));
  new MutationObserver(sync).observe(select, {
    attributes: true,
    attributeFilter: ["disabled"],
    childList: true,
    subtree: true,
  });
}

export function bindCustomSelects(root) {
  root.querySelectorAll("select.select-input").forEach(enhanceSelect);
  const observer = new MutationObserver(() => {
    root.querySelectorAll("select.select-input").forEach(enhanceSelect);
    if (openSelect && !openSelect.select.isConnected) closeSelect();
  });
  observer.observe(root, { childList: true, subtree: true });

  document.addEventListener("pointerdown", (event) => {
    if (!event.target.closest(".select-control, .select-menu")) closeSelect();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      const button = openSelect?.button;
      closeSelect();
      button?.focus();
      return;
    }
    if (!openSelect || !["ArrowDown", "ArrowUp"].includes(event.key)) return;
    const options = [...openSelect.menu.querySelectorAll(".select-option:not(:disabled)")];
    const current = options.indexOf(document.activeElement);
    const direction = event.key === "ArrowDown" ? 1 : -1;
    options[(current + direction + options.length) % options.length]?.focus();
    event.preventDefault();
  });
  window.addEventListener("resize", closeSelect);
  window.addEventListener("scroll", () => {
    if (openSelect) positionMenu(openSelect.wrapper, openSelect.menu);
  }, true);
}