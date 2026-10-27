import json

import pytest

from sop_agent import cards
from sop_agent.cards import (
    DISCLAIMER,
    MISSING_TEXT,
    NO_INFO_TEXT,
    NO_STAGE_NOTICE,
    OUT_OF_SCOPE_TEXT,
    UI_TEXT,
    UNAVAILABLE_TEXT,
    build_answer_card,
    clean_text,
    message_card,
)
from sop_agent.schema import Citation, Deadline, Item, ModelResponse


def citation(doc_id="oral-exam", version="2025-09-01") -> Citation:
    return Citation(doc_id=doc_id, version_date=version, quote="略")


def full_response() -> ModelResponse:
    return ModelResponse(
        status="answered",
        answer="請備妥文件。",
        next_steps=[Item(text="備妥文件", cite=[0])],
        forms=[Item(text="口試申請表", cite=[0, 1])],
        deadlines=[Deadline(text="口試前 14 日", term="114 學年度第 1 學期", cite=[0])],
        contacts=[Item(text="系辦 02-0000-0000", cite=[1])],
        citations=[citation(), citation("upload", "2025-10-01")],
    )


def build(resp=None, stage_selected=True, docs=None, quotes=("原文一", "原文二")):
    return build_answer_card(resp or full_response(), quotes, docs, stage_selected)


@pytest.fixture
def card(docs):
    return build(docs=docs)


def section(card, title):
    return next(s for s in card["sections"] if s["title"] == title)


# --- 固定文字 ---

def test_messages_are_distinct_and_mention_the_office():
    assert "文件中沒有這項資訊" in NO_INFO_TEXT and "請洽系辦" in NO_INFO_TEXT
    assert "不在服務範圍內" in OUT_OF_SCOPE_TEXT and "請洽系辦" in OUT_OF_SCOPE_TEXT
    assert UNAVAILABLE_TEXT == "現在無法回答，請稍後再試，或直接洽系辦。"
    assert len({NO_INFO_TEXT, OUT_OF_SCOPE_TEXT, UNAVAILABLE_TEXT}) == 3


def test_disclaimer_is_the_agreed_wording():
    assert DISCLAIMER == "本回答依系辦文件整理，僅供參考；正式規定以系辦公告為準。"


def test_no_stage_notice_is_the_agreed_wording():
    assert NO_STAGE_NOTICE == "你還沒選目前階段，以下回答是依整個流程的文件整理的"


def test_hint_text_is_the_agreed_wording():
    assert UI_TEXT["hint"] == "每次提問是獨立的，請把完整情況寫在問題裡"
    assert UI_TEXT["waiting"] == "正在查文件…"
    assert UI_TEXT["too_long"] == "問題太長，請縮短"
    assert UI_TEXT["placeholder_label"] == "範例資料，非正式規定"


@pytest.mark.parametrize(
    "kind, text",
    [("no_info", NO_INFO_TEXT), ("out_of_scope", OUT_OF_SCOPE_TEXT), ("unavailable", UNAVAILABLE_TEXT)],
)
def test_message_cards(kind, text):
    assert message_card(kind) == {"kind": kind, "message": text}


def test_message_cards_have_no_answer_fields():
    for kind in ("no_info", "out_of_scope", "unavailable"):
        c = message_card(kind)
        assert set(c) == {"kind", "message"}


# --- 答案卡：四欄 ---

def test_answer_card_has_all_four_parts(card):
    assert card["kind"] == "answer"
    assert [s["title"] for s in card["sections"]] == ["下一步", "相關表單", "期限與窗口"]
    assert card["sources_title"] == "出處"
    assert card["answer"] == "請備妥文件。"


def test_missing_fields_show_not_stated(docs):
    resp = ModelResponse(status="answered", answer="答", citations=[citation()])
    c = build(resp, docs=docs)
    for title in ("下一步", "相關表單"):
        (item,) = section(c, title)["items"]
        assert item["text"] == MISSING_TEXT and item["missing"] is True
    labels = {i["label"]: i for i in section(c, "期限與窗口")["items"]}
    assert labels["期限"]["text"] == MISSING_TEXT and labels["窗口"]["text"] == MISSING_TEXT


def test_only_the_missing_half_of_deadline_and_contact_is_marked(card):
    items = section(card, "期限與窗口")["items"]
    assert [i["label"] for i in items] == ["期限", "窗口"]
    assert all(not i["missing"] for i in items)

    resp = ModelResponse(
        status="answered", answer="答", citations=[citation()],
        deadlines=[Deadline(text="期限甲", cite=[0])],
    )
    items = section(build(resp, docs={"oral-exam": _doc("oral-exam")}), "期限與窗口")["items"]
    by_label = {i["label"]: i for i in items}
    assert by_label["期限"]["missing"] is False
    assert by_label["窗口"]["text"] == MISSING_TEXT and by_label["窗口"]["missing"] is True


def _doc(doc_id, title="口試辦理流程（測試用）", version="2025-09-01"):
    from sop_agent.schema import SourceDoc

    return SourceDoc(doc_id, title, version, "內文")


# --- 答案卡：期限標示適用學期與版本 ---

def test_deadline_shows_term_and_cited_document_version(card):
    deadline = section(card, "期限與窗口")["items"][0]
    assert deadline["label"] == "期限"
    assert "口試前 14 日" in deadline["text"]
    assert "適用：114 學年度第 1 學期" in deadline["text"]
    assert "《口試辦理流程（測試用）》2025-09-01 版" in deadline["text"]


def test_deadline_without_term_still_shows_version(docs):
    resp = ModelResponse(
        status="answered", answer="答", citations=[citation()],
        deadlines=[Deadline(text="口試前 14 日", term=None, cite=[0])],
    )
    text = section(build(resp, docs=docs), "期限與窗口")["items"][0]["text"]
    assert "適用" not in text
    assert "2025-09-01 版" in text


def test_deadline_citing_two_documents_lists_both_versions(docs):
    resp = ModelResponse(
        status="answered", answer="答", citations=[citation(), citation("upload", "2025-10-01")],
        deadlines=[Deadline(text="期限", cite=[0, 1])],
    )
    text = section(build(resp, docs=docs), "期限與窗口")["items"][0]["text"]
    assert "2025-09-01 版" in text and "2025-10-01 版" in text


def test_blank_term_is_treated_as_no_term(docs):
    resp = ModelResponse(
        status="answered", answer="答", citations=[citation()],
        deadlines=[Deadline(text="期限", term="   ", cite=[0])],
    )
    assert "適用" not in section(build(resp, docs=docs), "期限與窗口")["items"][0]["text"]


# --- 答案卡：出處與編號 ---

def test_sources_show_title_version_and_document_original_quote(card):
    assert card["sources"] == [
        {"n": 1, "label": "口試辦理流程（測試用）（2025-09-01）", "quote": "原文一"},
        {"n": 2, "label": "論文上傳（測試用）（2025-10-01）", "quote": "原文二"},
    ]


def test_items_point_to_source_numbers(card):
    assert section(card, "下一步")["items"][0]["refs"] == [1]
    assert section(card, "相關表單")["items"][0]["refs"] == [1, 2]
    assert section(card, "期限與窗口")["items"][1]["refs"] == [2]


def test_missing_items_have_no_refs(docs):
    resp = ModelResponse(status="answered", answer="答", citations=[citation()])
    assert section(build(resp, docs=docs), "下一步")["items"][0]["refs"] == []


# --- 階段提醒 ---

def test_notice_shown_when_no_stage_selected(docs):
    assert build(docs=docs, stage_selected=False)["notice"] == NO_STAGE_NOTICE


def test_no_notice_when_stage_selected(docs):
    assert build(docs=docs, stage_selected=True)["notice"] is None


# --- 清理與輸出 ---

def test_clean_text_removes_control_characters_but_keeps_newlines():
    assert clean_text("a\x00b\x07c\x1bd\x7fe") == "abcde"
    assert clean_text("第一行\r\n第二行\r第三行\t結尾") == "第一行\n第二行\n第三行\t結尾"
    assert clean_text("a b") == "ab"


def test_clean_text_does_not_touch_html():
    evil = '<script>alert("x")</script><img src=x onerror=alert(1)>&lt;'
    assert clean_text(evil) == evil


def test_card_strings_are_cleaned(docs):
    resp = ModelResponse(
        status="answered", answer="答\x00案", citations=[citation()],
        next_steps=[Item(text="步\x07驟", cite=[0])],
    )
    c = build(resp, docs=docs, quotes=("片\x1b段",))
    assert c["answer"] == "答案"
    assert section(c, "下一步")["items"][0]["text"] == "步驟"
    assert c["sources"][0]["quote"] == "片段"


def test_html_in_model_output_is_kept_as_plain_text(docs):
    evil = "<script>alert(1)</script>"
    resp = ModelResponse(status="answered", answer=evil, citations=[citation()],
                         forms=[Item(text=evil, cite=[0])])
    c = build(resp, docs=docs, quotes=(evil,))
    assert c["answer"] == evil
    assert section(c, "相關表單")["items"][0]["text"] == evil
    assert c["sources"][0]["quote"] == evil


def test_card_is_json_serialisable(card):
    assert json.loads(json.dumps(card, ensure_ascii=False)) == card


def test_cards_module_has_the_disclaimer_in_a_single_place():
    import re
    from pathlib import Path

    src = Path(cards.__file__).read_text(encoding="utf-8")
    assert len(re.findall(r"僅供參考", src)) == 1
