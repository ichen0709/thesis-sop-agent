from pathlib import Path

import pytest

from sop_agent.library import LibraryError, load_library

FIXTURE_LIB = Path(__file__).parent / "fixtures" / "library_ok"

GOOD_HEADER = {
    "id": "sample-doc",
    "title": "範例文件",
    "source": "系辦（測試用）",
    "version_date": "2025-09-01",
    "public": "true",
}


def write_doc(directory: Path, name: str = "sample-doc", body: str = "內文。\n", **overrides) -> Path:
    """寫一份測試文件；欄位值給 None 代表刪掉該欄位。"""
    fields = {**GOOD_HEADER, **overrides}
    lines = [f"{k}: {v}" for k, v in fields.items() if v is not None]
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.md"
    path.write_text("---\n" + "\n".join(lines) + "\n---\n" + body, encoding="utf-8")
    return path


def load_error(directory: Path) -> LibraryError:
    with pytest.raises(LibraryError) as e:
        load_library(directory)
    return e.value


# --- 正常載入 ---

def test_loads_fixture_library():
    lib = load_library(FIXTURE_LIB)
    assert {d.id for d in lib.docs} == {"thesis-oral-exam-sop", "thesis-upload-guide", "general-faq"}
    doc = lib.by_id["thesis-oral-exam-sop"]
    assert doc.title == "論文口試辦理流程（測試用）"
    assert doc.version_date == "2025-09-01"
    assert doc.stages == ("口試前", "口試後")
    assert lib.by_id["general-faq"].stages == ()
    assert lib.by_id["thesis-upload-guide"].stages == ("論文上傳", "離校")


def test_body_does_not_contain_front_matter():
    body = load_library(FIXTURE_LIB).by_id["thesis-oral-exam-sop"].body
    assert "version_date" not in body and "title:" not in body and "---" not in body
    assert body.startswith("口試申請應於口試日前 14")


def test_inline_comment_in_header_is_ignored():
    doc = load_library(FIXTURE_LIB).by_id["thesis-oral-exam-sop"]
    assert doc.id == "thesis-oral-exam-sop"  # 檔頭裡「# 與檔名相同」不會變成 id 的一部分


def test_utf8_bom_is_accepted(tmp_path):
    path = write_doc(tmp_path)
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    assert load_library(tmp_path).by_id["sample-doc"].title == "範例文件"


def test_crlf_line_endings_are_accepted(tmp_path):
    path = write_doc(tmp_path, body="第一行\n第二行\n")
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    doc = load_library(tmp_path).by_id["sample-doc"]
    assert "第二行" in doc.body and "version_date" not in doc.body


def test_documents_in_subfolders_are_loaded(tmp_path):
    write_doc(tmp_path / "sub", name="nested-doc", id="nested-doc")
    assert "nested-doc" in load_library(tmp_path).by_id


def test_non_markdown_files_are_ignored(tmp_path):
    (tmp_path / ".gitkeep").write_text("", encoding="utf-8")
    (tmp_path / "note.txt").write_text("不是文件", encoding="utf-8")
    assert load_library(tmp_path).docs == ()


def test_to_source_doc_bridges_to_stage_one_types():
    lib = load_library(FIXTURE_LIB)
    src = lib.by_id["thesis-oral-exam-sop"].to_source_doc()
    assert (src.id, src.version_date) == ("thesis-oral-exam-sop", "2025-09-01")
    assert src.body == lib.by_id["thesis-oral-exam-sop"].body
    assert set(lib.source_docs()) == set(lib.by_id)


# --- 檔頭缺欄位 ---

@pytest.mark.parametrize("field", ["id", "title", "source", "version_date", "public"])
def test_missing_required_field_names_the_file(tmp_path, field):
    write_doc(tmp_path, **{field: None})
    err = load_error(tmp_path)
    assert err.problems and err.problems[0][0] == "sample-doc.md"
    assert f"缺少欄位 {field}" in str(err)
    assert "sample-doc.md" in str(err)


@pytest.mark.parametrize("field", ["title", "source"])
def test_empty_required_field_is_rejected(tmp_path, field):
    write_doc(tmp_path, **{field: '""'})
    assert "sample-doc.md" in str(load_error(tmp_path))


def test_missing_stages_means_all_stages(tmp_path):
    write_doc(tmp_path)
    assert load_library(tmp_path).by_id["sample-doc"].stages == ()


def test_unknown_field_is_rejected_to_catch_typos(tmp_path):
    # 例如把 stages 打成 stage，文件就會悄悄變成所有階段都適用
    write_doc(tmp_path, stage="[口試前]")
    assert "不認得的欄位 stage" in str(load_error(tmp_path))


def test_no_front_matter_is_rejected(tmp_path):
    (tmp_path / "plain.md").write_text("只有內文，沒有檔頭\n", encoding="utf-8")
    err = load_error(tmp_path)
    assert err.problems == [("plain.md", "沒有檔頭")]


def test_unclosed_front_matter_is_rejected(tmp_path):
    (tmp_path / "open.md").write_text("---\nid: open\ntitle: x\n內文\n", encoding="utf-8")
    assert "沒有結尾" in str(load_error(tmp_path))


def test_front_matter_not_at_first_line_is_rejected(tmp_path):
    (tmp_path / "late.md").write_text("\n---\nid: late\n---\n內文\n", encoding="utf-8")
    assert "late.md" in str(load_error(tmp_path))


def test_invalid_yaml_header_is_rejected(tmp_path):
    (tmp_path / "bad.md").write_text("---\nid: [unclosed\n---\n內文\n", encoding="utf-8")
    assert "bad.md" in str(load_error(tmp_path))


@pytest.mark.parametrize("bad", ["x, y", "[口試前, ", "{a: b}"])
def test_stages_must_be_a_list(tmp_path, bad):
    write_doc(tmp_path, stages=bad)
    assert "sample-doc.md" in str(load_error(tmp_path))


# --- 日期格式 ---

@pytest.mark.parametrize(
    "bad",
    ["2025/09/01", "2025-9-1", "20250901", "2025-13-01", "2025-02-30", "114-09-01", "九月一日", "2025-09-01T10:00", "yesterday"],
)
def test_bad_version_date_is_rejected_and_names_the_file(tmp_path, bad):
    write_doc(tmp_path, version_date=f'"{bad}"')
    err = load_error(tmp_path)
    assert err.problems == [("sample-doc.md", "version_date 格式錯誤（需要 YYYY-MM-DD 的真實日期）")]


def test_valid_date_is_accepted_and_kept_as_text(tmp_path):
    write_doc(tmp_path, version_date="2024-02-29")  # 閏年
    assert load_library(tmp_path).by_id["sample-doc"].version_date == "2024-02-29"


# --- public ---

@pytest.mark.parametrize("bad", ["yes", "no", "True", "1", "maybe"])
def test_public_must_be_true_or_false(tmp_path, bad):
    write_doc(tmp_path, public=bad)
    assert "public 只能是 true 或 false" in str(load_error(tmp_path))


def test_private_document_is_not_loaded(tmp_path):
    write_doc(tmp_path, name="open-doc", id="open-doc")
    write_doc(tmp_path, name="secret-doc", id="secret-doc", public="false", body="內部暗號 TOP-SECRET-123\n")
    lib = load_library(tmp_path)
    assert set(lib.by_id) == {"open-doc"}
    assert lib.skipped_private == 1


def test_private_document_body_is_not_kept_anywhere(tmp_path):
    write_doc(tmp_path, name="secret-doc", id="secret-doc", public="false", body="內部暗號 TOP-SECRET-123\n")
    lib = load_library(tmp_path)
    dumped = repr(lib) + repr([d.to_source_doc() for d in lib.docs])
    assert "TOP-SECRET-123" not in dumped


def test_fixture_private_document_is_skipped():
    lib = load_library(FIXTURE_LIB)
    assert "internal-notes" not in lib.by_id
    assert lib.skipped_private == 1
    assert all("NOT-FOR-STUDENTS" not in d.body for d in lib.docs)


def test_private_document_header_is_still_validated(tmp_path):
    write_doc(tmp_path, name="secret-doc", id="secret-doc", public="false", version_date="2025/09/01")
    assert "secret-doc.md" in str(load_error(tmp_path))


# --- id 與檔名、id 重複 ---

def test_id_must_match_filename(tmp_path):
    write_doc(tmp_path, name="actual-name", id="other-name")
    err = load_error(tmp_path)
    assert err.problems == [("actual-name.md", "id 與檔名不一致")]


@pytest.mark.parametrize("bad_id", ["有中文", "has space", "-leading", "a/b", "a.b"])
def test_id_with_invalid_characters_is_rejected(tmp_path, bad_id):
    write_doc(tmp_path, name="whatever", id=f'"{bad_id}"')
    assert "whatever.md" in str(load_error(tmp_path))


def test_allowed_id_characters(tmp_path):
    write_doc(tmp_path, name="Thesis_Oral-2", id="Thesis_Oral-2")
    assert "Thesis_Oral-2" in load_library(tmp_path).by_id


def test_duplicate_id_is_rejected_and_names_both_files(tmp_path):
    write_doc(tmp_path / "a", name="same-id", id="same-id")
    write_doc(tmp_path / "b", name="same-id", id="same-id")
    err = load_error(tmp_path)
    assert any("重複" in p for _, p in err.problems)
    assert "a/same-id.md" in str(err) and "b/same-id.md" in str(err)


def test_duplicate_id_with_a_private_document_is_also_rejected(tmp_path):
    write_doc(tmp_path / "a", name="same-id", id="same-id")
    write_doc(tmp_path / "b", name="same-id", id="same-id", public="false")
    assert "重複" in str(load_error(tmp_path))


def test_all_problems_are_reported_at_once(tmp_path):
    write_doc(tmp_path, name="doc-a", id="doc-a", source=None)
    write_doc(tmp_path, name="doc-b", id="doc-b", version_date='"2025/01/01"')
    err = load_error(tmp_path)
    assert {name for name, _ in err.problems} == {"doc-a.md", "doc-b.md"}


def test_error_message_has_no_file_content(tmp_path):
    write_doc(tmp_path, source=None, body="機密內文 SECRET-BODY-777\n")
    assert "SECRET-BODY-777" not in str(load_error(tmp_path))


# --- 封存資料夾 ---

def test_archive_folder_is_not_read():
    # 封存資料夾裡有 id 重複的舊版與沒有檔頭的壞檔；如果被讀到就會報錯
    lib = load_library(FIXTURE_LIB)
    assert lib.by_id["thesis-oral-exam-sop"].version_date == "2025-09-01"


# --- 最後更新日期 ---

def test_last_updated_is_the_latest_version_date():
    assert load_library(FIXTURE_LIB).last_updated == "2025-10-01"


def test_last_updated_ignores_private_documents():
    # fixture 裡不公開的文件是 2025-12-31，不能算進去
    assert load_library(FIXTURE_LIB).last_updated != "2025-12-31"


def test_last_updated_changes_automatically_when_a_newer_document_is_added(tmp_path):
    write_doc(tmp_path, name="old-doc", id="old-doc", version_date="2025-03-01")
    assert load_library(tmp_path).last_updated == "2025-03-01"
    write_doc(tmp_path, name="new-doc", id="new-doc", version_date="2025-11-15")
    assert load_library(tmp_path).last_updated == "2025-11-15"


def test_last_updated_follows_a_replaced_document(tmp_path):
    write_doc(tmp_path, version_date="2025-03-01")
    assert load_library(tmp_path).last_updated == "2025-03-01"
    write_doc(tmp_path, version_date="2025-06-01")  # 系辦給新版，替換檔案
    assert load_library(tmp_path).last_updated == "2025-06-01"


def test_last_updated_is_none_for_empty_library(tmp_path):
    assert load_library(tmp_path).last_updated is None


# --- 文件庫為空 ---

def test_empty_folder_does_not_crash(tmp_path):
    lib = load_library(tmp_path)
    assert lib.docs == () and lib.skipped_private == 0


def test_folder_with_only_gitkeep_does_not_crash(tmp_path):
    (tmp_path / ".gitkeep").write_text("", encoding="utf-8")
    assert load_library(tmp_path).docs == ()


def test_missing_folder_does_not_crash(tmp_path):
    assert load_library(tmp_path / "does-not-exist").docs == ()


def test_only_private_documents_gives_empty_library(tmp_path):
    write_doc(tmp_path, public="false")
    lib = load_library(tmp_path)
    assert lib.docs == () and lib.skipped_private == 1


def test_real_library_folder_is_empty_except_gitkeep():
    real = Path(__file__).resolve().parents[1] / "library"
    assert [p.name for p in real.rglob("*") if p.is_file()] in ([], [".gitkeep"])
    assert load_library(real).docs == ()


# --- 檢查指令 ---

def test_cli_reports_ok(capsys):
    from sop_agent import library

    import sys

    argv = sys.argv
    sys.argv = ["library", str(FIXTURE_LIB)]
    try:
        assert library.main() == 0
    finally:
        sys.argv = argv
    out = capsys.readouterr().out
    assert "已載入 3 份" in out and "略過不公開 1 份" in out and "2025-10-01" in out


def test_cli_reports_errors_with_nonzero_exit(tmp_path, capsys):
    from sop_agent import library

    import sys

    write_doc(tmp_path, source=None)
    argv = sys.argv
    sys.argv = ["library", str(tmp_path)]
    try:
        assert library.main() == 1
    finally:
        sys.argv = argv
    assert "sample-doc.md" in capsys.readouterr().out
