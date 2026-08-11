import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const source = await readFile(new URL("../../frontend/scripts/views/chat.js", import.meta.url), "utf8");
const lifecycleStart = source.indexOf("function bindVideoTranscriptionPage");
const lifecycleEnd = source.indexOf("function openVideoTranscription", lifecycleStart);
const lifecycle = source.slice(lifecycleStart, lifecycleEnd);

assert.ok(lifecycleStart >= 0 && lifecycleEnd > lifecycleStart, "应能定位视频转写页面生命周期");
assert.doesNotMatch(lifecycle, /visibilitychange/, "切换标签页或应用不应取消视频转写");
assert.match(lifecycle, /addEventListener\("pagehide", handlePageHide/, "刷新或关闭页面时应取消视频转写");
assert.match(lifecycle, /video-transcription-back[\s\S]*cancelTask\(\)/, "返回聊天时应取消视频转写");

console.log("Video transcription lifecycle tests passed.");