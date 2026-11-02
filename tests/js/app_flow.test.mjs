// 用假的 DOM 實際執行 web/app.js，檢查畫面邏輯（不需要瀏覽器）。
// 假 DOM 的 innerHTML／outerHTML 一被設定就丟錯，所以只要 app.js 用了就會失敗。
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

const WEB = process.env.WEB_DIR;
const INDEX = fs.readFileSync(path.join(WEB, "index.html"), "utf8");
const IDS = [...INDEX.matchAll(/id="([^"]+)"/g)].map((m) => m[1]);

// ---- 假 DOM ----
class TextNode {
  constructor(text) { this.nodeType = 3; this.children = []; this._text = String(text); }
  get textContent() { return this._text; }
}
class El {
  constructor(tag) {
    this.tagName = tag; this.children = []; this._text = ""; this.listeners = {};
    this.hidden = false; this.disabled = false; this.value = ""; this.className = "";
  }
  set textContent(v) { this.children = []; this._text = String(v); }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(""); }
  set innerHTML(_v) { throw new Error("innerHTML 不可使用"); }
  set outerHTML(_v) { throw new Error("outerHTML 不可使用"); }
  appendChild(c) { this.children.push(c); return c; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  dispatch(type) { for (const fn of this.listeners[type] || []) fn({ preventDefault() {} }); }
  scrollIntoView(opts) { (this.scrolls ||= []).push(opts); }
  focus(opts) { this.focusOpts = opts; this.focused = true; }
}
function walk(node, out = []) { out.push(node); for (const c of node.children || []) walk(c, out); return out; }

function makeDocument() {
  const byId = Object.fromEntries(IDS.map((id) => [id, new El("el:" + id)]));
  byId["stage-placeholder"].hidden = true;
  byId["waiting"].hidden = true;
  byId["length-message"].hidden = true;
  return {
    byId,
    createElement: (tag) => new El(tag),
    createTextNode: (t) => new TextNode(t),
    getElementById: (id) => byId[id] ?? null,
  };
}

const META = {
  stages: ["口試前", "離校"],
  stages_placeholder: true,
  library_updated: "2025-10-01",
  max_question_chars: 500,
  disclaimer: "本回答依系辦文件整理，僅供參考；正式規定以系辦公告為準。",
  unavailable_text: "現在無法回答，請稍後再試，或直接洽系辦。",
  text: {
    stage_label: "目前階段", no_stage_option: "不指定階段", question_label: "你的問題",
    hint: "每次提問是獨立的，請把完整情況寫在問題裡", send: "送出", waiting: "正在查文件…",
    too_long: "問題太長，請縮短", empty: "請輸入問題", question_prefix: "問：",
    library_updated_label: "文件庫最後更新日期", library_empty_label: "（目前沒有文件）",
    placeholder_label: "範例資料，非正式規定",
  },
};

const tick = () => new Promise((r) => setTimeout(r, 0));
async function settle() { for (let i = 0; i < 5; i++) await tick(); }
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
const jsonResponse = (body, ok = true) => ({ ok, json: async () => body });

let counter = 0;
// 複製 app.js 與 safe.js 到暫存資料夾，只把絕對路徑 "/safe.js" 改成 "./safe.mjs" 讓 Node 找得到
function loadApp() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "sop-js-"));
  fs.copyFileSync(path.join(WEB, "safe.js"), path.join(dir, "safe.mjs"));
  const src = fs.readFileSync(path.join(WEB, "app.js"), "utf8");
  assert.ok(src.includes('from "/safe.js"'));
  fs.writeFileSync(path.join(dir, "app.mjs"), src.replace('from "/safe.js"', 'from "./safe.mjs"'));
  return pathToFileURL(path.join(dir, "app.mjs")).href + "?n=" + counter++;
}

async function boot({ askHandler, meta = META } = {}) {
  const doc = makeDocument();
  const calls = [];
  globalThis.document = doc;
  globalThis.fetch = async (url, opts) => {
    calls.push({ url, opts });
    if (url === "/api/meta") return jsonResponse(meta);
    if (url === "/api/ask") return askHandler(JSON.parse(opts.body));
    throw new Error("不該呼叫的網址 " + url);
  };
  await import(loadApp());
  await settle();
  return { doc, calls, el: doc.byId };
}
const typeText = (app, text) => { app.el["question"].value = text; app.el["question"].dispatch("input"); };
const submit = (app) => app.el["form"].dispatch("submit");
const allText = (node) => walk(node).map((n) => n.textContent).join("\n");
const askCalls = (app) => app.calls.filter((c) => c.url === "/api/ask");

const ANSWER = {
  kind: "answer", notice: null, answer: "請備妥文件。",
  sections: [
    { title: "下一步", items: [{ label: null, text: "備妥口試申請表", refs: [1], missing: false }] },
    { title: "相關表單", items: [{ label: null, text: "文件未載明", refs: [], missing: true }] },
    { title: "期限與窗口", items: [
      { label: "期限", text: "口試前 14 日（適用：114 學年度第 1 學期；依《口試辦理流程》2025-09-01 版）", refs: [1], missing: false },
      { label: "窗口", text: "文件未載明", refs: [], missing: true } ] },
  ],
  sources_title: "出處",
  sources: [{ n: 1, label: "口試辦理流程（2025-09-01）", quote: "口試申請應於口試日前 14\n日內" }],
};

// ---- 測試 ----
test("載入後：固定文字、階段選單、占位標示、文件庫日期都由伺服器提供", async () => {
  const app = await boot({});
  assert.equal(app.el["disclaimer"].textContent, META.disclaimer);
  assert.equal(app.el["hint"].textContent, "每次提問是獨立的，請把完整情況寫在問題裡");
  assert.equal(app.el["stage-label"].textContent, "目前階段");
  assert.deepEqual(app.el["stage"].children.map((o) => o.textContent), ["不指定階段", "口試前", "離校"]);
  assert.deepEqual(app.el["stage"].children.map((o) => o.value), ["", "口試前", "離校"]);
  assert.equal(app.el["stage-placeholder"].hidden, false);
  assert.equal(app.el["stage-placeholder"].textContent, "範例資料，非正式規定");
  assert.equal(app.el["library-updated"].textContent, "文件庫最後更新日期：2025-10-01");
  assert.equal(app.el["send"].textContent, "送出");
});

test("不是占位階段時不顯示標示；文件庫是空的顯示說明", async () => {
  const app = await boot({ meta: { ...META, stages_placeholder: false, library_updated: null } });
  assert.equal(app.el["stage-placeholder"].hidden, true);
  assert.equal(app.el["library-updated"].textContent, "文件庫最後更新日期：（目前沒有文件）");
});

test("空白不能送出；500 字可以；501 字不行並顯示提示", async () => {
  const app = await boot({});
  assert.equal(app.el["send"].disabled, true);
  typeText(app, "   \n\t ");
  assert.equal(app.el["send"].disabled, true);
  typeText(app, "問".repeat(500));
  assert.equal(app.el["send"].disabled, false);
  assert.equal(app.el["length-message"].hidden, true);
  typeText(app, "問".repeat(501));
  assert.equal(app.el["send"].disabled, true);
  assert.equal(app.el["length-message"].hidden, false);
  assert.equal(app.el["length-message"].textContent, "問題太長，請縮短");
  typeText(app, "問");
  assert.equal(app.el["send"].disabled, false);
  assert.equal(app.el["length-message"].hidden, true);
});

test("字數以 Unicode 字元計算（表情符號算一個）、頭尾空白不算", async () => {
  const app = await boot({});
  typeText(app, "😀".repeat(500));
  assert.equal(app.el["send"].disabled, false);
  typeText(app, "😀".repeat(501));
  assert.equal(app.el["send"].disabled, true);
  typeText(app, "  " + "問".repeat(500) + "  ");
  assert.equal(app.el["send"].disabled, false);
});

test("太長或空白時，直接觸發送出也不會呼叫伺服器", async () => {
  const app = await boot({ askHandler: async () => jsonResponse(ANSWER) });
  typeText(app, "問".repeat(501)); submit(app); await settle();
  typeText(app, "   "); submit(app); await settle();
  assert.equal(askCalls(app).length, 0);
});

test("送出後：按鈕停用、顯示「正在查文件…」；回來後恢復並清空輸入框", async () => {
  const pending = deferred();
  const app = await boot({ askHandler: () => pending.promise });
  typeText(app, "口試要準備什麼？");
  assert.equal(app.el["waiting"].hidden, true);
  submit(app); await settle();
  assert.equal(app.el["waiting"].hidden, false);
  assert.equal(app.el["waiting-text"].textContent, "正在查文件…");
  assert.equal(app.el["send"].disabled, true);
  assert.equal(app.el["question"].disabled, true);
  pending.resolve(jsonResponse(ANSWER)); await settle();
  assert.equal(app.el["waiting"].hidden, true);
  assert.equal(app.el["question"].disabled, false);
  assert.equal(app.el["question"].value, "");
  assert.equal(app.el["send"].disabled, true); // 輸入框已清空
  typeText(app, "下一題");
  assert.equal(app.el["send"].disabled, false);
});

test("處理中再次送出會被忽略（只呼叫一次）", async () => {
  const pending = deferred();
  const app = await boot({ askHandler: () => pending.promise });
  typeText(app, "第一題");
  submit(app); await settle();
  app.el["question"].value = "偷偷再送一次"; submit(app); await settle();
  assert.equal(askCalls(app).length, 1);
  pending.resolve(jsonResponse(ANSWER)); await settle();
});

test("送出的內容：問題、階段（沒選是 null）", async () => {
  const app = await boot({ askHandler: async () => jsonResponse(ANSWER) });
  typeText(app, "  問題一  "); submit(app); await settle();
  let body = JSON.parse(askCalls(app).at(-1).opts.body);
  assert.deepEqual(body, { question: "問題一", stage: null });
  assert.equal(askCalls(app).at(-1).opts.method, "POST");
  assert.equal(askCalls(app).at(-1).opts.headers["Content-Type"], "application/json");
  app.el["stage"].value = "口試前";
  typeText(app, "問題二"); submit(app); await settle();
  body = JSON.parse(askCalls(app).at(-1).opts.body);
  assert.deepEqual(body, { question: "問題二", stage: "口試前" });
});

test("答案卡：欄位、「文件未載明」、出處編號與原文片段都畫出來；舊問答保留在畫面上", async () => {
  const app = await boot({ askHandler: async () => jsonResponse(ANSWER) });
  typeText(app, "第一題"); submit(app); await settle();
  typeText(app, "第二題"); submit(app); await settle();
  assert.equal(app.el["history"].children.length, 2);
  const text = allText(app.el["history"]);
  for (const s of ["問：第一題", "問：第二題", "請備妥文件。", "下一步", "相關表單", "期限與窗口", "出處",
    "備妥口試申請表", "文件未載明", "期限：", "窗口：", "[1]", "適用：114 學年度第 1 學期",
    "口試辦理流程（2025-09-01）", "口試申請應於口試日前 14\n日內"]) {
    assert.ok(text.includes(s), "缺少：" + s);
  }
  const missing = walk(app.el["history"]).filter((n) => n.className === "missing");
  assert.ok(missing.length >= 2);
});

test("提醒只在答案卡有 notice 時顯示", async () => {
  const withNotice = { ...ANSWER, notice: "你還沒選目前階段，以下回答是依整個流程的文件整理的" };
  const app = await boot({ askHandler: async () => jsonResponse(withNotice) });
  typeText(app, "一題"); submit(app); await settle();
  assert.ok(allText(app.el["history"]).includes("你還沒選目前階段"));
  const app2 = await boot({ askHandler: async () => jsonResponse(ANSWER) });
  typeText(app2, "一題"); submit(app2); await settle();
  assert.ok(!allText(app2.el["history"]).includes("你還沒選目前階段"));
});

test("查不到卡、範圍外卡、無法回答訊息各自顯示伺服器給的文字", async () => {
  for (const [kind, message, cls] of [
    ["no_info", "文件中沒有這項資訊，請洽系辦。", "card warn"],
    ["out_of_scope", "這類問題不在服務範圍內，請洽系辦。", "card warn"],
    ["unavailable", "現在無法回答，請稍後再試，或直接洽系辦。", "card unavailable"],
  ]) {
    const app = await boot({ askHandler: async () => jsonResponse({ kind, message }) });
    typeText(app, "一題"); submit(app); await settle();
    const card = walk(app.el["history"]).find((n) => n.className === cls);
    assert.ok(card, kind);
    assert.equal(card.textContent, message);
    assert.ok(!allText(app.el["history"]).includes("下一步")); // 不顯示四個欄位
  }
});

test("連線失敗或伺服器回錯誤：顯示「無法回答」訊息，沒有技術細節", async () => {
  const failing = await boot({ askHandler: async () => { throw new Error("TypeError: Failed to fetch C:\\secret"); } });
  typeText(failing, "一題"); submit(failing); await settle();
  assert.ok(allText(failing.el["history"]).includes(META.unavailable_text));
  assert.ok(!allText(failing.el["history"]).includes("Failed to fetch"));
  assert.equal(failing.el["waiting"].hidden, true); // 失敗後也要恢復
  assert.equal(failing.el["question"].disabled, false);

  for (const status of [400, 403, 500]) {
    const app = await boot({ askHandler: async () => jsonResponse({ error: "forbidden" }, false) });
    typeText(app, "一題"); submit(app); await settle();
    assert.ok(allText(app.el["history"]).includes(META.unavailable_text), String(status));
    assert.ok(!allText(app.el["history"]).includes("forbidden"));
  }
});

test("HTML 字串只會變成文字：不產生 script／img 元素，也不碰 innerHTML", async () => {
  const evil = '<script>alert("evil")</script><img src=x onerror=alert(1)>';
  const card = {
    kind: "answer", notice: evil, answer: evil,
    sections: [
      { title: evil, items: [{ label: evil, text: evil, refs: [1], missing: false }] },
    ],
    sources_title: evil,
    sources: [{ n: 1, label: evil, quote: evil }],
  };
  const app = await boot({ askHandler: async () => jsonResponse(card) });
  app.el["stage"].value = evil; // 即使被竄改的階段值也只會被當文字顯示
  typeText(app, evil); submit(app); await settle();
  const nodes = walk(app.el["history"]);
  assert.ok(nodes.length > 10);
  for (const n of nodes) {
    assert.ok(!["script", "img", "iframe", "a", "style", "object"].includes(n.tagName), "不該有 " + n.tagName);
  }
  // 惡意字串確實出現在畫面上（當成文字）：問題、階段、提醒、回答、標題、項目、出處標題、出處標籤、片段
  const occurrences = allText(app.el["history"]).split(evil).length - 1;
  assert.ok(occurrences >= 8, "只出現 " + occurrences + " 次");
});

test("app.js 只透過 safe.js 建立元素：全部都在白名單內", async () => {
  const app = await boot({ askHandler: async () => jsonResponse(ANSWER) });
  typeText(app, "一題"); submit(app); await settle();
  const allowed = new Set(["div", "span", "p", "ul", "li", "h2", "h3", "button", "strong", "blockquote",
    "section", "label", "small", "option", "ol"]);
  for (const n of walk(app.el["history"])) {
    if (n.nodeType === 3 || String(n.tagName).startsWith("el:")) continue;
    assert.ok(allowed.has(n.tagName), n.tagName);
  }
});

test("新的問答出現後，捲到「那一則」的開頭（block: start），不是捲到最底", async () => {
  const app = await boot({ askHandler: async () => jsonResponse(ANSWER) });
  typeText(app, "第一題"); submit(app); await settle();
  typeText(app, "第二題"); submit(app); await settle();
  const [first, second] = app.el["history"].children;
  // 每一則在加入問題時、卡片加進去後各對齊一次自己的開頭
  assert.equal(first.scrolls.length, 2);
  assert.equal(second.scrolls.length, 2);
  for (const opts of [...first.scrolls, ...second.scrolls]) {
    assert.equal(opts.block, "start");
  }
  // 不會去捲整個紀錄區（history）或其他元素
  assert.equal(app.el["history"].scrolls, undefined);
  assert.equal(app.el["log"].scrolls, undefined);
});

test("卡片是在加進問答之後才再對齊一次（長答案的開頭不會被擠出畫面）", async () => {
  const pending = deferred();
  const app = await boot({ askHandler: () => pending.promise });
  typeText(app, "一題"); submit(app); await settle();
  const entry = app.el["history"].children[0];
  assert.equal(entry.scrolls.length, 1); // 問題加進去時先對齊
  pending.resolve(jsonResponse(ANSWER)); await settle();
  assert.equal(entry.scrolls.length, 2); // 卡片加進去後再對齊
  assert.ok(entry.children.length >= 2); // 問題 + 卡片
});

test("回到輸入框時不讓瀏覽器自己亂捲（preventScroll）", async () => {
  const app = await boot({ askHandler: async () => jsonResponse(ANSWER) });
  typeText(app, "一題"); submit(app); await settle();
  assert.equal(app.el["question"].focusOpts?.preventScroll, true);
});

test("輸入框的 placeholder 來自伺服器，輸入區的元素都還在", async () => {
  const app = await boot({});
  assert.equal(app.el["question"].placeholder, "你的問題");
  for (const id of ["stage", "question", "send", "hint"]) assert.ok(app.el[id], id);
});

// ---- 聯絡方式 ----
const CONTACT = {
  title: "系所聯絡方式", hint: "（請依你的班別或所屬單位選擇）",
  lines: ["電話 03-111-0001：甲班、乙班（Class B）", "電子郵件 a@example.test：甲單位", "地點：測試樓 101 室"],
  checked: "聯絡資訊取自系所官網，查閱日期 2026-01-02",
};

test("三種訊息卡：有聯絡資料就列出每一行與查閱日期，全是純文字", async () => {
  for (const [kind, message, cls] of [
    ["no_info", "文件中沒有這項資訊，請洽系辦。", "card warn"],
    ["out_of_scope", "這類問題不在服務範圍內，請洽系辦。", "card warn"],
    ["unavailable", "現在無法回答，請稍後再試，或直接洽系辦。", "card unavailable"],
  ]) {
    const app = await boot({ askHandler: async () => jsonResponse({ kind, message, contact: CONTACT }) });
    typeText(app, "一題"); submit(app); await settle();
    const card = walk(app.el["history"]).find((n) => n.className === cls);
    assert.ok(card, kind);
    const text = card.textContent;
    assert.ok(text.includes(message));
    assert.ok(text.includes("系所聯絡方式") && text.includes("（請依你的班別或所屬單位選擇）"));
    for (const line of CONTACT.lines) assert.ok(text.includes(line), line);
    assert.ok(text.includes(CONTACT.checked));
    for (const n of walk(card)) assert.notEqual(n.tagName, "a"); // 不做連結
  }
});

test("沒有聯絡資料：訊息卡跟原本一樣，只有那一句", async () => {
  const app = await boot({ askHandler: async () => jsonResponse({ kind: "no_info", message: "文件中沒有這項資訊，請洽系辦。" }) });
  typeText(app, "一題"); submit(app); await settle();
  const card = walk(app.el["history"]).find((n) => n.className === "card warn");
  assert.equal(card.textContent, "文件中沒有這項資訊，請洽系辦。");
});

test("含 HTML 的聯絡字串只會變成文字", async () => {
  const evil = '<script>alert("evil")</script><img src=x onerror=alert(1)>';
  const contact = { title: evil, hint: evil, lines: [evil], checked: evil };
  const app = await boot({ askHandler: async () => jsonResponse({ kind: "no_info", message: "請洽系辦", contact }) });
  typeText(app, "一題"); submit(app); await settle();
  for (const n of walk(app.el["history"])) {
    assert.ok(!["script", "img", "iframe", "a", "style", "object"].includes(n.tagName), n.tagName);
  }
  assert.ok(allText(app.el["history"]).split(evil).length - 1 >= 4);
});

test("連不上伺服器：「無法回答」卡用載入時 /api/meta 拿到的聯絡資料", async () => {
  const app = await boot({ meta: { ...META, contact: CONTACT },
    askHandler: async () => { throw new Error("Failed to fetch"); } });
  typeText(app, "一題"); submit(app); await settle();
  const text = allText(app.el["history"]);
  assert.ok(text.includes(META.unavailable_text));
  for (const line of CONTACT.lines) assert.ok(text.includes(line), line);
  assert.ok(!text.includes("Failed to fetch"));

  const app2 = await boot({ meta: { ...META, contact: CONTACT },
    askHandler: async () => jsonResponse({ error: "forbidden" }, false) });
  typeText(app2, "一題"); submit(app2); await settle();
  assert.ok(allText(app2.el["history"]).includes(CONTACT.lines[0]));
});

test("連不上伺服器且 meta 沒有聯絡資料：只顯示「無法回答」那句", async () => {
  const app = await boot({ meta: { ...META, contact: null }, askHandler: async () => { throw new Error("x"); } });
  typeText(app, "一題"); submit(app); await settle();
  const card = walk(app.el["history"]).find((n) => n.className === "card unavailable");
  assert.equal(card.textContent, META.unavailable_text);
});
