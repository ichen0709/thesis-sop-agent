// 前端安全寫入：所有顯示學生輸入、模型回答、原文片段、文件名稱的地方都用這裡的函式。
// 只用 textContent 與 createTextNode，不解析 HTML。

// 防護 5 開始：前端安全寫入
const ALLOWED_TAGS = new Set([
  "div", "span", "p", "ul", "li", "h2", "h3", "button",
  "strong", "blockquote", "section", "label", "small", "option", "ol",
]);

export function setText(element, text) {
  element.textContent = String(text ?? "");
}

export function appendText(parent, text) {
  parent.appendChild(document.createTextNode(String(text ?? "")));
}

export function makeEl(tag, text = "", className = "") {
  if (!ALLOWED_TAGS.has(tag)) {
    throw new Error("不允許的標籤");
  }
  const el = document.createElement(tag);
  if (className) {
    el.className = className;
  }
  setText(el, text);
  return el;
}
// 防護 5 結束
