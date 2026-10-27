"""把問答結果轉成要顯示的卡片（JSON）。

所有給學生看的文字都在這裡決定：區塊標題、「文件未載明」、提示、出處標籤。
前端只負責用 textContent 把這些字串畫出來，不做判斷，所以畫面內容可以用 Python 測試。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from sop_agent.schema import ModelResponse, SourceDoc

# 免責提示：單一常數。確切用詞還沒和系辦確認。
DISCLAIMER = "本回答依系辦文件整理，僅供參考；正式規定以系辦公告為準。"

NO_INFO_TEXT = "文件中沒有這項資訊，請洽系辦。"
OUT_OF_SCOPE_TEXT = "這類問題不在服務範圍內，請洽系辦。"
UNAVAILABLE_TEXT = "現在無法回答，請稍後再試，或直接洽系辦。"
NO_STAGE_NOTICE = "你還沒選目前階段，以下回答是依整個流程的文件整理的"
MISSING_TEXT = "文件未載明"
PLACEHOLDER_LABEL = "範例資料，非正式規定"

SECTION_NEXT_STEPS = "下一步"
SECTION_FORMS = "相關表單"
SECTION_DEADLINE_CONTACT = "期限與窗口"
SECTION_SOURCES = "出處"

# 網頁上的固定文字，由 /api/meta 提供給前端。
UI_TEXT: dict[str, str] = {
    "stage_label": "目前階段",
    "no_stage_option": "不指定階段",
    "question_label": "你的問題",
    "hint": "每次提問是獨立的，請把完整情況寫在問題裡",
    "send": "送出",
    "waiting": "正在查文件…",
    "too_long": "問題太長，請縮短",
    "empty": "請輸入問題",
    "question_prefix": "問：",
    "library_updated_label": "文件庫最後更新日期",
    "library_empty_label": "（目前沒有文件）",
    "placeholder_label": PLACEHOLDER_LABEL,
}

# 防護 5 開始：伺服器端移除控制字元
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f  ]")


def clean_text(text: str) -> str:
    """移除控制字元（保留換行與 tab）。學生輸入與模型輸出顯示前都要經過這裡。"""
    return _CONTROL_CHARS.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
# 防護 5 結束


def message_card(kind: str) -> dict[str, Any]:
    """查不到卡、範圍外卡、無法回答訊息。"""
    text = {
        "no_info": NO_INFO_TEXT,
        "out_of_scope": OUT_OF_SCOPE_TEXT,
        "unavailable": UNAVAILABLE_TEXT,
    }[kind]
    return {"kind": kind, "message": text}


def _item(text: str, refs: list[int], label: str | None = None) -> dict[str, Any]:
    return {"label": label, "text": clean_text(text), "refs": refs, "missing": False}


def _missing_item(label: str | None = None) -> dict[str, Any]:
    return {"label": label, "text": MISSING_TEXT, "refs": [], "missing": True}


def build_answer_card(
    response: ModelResponse,
    shown_quotes: tuple[str, ...],
    docs: Mapping[str, SourceDoc],
    stage_selected: bool,
) -> dict[str, Any]:
    """答案卡。呼叫前必須已通過 verify（引用的文件都存在於 docs）。"""
    citations = response.citations

    def refs(cite: list[int]) -> list[int]:
        return [i + 1 for i in cite]

    def source_note(cite: list[int]) -> str:
        seen: list[str] = []
        for i in cite:
            doc = docs[citations[i].doc_id]
            label = f"《{doc.title}》{doc.version_date} 版"
            if label not in seen:
                seen.append(label)
        return "依" + "、".join(seen)

    next_steps = [_item(i.text, refs(i.cite)) for i in response.next_steps] or [_missing_item()]
    forms = [_item(i.text, refs(i.cite)) for i in response.forms] or [_missing_item()]

    deadlines = []
    for d in response.deadlines:
        if d.term and d.term.strip():
            suffix = f"（適用：{d.term.strip()}；{source_note(d.cite)}）"
        else:
            suffix = f"（{source_note(d.cite)}）"
        deadlines.append(_item(d.text + suffix, refs(d.cite), label="期限"))
    contacts = [_item(c.text, refs(c.cite), label="窗口") for c in response.contacts]
    deadline_contact = (deadlines or [_missing_item("期限")]) + (contacts or [_missing_item("窗口")])

    sources = []
    for n, (c, quote) in enumerate(zip(citations, shown_quotes), start=1):
        doc = docs[c.doc_id]
        sources.append(
            {"n": n, "label": clean_text(f"{doc.title}（{doc.version_date}）"), "quote": clean_text(quote)}
        )

    return {
        "kind": "answer",
        "notice": None if stage_selected else NO_STAGE_NOTICE,
        "answer": clean_text(response.answer),
        "sections": [
            {"title": SECTION_NEXT_STEPS, "items": next_steps},
            {"title": SECTION_FORMS, "items": forms},
            {"title": SECTION_DEADLINE_CONTACT, "items": deadline_contact},
        ],
        "sources_title": SECTION_SOURCES,
        "sources": sources,
    }
