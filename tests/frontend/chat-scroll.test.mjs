import assert from "node:assert/strict";

import { hasAssistantContentBelowViewport, shouldFollowDeepSeek } from "../../frontend/scripts/chat-scroll.js";

assert.equal(shouldFollowDeepSeek("threshold", 100, 100), false, "正文高度达到消息栏高度后应停止跟随");
assert.equal(shouldFollowDeepSeek("threshold", 98, 100), true, "正文明确未占满消息栏时应继续跟随");
assert.equal(shouldFollowDeepSeek("threshold", 140, 100), false, "正文超过消息栏高度后应停止跟随");
assert.equal(shouldFollowDeepSeek("bottom", 140, 100), true, "点击到底部后应持续跟随");
assert.equal(shouldFollowDeepSeek("manual", 140, 100), false, "用户接管后不应自动滚动");

assert.equal(hasAssistantContentBelowViewport(501, 500), false, "边缘取整误差不应显示按钮");
assert.equal(hasAssistantContentBelowViewport(502, 500), true, "内容低于输入栏时应显示按钮");

console.log("Chat scroll tests passed.");