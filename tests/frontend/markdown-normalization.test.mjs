import assert from "node:assert/strict";

import { normalizeMarkdown } from "../../frontend/scripts/markdown-normalization.js";

assert.equal(
  normalizeMarkdown("－\u00a0项目一\n– 项目二\n•\u202f项目三\n1． 第一项"),
  "- 项目一\n- 项目二\n- 项目三\n1. 第一项",
  "模型和 OCR 输出的兼容字符应转换为标准 Markdown 列表标记",
);

assert.equal(
  normalizeMarkdown("正文中的－和 – 不应改变\r\n- 标准列表"),
  "正文中的－和 – 不应改变\n- 标准列表",
  "只应规范化行首列表标记，并统一换行符",
);

console.log("Markdown normalization tests passed.");