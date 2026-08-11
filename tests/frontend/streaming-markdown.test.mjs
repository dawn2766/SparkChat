import assert from "node:assert/strict";

import { stableStreamingMarkdown } from "../../frontend/scripts/streaming-markdown.js";

for (const marker of ["-", "- ", "+ ", "* ", "1.", "1. ", "2) "]) {
  assert.equal(stableStreamingMarkdown(marker), "", `不应渲染未完成的列表标记：${JSON.stringify(marker)}`);
}

assert.equal(
  stableStreamingMarkdown("- 第一项\n- "),
  "- 第一项\n",
  "后续列表项尚无正文时，不应生成空列表项",
);
assert.equal(
  stableStreamingMarkdown("1. 第一项\n2. "),
  "1. 第一项\n",
  "数字列表标记尚无正文时，不应产生临时空行",
);
assert.equal(stableStreamingMarkdown("- 项目"), "- 项目", "正文到达后应立即恢复列表渲染");
assert.equal(stableStreamingMarkdown("1. 第一项"), "1. 第一项", "完整数字列表项应保持不变");

console.log("Streaming Markdown tests passed.");