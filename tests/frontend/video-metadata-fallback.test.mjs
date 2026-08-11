import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const source = await readFile(new URL("../../frontend/scripts/video-compression.js", import.meta.url), "utf8");
const inspectStart = source.indexOf("export async function inspectVideo");
const inspectEnd = source.indexOf("function outputDimensions", inspectStart);
const inspectVideo = source.slice(inspectStart, inspectEnd);

assert.ok(inspectStart >= 0 && inspectEnd > inspectStart, "应能定位视频参数检测逻辑");
assert.match(inspectVideo, /VIDEO_METADATA_UNAVAILABLE/, "应识别浏览器无法解析视频元数据的情况");
assert.match(inspectVideo, /file\.size > UPLOAD_FILE_MAX_BYTES/, "元数据不可读时仍应执行服务端上传大小限制");
assert.match(inspectVideo, /needsCompression:\s*false/, "上传大小允许时应跳过本地压缩并直接上传原视频");
assert.match(inspectVideo, /inspectionUnavailable:\s*true/, "降级结果应明确标记参数检测不可用");

console.log("Video metadata fallback tests passed.");