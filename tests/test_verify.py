from sop_agent.schema import Citation, Deadline, Item, ModelResponse
from sop_agent.verify import find_original_span, normalize, verify

MIN = 8


def answered(citations, **kw) -> ModelResponse:
    return ModelResponse(
        status="answered",
        answer="請在口試日前備妥文件。",
        citations=citations,
        **kw,
    )


def cite(quote, doc_id="oral-exam", version="2025-09-01") -> Citation:
    return Citation(doc_id=doc_id, version_date=version, quote=quote)


# --- 標準化 ---

def test_normalize_removes_whitespace_and_unifies_width():
    assert normalize("a b\nc　d​e") == "abcde"
    assert normalize("（１）ＡＢ") == "(1)AB"


# --- 通過的情況 ---

def test_verbatim_quote_passes(docs):
    r = verify(answered([cite("備妥下列文件，送交系辦")]), docs, MIN)
    assert r.ok


def test_quote_without_linebreak_passes_when_document_breaks_line(docs):
    # 原文在「14」後面換行；模型回傳的片段沒有換行。內容正確，只差換行位置：通過。
    r = verify(answered([cite("口試申請應於口試日前 14日內，備妥下列文件")]), docs, MIN)
    assert r.ok


def test_quote_with_different_spacing_passes(docs):
    r = verify(answered([cite("口試申請應於 口試日前14 日內，備妥下列文件")]), docs, MIN)
    assert r.ok


def test_english_quote_with_linebreak_difference_passes(docs):
    r = verify(answered([cite("Applicants must submit the form to the department office.")]), docs, MIN)
    assert r.ok


def test_fullwidth_in_quote_halfwidth_in_document_passes_and_shows_document_form(docs):
    # 模型回傳全形的「（１）口試申請表」，文件是半形的「(1) 口試申請表」。
    r = verify(answered([cite("（１）口試申請表（２）論文初稿")]), docs, MIN)
    assert r.ok
    shown = r.shown_quotes[0]
    assert shown == "(1) 口試申請表 (2) 論文初稿"
    assert "（" not in shown and "１" not in shown


def test_shown_quote_is_document_original_not_model_version(docs):
    r = verify(answered([cite("口試申請應於口試日前14日內，備妥下列文件")]), docs, MIN)
    assert r.ok
    assert r.shown_quotes[0] == "口試申請應於口試日前 14\n日內，備妥下列文件"


def test_shown_quote_has_no_leading_or_trailing_blank(docs):
    r = verify(answered([cite("  備妥下列文件，送交系辦  ")]), docs, MIN)
    assert r.ok
    assert r.shown_quotes[0] == r.shown_quotes[0].strip()


def test_find_original_span_returns_first_occurrence():
    body = "申請表申請表申請表\n申請表"
    assert find_original_span(body, "申請表申請表", 4) == "申請表申請表"


def test_multiple_citations_all_valid(docs):
    r = verify(
        answered(
            [cite("備妥下列文件，送交系辦"), cite("請至系統上傳電子檔並列印授權書", "upload", "2025-10-01")],
            next_steps=[Item(text="備文件", cite=[0]), Item(text="上傳", cite=[1])],
            deadlines=[Deadline(text="口試前 14 日", term=None, cite=[0])],
        ),
        docs,
        MIN,
    )
    assert r.ok
    assert len(r.shown_quotes) == 2


# --- 不通過的情況 ---

def test_changed_one_character_fails(docs):
    r = verify(answered([cite("口試申請應於口試日前15日內，備妥下列文件")]), docs, MIN)
    assert not r.ok and r.reason == "quote_not_found"


def test_translated_quote_fails(docs):
    r = verify(answered([cite("Applications must be submitted 14 days before the oral exam")]), docs, MIN)
    assert not r.ok


def test_paraphrased_quote_fails(docs):
    r = verify(answered([cite("口試前兩週要把文件交給系辦")]), docs, MIN)
    assert not r.ok


def test_quote_from_another_document_fails(docs):
    # 片段在 upload 文件裡，但 doc_id 指向 oral-exam
    r = verify(answered([cite("請至系統上傳電子檔並列印授權書", "oral-exam")]), docs, MIN)
    assert not r.ok and r.reason == "quote_not_found"


def test_unknown_doc_id_fails(docs):
    r = verify(answered([cite("備妥下列文件，送交系辦", "no-such-doc")]), docs, MIN)
    assert not r.ok and r.reason == "unknown_doc"


def test_doc_not_in_this_prompt_fails(oral_doc, other_doc):
    # upload 存在於文件庫，但這次 prompt 只放了 oral-exam
    only_oral = {oral_doc.id: oral_doc}
    r = verify(answered([cite("請至系統上傳電子檔並列印授權書", "upload", "2025-10-01")]), only_oral, MIN)
    assert not r.ok and r.reason == "unknown_doc"


def test_version_date_mismatch_fails(docs):
    r = verify(answered([cite("備妥下列文件，送交系辦", version="2024-01-01")]), docs, MIN)
    assert not r.ok and r.reason == "version_mismatch"


def test_quote_shorter_than_minimum_fails(docs):
    r = verify(answered([cite("系辦")]), docs, MIN)
    assert not r.ok


def test_one_bad_citation_voids_whole_answer(docs):
    r = verify(
        answered([cite("備妥下列文件，送交系辦"), cite("這句話文件裡根本沒有出現過")]),
        docs,
        MIN,
    )
    assert not r.ok
    assert r.shown_quotes == ()


def test_cite_index_out_of_range_fails(docs):
    r = verify(
        answered([cite("備妥下列文件，送交系辦")], next_steps=[Item(text="x", cite=[3])]),
        docs,
        MIN,
    )
    assert not r.ok and r.reason == "cite_out_of_range"


def test_item_without_cite_fails(docs):
    r = verify(
        answered([cite("備妥下列文件，送交系辦")], forms=[Item(text="口試申請表", cite=[])]),
        docs,
        MIN,
    )
    assert not r.ok and r.reason == "item_without_cite"


def test_answered_without_citations_fails(docs):
    r = verify(answered([]), docs, MIN)
    assert not r.ok and r.reason == "no_citation"


def test_answered_with_empty_answer_fails(docs):
    resp = ModelResponse(status="answered", answer="  ", citations=[cite("備妥下列文件，送交系辦")])
    assert not verify(resp, docs, MIN).ok


def test_non_answered_status_needs_no_citation(docs):
    assert verify(ModelResponse(status="not_in_documents"), docs, MIN).ok
    assert verify(ModelResponse(status="out_of_scope"), docs, MIN).ok
