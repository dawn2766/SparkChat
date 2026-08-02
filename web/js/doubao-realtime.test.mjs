import assert from "node:assert/strict";
import { mergeRealtimeText } from "./realtime-text.js";

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

console.log("Realtime subtitle merge tests passed.");