import assert from "node:assert/strict";
import { mergeRealtimeText } from "../../frontend/scripts/realtime-text.js";

assert.equal(mergeRealtimeText("", "(He pauses.)"), "(He pauses.)");
assert.equal(mergeRealtimeText("(He pauses.)", "  State your purpose."), "(He pauses.)  State your purpose.");
assert.equal(mergeRealtimeText("你好。。  ", "世界！"), "你好。。  世界！");

console.log("Realtime subtitle append tests passed.");