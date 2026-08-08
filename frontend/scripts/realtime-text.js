export function mergeRealtimeText(current, incoming) {
  return `${String(current || "")}${String(incoming || "")}`;
}