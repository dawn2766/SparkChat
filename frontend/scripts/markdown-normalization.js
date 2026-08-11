const LIST_DASHES = "\\-\\u2010\\u2011\\u2012\\u2013\\u2212\\uFE58\\uFE63\\uFF0D";
const LIST_BULLETS = "\\u2022\\u2023\\u2043\\u2219\\u25CF\\u25E6";

export function normalizeMarkdown(content) {
  return String(content || "")
    .normalize("NFC")
    .replace(/\r\n?/g, "\n")
    .replace(new RegExp(`^([ \\t]{0,3})[${LIST_DASHES}${LIST_BULLETS}][\\u00A0\\u202F \\t]+`, "gm"), "$1- ")
    .replace(/^( {0,3}\d{1,9})[．。][\u00A0\u202F \t]+/gm, "$1. ");
}