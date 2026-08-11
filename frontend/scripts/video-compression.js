const SOURCE_FILE_MAX_BYTES = 2 * 1024 * 1024 * 1024;
const UPLOAD_FILE_MAX_BYTES = 512 * 1024 * 1024;
const COMPRESSION_SIZE_THRESHOLD = 80 * 1024 * 1024;
const MAX_VIDEO_EDGE = 1280;
const MAX_SOURCE_FPS = 30;
const OUTPUT_FPS = 24;
const OUTPUT_VIDEO_BITS_PER_SECOND = 3_000_000;
const OUTPUT_BUDGET_BYTES = 480 * 1024 * 1024;

function throwIfAborted(signal) {
  if (signal?.aborted) throw signal.reason || new DOMException("操作已取消", "AbortError");
}

function compressionProfile() {
  return {
    maxEdge: MAX_VIDEO_EDGE,
    outputFps: OUTPUT_FPS,
    videoBitsPerSecond: OUTPUT_VIDEO_BITS_PER_SECOND,
    sourceFileMaxBytes: SOURCE_FILE_MAX_BYTES,
    outputBudgetBytes: OUTPUT_BUDGET_BYTES,
  };
}

function supportedMp4MimeType() {
  if (typeof MediaRecorder === "undefined" || typeof MediaRecorder.isTypeSupported !== "function") return "";
  return ["video/mp4;codecs=avc1.42E01E", "video/mp4"].find((type) => MediaRecorder.isTypeSupported(type)) || "";
}

function loadVideo(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const video = document.createElement("video");
    video.preload = "metadata";
    video.muted = true;
    video.defaultMuted = true;
    video.playsInline = true;
    video.setAttribute("muted", "");
    video.setAttribute("playsinline", "");
    video.src = url;
    video.onloadedmetadata = () => resolve({ video, url });
    video.onerror = () => {
      URL.revokeObjectURL(url);
      const error = Error("浏览器无法读取视频参数");
      error.code = "VIDEO_METADATA_UNAVAILABLE";
      reject(error);
    };
  });
}

async function estimateFrameRate(video, signal) {
  if (!("requestVideoFrameCallback" in video) || video.duration <= 0) return 0;
  throwIfAborted(signal);
  const sampleDuration = Math.min(1.5, video.duration);
  let frameCount = 0;
  let firstMediaTime = null;
  let lastMediaTime = null;
  let callbackId = 0;
  const sampling = new Promise((resolve) => {
    const countFrame = (_now, metadata) => {
      frameCount += 1;
      firstMediaTime ??= metadata.mediaTime;
      lastMediaTime = metadata.mediaTime;
      if (metadata.mediaTime >= sampleDuration || video.ended) {
        resolve();
        return;
      }
      callbackId = video.requestVideoFrameCallback(countFrame);
    };
    callbackId = video.requestVideoFrameCallback(countFrame);
  });
  video.currentTime = 0;
  video.playbackRate = 4;
  try {
    await video.play();
  } catch (_error) {
    if (callbackId) video.cancelVideoFrameCallback(callbackId);
    video.playbackRate = 1;
    return 0;
  }
  const aborted = new Promise((_, reject) => {
    signal?.addEventListener("abort", () => reject(signal.reason || new DOMException("操作已取消", "AbortError")), { once: true });
  });
  await Promise.race([sampling, new Promise((resolve) => window.setTimeout(resolve, 2500)), aborted]);
  video.pause();
  if (callbackId) video.cancelVideoFrameCallback(callbackId);
  video.playbackRate = 1;
  const sampledSeconds = (lastMediaTime ?? 0) - (firstMediaTime ?? 0);
  return sampledSeconds > 0 ? Math.round(((frameCount - 1) / sampledSeconds) * 10) / 10 : 0;
}

export async function inspectVideo(file, { signal } = {}) {
  throwIfAborted(signal);
  if (!file || file.size <= 0) throw Error("请选择有效的视频文件");
  const profile = compressionProfile();
  if (file.size > profile.sourceFileMaxBytes) {
    throw Error("原视频不能超过 2 GB");
  }
  let loadedVideo;
  try {
    loadedVideo = await loadVideo(file);
  } catch (error) {
    throwIfAborted(signal);
    if (error.code !== "VIDEO_METADATA_UNAVAILABLE") throw error;
    if (file.size > UPLOAD_FILE_MAX_BYTES) {
      throw Error("浏览器无法读取该视频参数，且原视频超过 512 MB，无法直接上传；请先在系统相册中导出为兼容 MP4 或降低清晰度");
    }
    return {
      width: 0,
      height: 0,
      duration: 0,
      frameRate: 0,
      size: file.size,
      needsCompression: false,
      compressionSupported: false,
      inspectionUnavailable: true,
      profile,
    };
  }
  const { video, url } = loadedVideo;
  try {
    throwIfAborted(signal);
    const frameRate = await estimateFrameRate(video, signal);
    throwIfAborted(signal);
    const needsCompression =
      file.size > COMPRESSION_SIZE_THRESHOLD ||
      Math.max(video.videoWidth, video.videoHeight) > profile.maxEdge ||
      frameRate > MAX_SOURCE_FPS;
    const compressionSupported =
      typeof HTMLCanvasElement.prototype.captureStream === "function" && Boolean(supportedMp4MimeType());
    return {
      width: video.videoWidth,
      height: video.videoHeight,
      duration: video.duration,
      frameRate,
      size: file.size,
      needsCompression,
      compressionSupported,
      profile,
    };
  } finally {
    video.removeAttribute("src");
    video.load();
    URL.revokeObjectURL(url);
  }
}

function outputDimensions(width, height, maxEdge) {
  const scale = Math.min(1, maxEdge / Math.max(width, height));
  return {
    width: Math.max(2, Math.round((width * scale) / 2) * 2),
    height: Math.max(2, Math.round((height * scale) / 2) * 2),
  };
}

function outputProfile(metadata, profile) {
  const sourceBitrate = metadata.duration > 0 ? (metadata.size * 8) / metadata.duration : profile.videoBitsPerSecond;
  return {
    outputFps: Math.min(profile.outputFps, metadata.frameRate > 0 ? metadata.frameRate : profile.outputFps),
    videoBitsPerSecond: Math.min(profile.videoBitsPerSecond, sourceBitrate),
  };
}

export async function compressVideo(file, metadata, onProgress, { signal } = {}) {
  throwIfAborted(signal);
  const mimeType = supportedMp4MimeType();
  if (!metadata.compressionSupported || !mimeType) {
    if (file.size <= UPLOAD_FILE_MAX_BYTES) return file;
    throw Error("当前移动浏览器无法压缩该视频，请先在系统相册中降低清晰度或使用桌面版 Chrome/Edge");
  }
  const profile = metadata.profile || compressionProfile();
  const output = outputProfile(metadata, profile);
  const estimatedOutputBytes = (metadata.duration * output.videoBitsPerSecond) / 8;
  if (estimatedOutputBytes > profile.outputBudgetBytes) {
    throw Error("视频过长，预计压缩结果超过安全上限，请先剪短视频");
  }
  const { video, url } = await loadVideo(file);
  const canvas = document.createElement("canvas");
  const dimensions = outputDimensions(metadata.width, metadata.height, profile.maxEdge);
  canvas.width = dimensions.width;
  canvas.height = dimensions.height;
  const context = canvas.getContext("2d", { alpha: false });
  const stream = canvas.captureStream(output.outputFps);
  let recorder;
  try {
    recorder = new MediaRecorder(stream, { mimeType, videoBitsPerSecond: output.videoBitsPerSecond });
  } catch (_error) {
    stream.getTracks().forEach((track) => track.stop());
    URL.revokeObjectURL(url);
    if (file.size <= UPLOAD_FILE_MAX_BYTES) return file;
    throw Error("当前浏览器无法启动视频压缩，请先在系统相册中降低清晰度");
  }
  const chunks = [];
  let outputBytes = 0;
  recorder.ondataavailable = (event) => {
    if (!event.data.size) return;
    outputBytes += event.data.size;
    if (outputBytes > profile.outputBudgetBytes) {
      recorder.stop();
      return;
    }
    chunks.push(event.data);
  };
  const completed = new Promise((resolve, reject) => {
    recorder.onerror = () => reject(Error("视频压缩失败"));
    recorder.onstop = () => resolve(new Blob(chunks, { type: "video/mp4" }));
  });
  let animationFrame = 0;
  const abort = () => {
    video.pause();
    if (recorder.state !== "inactive") recorder.stop();
  };
  signal?.addEventListener("abort", abort, { once: true });
  const draw = () => {
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    const percent = metadata.duration > 0 ? Math.min(99, Math.round((video.currentTime / metadata.duration) * 100)) : 0;
    onProgress(percent, "正在压缩视频");
    if (!video.ended) animationFrame = requestAnimationFrame(draw);
  };
  try {
    throwIfAborted(signal);
    video.currentTime = 0;
    try {
      recorder.start(1000);
    } catch (_error) {
      if (file.size <= UPLOAD_FILE_MAX_BYTES) return file;
      throw Error("当前浏览器无法启动视频压缩，请先在系统相册中降低清晰度");
    }
    try {
      await video.play();
    } catch (_error) {
      if (file.size <= UPLOAD_FILE_MAX_BYTES) return file;
      throw Error("当前浏览器无法播放视频进行压缩，请先在系统相册中降低清晰度");
    }
    draw();
    await new Promise((resolve, reject) => {
      const abortPlayback = () => reject(signal.reason || new DOMException("操作已取消", "AbortError"));
      video.onended = resolve;
      video.onerror = () => reject(Error("视频压缩过程中读取失败"));
      signal?.addEventListener("abort", abortPlayback, { once: true });
    }).finally(() => {
      video.onended = null;
      video.onerror = null;
    });
    throwIfAborted(signal);
    recorder.stop();
    const blob = await completed;
    throwIfAborted(signal);
    if (outputBytes > profile.outputBudgetBytes) throw Error("压缩结果超过设备安全内存预算，请先剪短视频");
    if (blob.size > UPLOAD_FILE_MAX_BYTES) throw Error("压缩后的视频仍超过 512 MB，请缩短视频后重试");
    onProgress(100, "压缩完成");
    const baseName = file.name.replace(/\.[^.]+$/, "");
    Object.defineProperty(blob, "name", { value: `${baseName}-compressed.mp4` });
    return blob;
  } finally {
    signal?.removeEventListener("abort", abort);
    cancelAnimationFrame(animationFrame);
    stream.getTracks().forEach((track) => track.stop());
    if (recorder.state !== "inactive") recorder.stop();
    video.pause();
    video.removeAttribute("src");
    video.load();
    URL.revokeObjectURL(url);
  }
}

export const videoCompressionLimits = {
  sourceFileMaxBytes: SOURCE_FILE_MAX_BYTES,
  uploadFileMaxBytes: UPLOAD_FILE_MAX_BYTES,
  compressionSizeThreshold: COMPRESSION_SIZE_THRESHOLD,
  maxVideoEdge: MAX_VIDEO_EDGE,
  maxSourceFps: MAX_SOURCE_FPS,
  outputFps: OUTPUT_FPS,
};
