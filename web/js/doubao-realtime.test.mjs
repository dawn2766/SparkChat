import assert from "node:assert/strict";
import { completeSubtitleSentence, mergeRealtimeText } from "./realtime-text.js";

assert.equal(mergeRealtimeText("", "State your purpose."), "State your purpose.");
assert.equal(
  mergeRealtimeText("State your purpose.", "State your purpose."),
  "State your purpose.",
);
assert.equal(
  mergeRealtimeText("State your", "State your purpose."),
  "State your purpose.",
);
assert.equal(
  mergeRealtimeText("State your purpose.", "purpose."),
  "State your purpose.",
);
assert.equal(mergeRealtimeText("Cyber", "bertron"), "Cybertron");
assert.equal(
  mergeRealtimeText("State", " your purpose."),
  "State your purpose.",
);
assert.equal(
  mergeRealtimeText("State your", " purpose."),
  "State your purpose.",
);
assert.equal(
  mergeRealtimeText("State your purpose", "State your purpose."),
  "State your purpose.",
);
assert.equal(
  mergeRealtimeText("准备行动", "准备行动。"),
  "准备行动。",
);
assert.equal(
  mergeRealtimeText("准备行动。", "准备行动，马上出发。"),
  "准备行动，马上出发。",
);
assert.equal(
  mergeRealtimeText("你好。。  世界", "世界！"),
  "你好。世界！",
);
assert.equal(
  mergeRealtimeText("State your purpose.", "State your purpose. Now."),
  "State your purpose. Now.",
);
assert.equal(
  mergeRealtimeText("First sentence.", "Second sentence."),
  "First sentence. Second sentence.",
);
assert.equal(completeSubtitleSentence("马上出发", "zh"), "马上出发。");
assert.equal(completeSubtitleSentence("Move out", "en"), "Move out.");
assert.equal(completeSubtitleSentence("准备好了吗？", "zh"), "准备好了吗？");

console.log("Realtime subtitle merge tests passed.");