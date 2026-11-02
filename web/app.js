// 問答畫面。伺服器已經把所有要顯示的文字組好，這裡只負責用 safe.js 畫出來。
import { appendText, makeEl, setText } from "/safe.js";

const $ = (id) => document.getElementById(id);

const stageSelect = $("stage");
const questionBox = $("question");
const sendButton = $("send");
const lengthMessage = $("length-message");
const waiting = $("waiting");
const history = $("history");

let meta = null;
let busy = false;

// 防護 5 開始：畫面只用 safe.js 寫入（textContent），不解析 HTML
function renderItem(item) {
  const li = makeEl("li", "", item.missing ? "missing" : "");
  if (item.label) {
    li.appendChild(makeEl("strong", item.label + "："));
  }
  appendText(li, item.text);
  for (const n of item.refs) {
    li.appendChild(makeEl("small", " [" + n + "]", "ref"));
  }
  return li;
}

function renderAnswerCard(card) {
  const box = makeEl("div", "", "card answer");
  if (card.notice) {
    box.appendChild(makeEl("p", card.notice, "notice"));
  }
  box.appendChild(makeEl("p", card.answer, "answer-text"));
  for (const section of card.sections) {
    const sec = makeEl("section", "", "field");
    sec.appendChild(makeEl("h3", section.title));
    const list = makeEl("ul");
    for (const item of section.items) {
      list.appendChild(renderItem(item));
    }
    sec.appendChild(list);
    box.appendChild(sec);
  }
  const src = makeEl("section", "", "field sources");
  src.appendChild(makeEl("h3", card.sources_title));
  const list = makeEl("ol");
  for (const s of card.sources) {
    const li = makeEl("li");
    li.appendChild(makeEl("strong", "[" + s.n + "] " + s.label));
    li.appendChild(makeEl("blockquote", s.quote));
    list.appendChild(li);
  }
  src.appendChild(list);
  box.appendChild(src);
  return box;
}

function renderContact(contact) {
  const sec = makeEl("section", "", "contact");
  const heading = makeEl("h3", contact.title);
  heading.appendChild(makeEl("small", contact.hint, "contact-hint"));
  sec.appendChild(heading);
  const list = makeEl("ul");
  for (const line of contact.lines) {
    list.appendChild(makeEl("li", line));
  }
  sec.appendChild(list);
  sec.appendChild(makeEl("small", contact.checked, "contact-checked"));
  return sec;
}

function renderMessageCard(card) {
  const cls = card.kind === "unavailable" ? "card unavailable" : "card warn";
  if (!card.contact) {
    return makeEl("div", card.message, cls); // 沒有聯絡資料：只顯示「請洽系辦」那句
  }
  const box = makeEl("div", "", cls);
  box.appendChild(makeEl("p", card.message, "message"));
  box.appendChild(renderContact(card.contact));
  return box;
}

function renderCard(card) {
  return card.kind === "answer" ? renderAnswerCard(card) : renderMessageCard(card);
}

function addHistoryEntry(question, stage) {
  const entry = makeEl("div", "", "entry");
  const q = makeEl("div", "", "question");
  q.appendChild(makeEl("strong", meta.text.question_prefix));
  appendText(q, question);
  if (stage) {
    q.appendChild(makeEl("small", "（" + stage + "）", "stage-tag"));
  }
  entry.appendChild(q);
  history.appendChild(entry);
  return entry;
}
// 防護 5 結束

// 捲到這一則問答的開頭（不是捲到最底），長答案的開頭才不會被擠出畫面。
// 紀錄區自己捲動，輸入區（階段選單、輸入框）固定在畫面下方，不會被推走。
function scrollToEntry(entry) {
  const reduce = globalThis.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
  entry.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
}

function charCount(text) {
  return [...text.trim()].length; // 以 Unicode 字元計算，與後端一致
}

function updateForm() {
  const n = charCount(questionBox.value);
  const tooLong = n > meta.max_question_chars;
  lengthMessage.hidden = !tooLong;
  sendButton.disabled = busy || n === 0 || tooLong;
}

function setBusy(value) {
  busy = value;
  waiting.hidden = !value;
  questionBox.disabled = value;
  updateForm();
}

// 連不上伺服器時，聯絡方式用頁面載入時 /api/meta 已經拿到的那份（沒有就只顯示訊息）
function unavailableCard() {
  return { kind: "unavailable", message: meta.unavailable_text, contact: meta.contact || null };
}

async function submit(event) {
  event.preventDefault();
  if (busy) {
    return;
  }
  const question = questionBox.value.trim();
  if (charCount(question) === 0 || charCount(question) > meta.max_question_chars) {
    return;
  }
  const stage = stageSelect.value || null;
  const entry = addHistoryEntry(question, stage);
  scrollToEntry(entry);
  setBusy(true);
  let card;
  try {
    const res = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, stage }),
    });
    card = res.ok ? await res.json() : unavailableCard();
  } catch (err) {
    card = unavailableCard();
  }
  entry.appendChild(renderCard(card));
  scrollToEntry(entry); // 卡片加進去後內容變高，再對齊一次這一則的開頭
  questionBox.value = "";
  setBusy(false);
  questionBox.focus({ preventScroll: true });
}

async function init() {
  const res = await fetch("/api/meta");
  meta = await res.json();

  setText($("stage-label"), meta.text.stage_label);
  setText($("question-label"), meta.text.question_label);
  questionBox.placeholder = meta.text.question_label;
  setText($("hint"), meta.text.hint);
  setText($("disclaimer"), meta.disclaimer);
  setText($("send"), meta.text.send);
  setText($("waiting-text"), meta.text.waiting);
  setText(lengthMessage, meta.text.too_long);

  stageSelect.appendChild(makeOption("", meta.text.no_stage_option));
  for (const name of meta.stages) {
    stageSelect.appendChild(makeOption(name, name));
  }
  const badge = $("stage-placeholder");
  if (meta.stages_placeholder) {
    setText(badge, meta.text.placeholder_label);
    badge.hidden = false;
  }

  setText(
    $("library-updated"),
    meta.text.library_updated_label + "：" + (meta.library_updated || meta.text.library_empty_label),
  );

  questionBox.addEventListener("input", updateForm);
  $("form").addEventListener("submit", submit);
  updateForm();
}

function makeOption(value, text) {
  const option = makeEl("option", text);
  option.value = value;
  return option;
}

init();
