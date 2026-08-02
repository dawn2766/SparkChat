export function mergeRealtimeText(current, incoming) {
  const raw = String(incoming || "");
  if (!raw.trim()) return current;
  const next = current ? raw.trimEnd() : raw.trim();
  if (!current || next.startsWith(current)) return next;
  if (current.includes(next)) return current;
  const overlapLimit = Math.min(current.length, next.length);
  for (let overlap = overlapLimit; overlap > 0; overlap -= 1) {
    if (current.endsWith(next.slice(0, overlap))) return current + next.slice(overlap);
  }
  return current + next;
}