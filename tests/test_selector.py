from pathlib import Path

import pytest

from sop_agent.library import Library, LibraryDoc, load_library
from sop_agent.schema import Citation, ModelResponse
from sop_agent.selector import SelectionStatus, narrow_to_budget, select_documents
from sop_agent.verify import verify

FIXTURE_LIB = Path(__file__).parent / "fixtures" / "library_ok"


@pytest.fixture
def lib() -> Library:
    return load_library(FIXTURE_LIB)


def ids(selection) -> set[str]:
    return {d.id for d in selection.docs}


# --- 依階段選文件 ---

def test_no_stage_selects_all_loaded_documents(lib):
    s = select_documents(lib, None)
    assert s.status is SelectionStatus.OK
    assert ids(s) == {"thesis-oral-exam-sop", "thesis-upload-guide", "general-faq"}


def test_empty_string_stage_means_no_stage(lib):
    assert ids(select_documents(lib, "")) == ids(select_documents(lib, None))


def test_stage_selects_matching_and_all_stage_documents(lib):
    s = select_documents(lib, "口試前")
    assert s.status is SelectionStatus.OK
    assert ids(s) == {"thesis-oral-exam-sop", "general-faq"}  # general-faq 的 stages 為空，一律包含


def test_stage_excludes_documents_for_other_stages(lib):
    assert "thesis-oral-exam-sop" not in ids(select_documents(lib, "離校"))
    assert ids(select_documents(lib, "離校")) == {"thesis-upload-guide", "general-faq"}


def test_document_listing_several_stages_matches_each_of_them(lib):
    assert "thesis-upload-guide" in ids(select_documents(lib, "論文上傳"))
    assert "thesis-upload-guide" in ids(select_documents(lib, "離校"))


def test_private_document_is_never_selected(lib):
    for stage in (None, "口試前", "離校"):
        assert "internal-notes" not in ids(select_documents(lib, stage))


def test_stage_with_no_applicable_documents(tmp_path):
    only_oral = Library(docs=(doc("only-oral", stages=("口試前",)),))
    s = select_documents(only_oral, "離校")
    assert s.status is SelectionStatus.NO_DOCS_FOR_STAGE
    assert s.docs == ()


def doc(doc_id="d1", body="內文", stages=(), version="2025-01-01") -> LibraryDoc:
    return LibraryDoc(id=doc_id, title="標題", source="來源", version_date=version,
                      stages=stages, body=body, path=f"{doc_id}.md")


# --- 文件庫為空 ---

def test_empty_library_gives_explicit_status_without_crashing():
    s = select_documents(Library(), None)
    assert s.status is SelectionStatus.LIBRARY_EMPTY
    assert s.docs == () and s.by_id() == {}


def test_empty_library_with_stage_is_still_library_empty():
    assert select_documents(Library(), "口試前").status is SelectionStatus.LIBRARY_EMPTY


def test_library_with_only_private_documents_is_empty(tmp_path):
    (tmp_path / "secret.md").write_text(
        "---\nid: secret\ntitle: t\nsource: s\nversion_date: 2025-01-01\npublic: false\n---\n內文\n",
        encoding="utf-8",
    )
    assert select_documents(load_library(tmp_path), None).status is SelectionStatus.LIBRARY_EMPTY


def test_empty_real_library_folder_gives_library_empty():
    real = Path(__file__).resolve().parents[1] / "library"
    assert select_documents(load_library(real), None).status is SelectionStatus.LIBRARY_EMPTY


# --- 超量（尚未實作挑段落） ---

def test_over_budget_returns_no_documents():
    big = Library(docs=(doc("a", body="字" * 600), doc("b", body="字" * 600)))
    s = select_documents(big, None, max_prompt_chars=1000)
    assert s.status is SelectionStatus.OVER_BUDGET
    assert s.docs == ()  # 不回傳過量的文件，避免上層忘了檢查就送出


def test_within_budget_is_ok():
    small = Library(docs=(doc("a", body="字" * 400), doc("b", body="字" * 400)))
    assert select_documents(small, None, max_prompt_chars=1000).status is SelectionStatus.OK


def test_budget_of_zero_means_no_limit():
    big = Library(docs=(doc("a", body="字" * 100000),))
    assert select_documents(big, None, max_prompt_chars=0).status is SelectionStatus.OK


def test_budget_counts_only_selected_documents():
    lib2 = Library(docs=(doc("a", body="字" * 900, stages=("離校",)), doc("b", body="字" * 100, stages=("口試前",))))
    assert select_documents(lib2, "口試前", max_prompt_chars=500).status is SelectionStatus.OK
    assert select_documents(lib2, "離校", max_prompt_chars=500).status is SelectionStatus.OVER_BUDGET


def test_narrowing_to_budget_is_explicitly_not_implemented():
    with pytest.raises(NotImplementedError):
        narrow_to_budget()


# --- 與階段 1 的銜接：登記表可被 verify.py 用來核對 ---

def response(doc_id, quote, version="2025-09-01") -> ModelResponse:
    return ModelResponse(
        status="answered",
        answer="請備妥文件。",
        citations=[Citation(doc_id=doc_id, version_date=version, quote=quote)],
    )


def test_selection_by_id_feeds_verify_and_a_body_quote_passes(lib):
    s = select_documents(lib, "口試前")
    r = verify(response("thesis-oral-exam-sop", "口試申請應於口試日前14日內，備妥下列文件"), s.by_id(), 8)
    assert r.ok
    assert r.shown_quotes[0] == "口試申請應於口試日前 14\n日內，備妥下列文件"


def test_quote_that_only_appears_in_the_header_fails(lib):
    # 檔頭不算內文：title、source 的文字不能拿來當出處片段
    s = select_documents(lib, "口試前")
    for header_text in ("論文口試辦理流程（測試用）", "測試用假資料，非系辦正式文件"):
        assert not verify(response("thesis-oral-exam-sop", header_text), s.by_id(), 8).ok


def test_version_date_is_checked_against_the_library(lib):
    s = select_documents(lib, "口試前")
    r = verify(response("thesis-oral-exam-sop", "備妥下列文件，送交系辦", version="2024-01-01"), s.by_id(), 8)
    assert not r.ok and r.reason == "version_mismatch"


def test_document_not_selected_for_this_stage_cannot_be_cited(lib):
    # 選了「離校」階段，口試文件沒有放進這次的 prompt，所以不能被引用
    s = select_documents(lib, "離校")
    r = verify(response("thesis-oral-exam-sop", "備妥下列文件，送交系辦"), s.by_id(), 8)
    assert not r.ok and r.reason == "unknown_doc"


def test_private_document_cannot_be_cited(lib):
    s = select_documents(lib, None)
    r = verify(response("internal-notes", "這份文件不可公開，不可以被載入", "2025-12-31"), s.by_id(), 8)
    assert not r.ok and r.reason == "unknown_doc"
