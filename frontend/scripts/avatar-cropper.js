import { esc, notify } from "./dom.js";

const CROP_SIZE = 180;
const OUTPUT_SIZE = 512;

export function avatarFieldMarkup({ currentUrl = "", id = "avatar" } = {}) {
  const image = currentUrl ? `<img src="${esc(currentUrl)}" alt="">` : '<span class="avatar-placeholder">+</span>';
  return `<section class="avatar-field" data-avatar-editor="${id}">
    <input type="hidden" name="avatarUrl" value="${esc(currentUrl)}">
    <input class="avatar-file-input" id="${id}-file" type="file" accept="image/*" hidden>
    <div class="avatar-field-preview" data-avatar-preview>${image}</div>
    <div class="avatar-field-copy"><strong>角色头像</strong><span>支持常见图片格式，上传前会自动压缩</span></div>
    <label class="secondary-button avatar-choose" for="${id}-file">${currentUrl ? "更换" : "选择图片"}</label>
  </section>
  <dialog class="app-dialog crop-dialog" data-crop-dialog>
    <div class="dialog-panel">
      <header class="dialog-header"><h2>裁切角色头像</h2></header>
      <div class="dialog-body crop-dialog-body">
        <div class="crop-stage" data-crop-stage>
          <img data-crop-image alt="待裁切头像">
          <div class="crop-box" data-crop-box><i></i><i></i><i></i><i></i></div>
        </div>
      </div>
      <footer class="dialog-actions"><button type="button" class="secondary-button" data-crop-cancel>取消</button><button type="button" class="primary-button" data-crop-save>使用头像</button></footer>
    </div>
  </dialog>`;
}

export function bindAvatarEditor(root) {
  const editor = root.querySelector("[data-avatar-editor]");
  if (!editor) return;
  const input = editor.querySelector("[name=avatarUrl]");
  const fileInput = editor.querySelector(".avatar-file-input");
  const preview = editor.querySelector("[data-avatar-preview]");
  const chooseLabel = editor.querySelector(".avatar-choose");
  const dialog = root.querySelector("[data-crop-dialog]");
  const stage = dialog.querySelector("[data-crop-stage]");
  const cropImage = dialog.querySelector("[data-crop-image]");
  const cropBox = dialog.querySelector("[data-crop-box]");
  const sourceImage = new Image();
  let objectUrl = "";
  let baseScale = 1;
  let zoom = 1;
  let imageLeft = 0;
  let imageTop = 0;
  const pointers = new Map();
  let dragStart = null;
  let pinchStart = null;

  const renderPreview = (value) => {
    input.value = value || "";
    preview.innerHTML = value ? `<img src="${esc(value)}" alt="">` : '<span class="avatar-placeholder">+</span>';
    chooseLabel.textContent = value ? "更换" : "选择图片";
  };

  editor.resetAvatar = (value = "") => renderPreview(value);

  const geometry = () => {
    const width = sourceImage.naturalWidth * baseScale * zoom;
    const height = sourceImage.naturalHeight * baseScale * zoom;
    return { width, height, left: imageLeft, top: imageTop };
  };

  const cropPosition = () => ({
    left: (stage.clientWidth - CROP_SIZE) / 2,
    top: (stage.clientHeight - CROP_SIZE) / 2,
  });

  const constrainImage = () => {
    const image = geometry();
    const crop = cropPosition();
    imageLeft = Math.min(crop.left, Math.max(crop.left + CROP_SIZE - image.width, imageLeft));
    imageTop = Math.min(crop.top, Math.max(crop.top + CROP_SIZE - image.height, imageTop));
  };

  const renderCrop = () => {
    constrainImage();
    const image = geometry();
    const crop = cropPosition();
    Object.assign(cropImage.style, { width: `${image.width}px`, height: `${image.height}px`, left: `${image.left}px`, top: `${image.top}px` });
    Object.assign(cropBox.style, { left: `${crop.left}px`, top: `${crop.top}px` });
  };

  const openCropper = () => {
    const stageSize = stage.clientWidth;
    baseScale = Math.max(CROP_SIZE / sourceImage.naturalWidth, CROP_SIZE / sourceImage.naturalHeight);
    const stageScale = Math.min(stageSize / sourceImage.naturalWidth, stageSize / sourceImage.naturalHeight);
    zoom = Math.max(1, stageScale / baseScale);
    const imageWidth = sourceImage.naturalWidth * baseScale * zoom;
    const imageHeight = sourceImage.naturalHeight * baseScale * zoom;
    imageLeft = (stage.clientWidth - imageWidth) / 2;
    imageTop = (stage.clientHeight - imageHeight) / 2;
    cropImage.src = objectUrl;
    renderCrop();
  };

  const closeCropper = () => {
    dialog.close();
    fileInput.value = "";
  };

  fileInput.onchange = () => {
    const file = fileInput.files[0];
    if (!file) return;
    if (file.type && !file.type.startsWith("image/")) {
      notify("请选择图片文件");
      fileInput.value = "";
      return;
    }
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = URL.createObjectURL(file);
    sourceImage.onload = () => {
      dialog.showModal();
      requestAnimationFrame(openCropper);
    };
    sourceImage.onerror = () => notify("图片无法读取，请换一张重试");
    sourceImage.src = objectUrl;
  };
  fileInput.oncancel = (event) => event.stopPropagation();

  stage.onwheel = (event) => {
    event.preventDefault();
    const oldImage = geometry();
    const crop = cropPosition();
    const focusX = crop.left + CROP_SIZE / 2;
    const focusY = crop.top + CROP_SIZE / 2;
    const sourceX = (focusX - oldImage.left) / oldImage.width;
    const sourceY = (focusY - oldImage.top) / oldImage.height;
    zoom = Math.min(4, Math.max(1, zoom * (event.deltaY < 0 ? 1.1 : 0.9)));
    const nextWidth = sourceImage.naturalWidth * baseScale * zoom;
    const nextHeight = sourceImage.naturalHeight * baseScale * zoom;
    imageLeft = focusX - sourceX * nextWidth;
    imageTop = focusY - sourceY * nextHeight;
    renderCrop();
  };

  const pointerDistance = (first, second) => Math.hypot(second.clientX - first.clientX, second.clientY - first.clientY);
  const pointerMidpoint = (first, second) => {
    const bounds = stage.getBoundingClientRect();
    return {
      x: (first.clientX + second.clientX) / 2 - bounds.left,
      y: (first.clientY + second.clientY) / 2 - bounds.top,
    };
  };

  const beginPinch = () => {
    const [first, second] = pointers.values();
    const midpoint = pointerMidpoint(first, second);
    const image = geometry();
    pinchStart = {
      distance: Math.max(pointerDistance(first, second), 1),
      midpoint,
      zoom,
      sourceX: (midpoint.x - image.left) / image.width,
      sourceY: (midpoint.y - image.top) / image.height,
    };
    dragStart = null;
    stage.classList.add("dragging");
  };

  const updatePinch = () => {
    if (pointers.size < 2 || !pinchStart) return;
    const [first, second] = pointers.values();
    const midpoint = pointerMidpoint(first, second);
    const distance = pointerDistance(first, second);
    zoom = Math.min(4, Math.max(1, pinchStart.zoom * distance / pinchStart.distance));
    const nextWidth = sourceImage.naturalWidth * baseScale * zoom;
    const nextHeight = sourceImage.naturalHeight * baseScale * zoom;
    imageLeft = midpoint.x - pinchStart.sourceX * nextWidth;
    imageTop = midpoint.y - pinchStart.sourceY * nextHeight;
    renderCrop();
  };

  dialog.querySelector("[data-crop-cancel]").onclick = closeCropper;
  dialog.oncancel = (event) => { event.preventDefault(); closeCropper(); };
  dialog.onclick = (event) => { if (event.target === dialog) closeCropper(); };

  stage.onpointerdown = (event) => {
    event.preventDefault();
    pointers.set(event.pointerId, event);
    stage.setPointerCapture(event.pointerId);
    if (pointers.size === 2) beginPinch();
    if (pointers.size === 1) {
      dragStart = { imageLeft, imageTop, clientX: event.clientX, clientY: event.clientY };
      stage.classList.add("dragging");
    }
  };

  stage.onpointermove = (event) => {
    if (!pointers.has(event.pointerId)) return;
    event.preventDefault();
    pointers.set(event.pointerId, event);
    if (pointers.size >= 2) {
      updatePinch();
      return;
    }
    if (dragStart) {
      imageLeft = dragStart.imageLeft + event.clientX - dragStart.clientX;
      imageTop = dragStart.imageTop + event.clientY - dragStart.clientY;
      renderCrop();
    }
  };

  const stopPointer = (event) => {
    pointers.delete(event.pointerId);
    if (pointers.size === 1) {
      const remaining = pointers.values().next().value;
      dragStart = { imageLeft, imageTop, clientX: remaining.clientX, clientY: remaining.clientY };
      pinchStart = null;
      return;
    }
    if (pointers.size === 0) {
      dragStart = null;
      pinchStart = null;
      stage.classList.remove("dragging");
    }
  };

  stage.onpointerup = stopPointer;
  stage.onpointercancel = stopPointer;

  dialog.querySelector("[data-crop-save]").onclick = () => {
    const image = geometry();
    const crop = cropPosition();
    const canvas = document.createElement("canvas");
    canvas.width = OUTPUT_SIZE;
    canvas.height = OUTPUT_SIZE;
    const sourceX = (crop.left - image.left) / image.width * sourceImage.naturalWidth;
    const sourceY = (crop.top - image.top) / image.height * sourceImage.naturalHeight;
    const sourceWidth = CROP_SIZE / image.width * sourceImage.naturalWidth;
    const sourceHeight = CROP_SIZE / image.height * sourceImage.naturalHeight;
    canvas.getContext("2d").drawImage(sourceImage, sourceX, sourceY, sourceWidth, sourceHeight, 0, 0, OUTPUT_SIZE, OUTPUT_SIZE);
    renderPreview(canvas.toDataURL("image/jpeg", 0.84));
    closeCropper();
  };

}