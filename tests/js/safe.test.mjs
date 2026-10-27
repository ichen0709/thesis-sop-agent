// safe.js 的行為：只用 textContent／createTextNode，不允許危險標籤。
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

const WEB = process.env.WEB_DIR;
const dir = fs.mkdtempSync(path.join(os.tmpdir(), "sop-safe-"));
fs.copyFileSync(path.join(WEB, "safe.js"), path.join(dir, "safe.mjs"));

class El {
  constructor(tag) { this.tagName = tag; this.children = []; this._text = ""; this.className = ""; }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this._text; }
  set innerHTML(_v) { throw new Error("innerHTML 不可使用"); }
  appendChild(c) { this.children.push(c); return c; }
}
globalThis.document = {
  createElement: (t) => new El(t),
  createTextNode: (t) => ({ nodeType: 3, textContent: String(t) }),
};
const { setText, appendText, makeEl } = await import(pathToFileURL(path.join(dir, "safe.mjs")).href);
const evil = '<script>alert(1)</script><img src=x onerror=alert(1)>';

test("setText 把字串原樣當文字", () => {
  const el = new El("div");
  setText(el, evil);
  assert.equal(el.textContent, evil);
  assert.equal(el.children.length, 0);
});

test("setText 對 null／undefined 給空字串，數字轉成文字", () => {
  const el = new El("div");
  setText(el, null); assert.equal(el.textContent, "");
  setText(el, undefined); assert.equal(el.textContent, "");
  setText(el, 5); assert.equal(el.textContent, "5");
});

test("appendText 建立文字節點，不是元素", () => {
  const el = new El("div");
  appendText(el, evil);
  assert.equal(el.children.length, 1);
  assert.equal(el.children[0].nodeType, 3);
  assert.equal(el.children[0].textContent, evil);
});

test("makeEl 只允許白名單標籤", () => {
  for (const tag of ["script", "img", "iframe", "a", "style", "object", "embed", "link", "form", "input", "svg"]) {
    assert.throws(() => makeEl(tag, "x"), /不允許/, tag);
  }
  for (const tag of ["div", "p", "li", "blockquote", "option"]) {
    assert.equal(makeEl(tag, evil).textContent, evil);
  }
});

test("makeEl 設定 class 與文字", () => {
  const el = makeEl("div", "內容", "card warn");
  assert.equal(el.className, "card warn");
  assert.equal(el.textContent, "內容");
});
