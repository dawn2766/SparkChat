const PUNCTUATION = "，。！？；：、,.!?;:";

function cleanRealtimeText(value) {
  return String(value || "")
    .replace(/\r?\n+/g, " ")
    .replace(/[ \t]+/g, " ")
    .replace(new RegExp(`([${PUNCTUATION}])\\1+`, "g"), "$1")
    .replace(new RegExp(` +([${PUNCTUATION}])`, "g"), "$1")
    .replace(/([，。！？；：、]) +(?=[\u3400-\u9fff])/g, "$1")
    .trim();
}

export function mergeRealtimeText(current, incoming) {
  const existing = cleanRealtimeText(current);
  const next = cleanRealtimeText(incoming);
  if (!next) return existing;
  if (!existing || next.startsWith(existing)) return next;
  if (existing.startsWith(next) || existing.includes(next)) return existing;

  const terminalPunctuation = new RegExp(`[${PUNCTUATION}]+$`);
  const existingStem = existing.replace(terminalPunctuation, "");
  if (existingStem && next.startsWith(existingStem)) return next;

  const overlapLimit = Math.min(existing.length, next.length);
  for (let overlap = overlapLimit; overlap > 0; overlap -= 1) {
    if (existing.endsWith(next.slice(0, overlap))) {
      return cleanRealtimeText(existing + next.slice(overlap));
    }
  }

  const separator = /[A-Za-z0-9.!?;:]$/.test(existing) && /^[A-Za-z0-9]/.test(next) ? " " : "";
  return cleanRealtimeText(existing + separator + next);
}

export function completeSubtitleSentence(text, language = "zh") {
  const cleaned = cleanRealtimeText(text);
  if (!cleaned || /[，。！？；：、,.!?;:]$/.test(cleaned)) return cleaned;
  return `${cleaned}${language === "en" ? "." : "。"}`;
}