const EDGE_TOLERANCE = 1;

export function shouldFollowDeepSeek(mode, bodyHeight, viewportHeight) {
  if (mode === "bottom") return true;
  if (mode !== "threshold") return false;
  return bodyHeight < viewportHeight - EDGE_TOLERANCE;
}

export function hasAssistantContentBelowViewport(contentBottom, viewportBottom) {
  return contentBottom > viewportBottom + EDGE_TOLERANCE;
}