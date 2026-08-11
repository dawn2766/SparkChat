const INCOMPLETE_LIST_MARKER = /^(?: {0,3})(?:[-+*]|\d{1,9}[.)])[ \t]*$/;

export function stableStreamingMarkdown(content) {
  const text = String(content || "").replace(/\r\n?/g, "\n");
  const lastLineStart = text.lastIndexOf("\n") + 1;
  return INCOMPLETE_LIST_MARKER.test(text.slice(lastLineStart))
    ? text.slice(0, lastLineStart)
    : text;
}