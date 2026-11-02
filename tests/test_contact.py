"""系所聯絡方式：data/contact.json 的載入、卡片上的顯示、防護 5 與「不進 prompt」。"""

import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sop_agent.applog import ErrorType
from sop_agent.ask import Stages, print_startup_notes
from sop_agent.cards import (
    CONTACT_CHECKED_PREFIX,
    CONTACT_HINT,
    CONTACT_TITLE,
    NO_INFO_TEXT,
    OUT_OF_SCOPE_TEXT,
    UNAVAILABLE_TEXT,
    contact_block,
    message_card,
)
from sop_agent.contact import Contact, ContactLoad, Email, Phone, load_contact
from sop_agent.library import Library, load_library
from sop_agent.runner import RunnerError
from sop_agent.server import create_app

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
BASE = "http://127.0.0.1:8000"

GOOD = {
    "phones": [
        {"number": "03-111-0001", "for": ["甲班", "乙班（Class B）"]},
        {"number": "03-111-0002", "for": ["丙班"]},
    ],
    "emails": [
        {"address": "a@example.test", "unit": "甲單位"},
        {"address": "b@example.test", "unit": "乙單位"},
    ],
    "location": "測試樓 101 室",
    "office_hours": "",
    "sources": ["https://example.test/a", "https://example.test/b"],
    "checked_on": "2026-01-02",
}


def write(base: Path, data) -> Path:
    """在 base/data 寫入 contact.json，回傳資料夾。"""
    d = base / "data"
    d.mkdir(exist_ok=True)
    (d / "contact.json").write_text(
        data if isinstance(data, str) else json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    return d


def mutated(**changes):
    data = copy.deepcopy(GOOD)
    data.update(changes)
    return data


# --- 載入 ---

def test_valid_file_loads(tmp_path):
    result = load_contact(write(tmp_path, GOOD))
    assert result.notes == ()
    c = result.contact
    assert c.phones[0] == Phone("03-111-0001", ("甲班", "乙班（Class B）"))
    assert c.emails[1] == Email("b@example.test", "乙單位")
    assert c.location == "測試樓 101 室" and c.office_hours == ""
    assert c.sources == ("https://example.test/a", "https://example.test/b")
    assert c.checked_on == "2026-01-02"


def test_shipped_contact_json_is_valid():
    """出廠的 data/contact.json 必須能通過載入（不比對號碼，之後改號碼不會害測試壞掉）。"""
    result = load_contact(ROOT / "data")
    assert result.notes == (), result.notes
    c = result.contact
    assert c is not None and c.phones and c.emails and c.sources and c.checked_on
    assert c.office_hours == ""  # 辦公時間還沒確認，不猜


def test_missing_file_means_no_contact_and_a_note(tmp_path):
    result = load_contact(tmp_path / "data")
    assert result.contact is None
    assert len(result.notes) == 1 and "contact.json" in result.notes[0]


@pytest.mark.parametrize(
    "bad",
    [
        "{不是 json",
        "[]",
        '"字串"',
        "",
        mutated(phones="03-111-0001"),
        mutated(phones=[{"number": "03-111-0001"}]),
        mutated(phones=[{"number": "03-111-0001", "for": []}]),
        mutated(phones=[{"number": "03-111-0001", "for": [""]}]),
        mutated(phones=[{"number": "abc", "for": ["甲班"]}]),
        mutated(phones=[{"number": "03-111-0001", "for": ["甲班"], "extra": 1}]),
        mutated(emails=[{"address": "不是信箱", "unit": "甲"}]),
        mutated(emails=[{"address": "a@example.test", "unit": ""}]),
        mutated(emails=[{"address": "a b@example.test", "unit": "甲"}]),
        mutated(phones=[], emails=[]),
        mutated(location=123),
        mutated(office_hours=["一到五"]),
        mutated(sources=[]),
        mutated(sources=["ftp://example.test"]),
        mutated(sources="https://example.test"),
        mutated(checked_on="2026-13-40"),
        mutated(checked_on="20260102"),
        mutated(checked_on=20260102),
        mutated(unknown_field="x"),
        mutated(location="長" * 201),
    ],
    ids=lambda v: str(v)[:40],
)
def test_any_problem_means_the_whole_file_is_not_used(tmp_path, bad):
    result = load_contact(write(tmp_path, bad))
    assert result.contact is None
    assert result.notes  # 啟動時要有說明


def test_one_bad_item_drops_the_whole_file_not_just_that_item(tmp_path):
    data = mutated(emails=[GOOD["emails"][0], {"address": "壞的", "unit": "乙單位"}])
    assert load_contact(write(tmp_path, data)).contact is None


def test_notes_contain_field_names_but_never_file_content(tmp_path):
    data = mutated(phones=[{"number": "秘密電話ZZZ", "for": ["甲班"]}], location="秘密地點QQQ")
    result = load_contact(write(tmp_path, data))
    assert result.contact is None
    text = "\n".join(result.notes)
    assert "phones[0].number" in text
    assert "秘密電話ZZZ" not in text and "秘密地點QQQ" not in text


def test_utf8_bom_is_accepted(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    (d / "contact.json").write_bytes(b"\xef\xbb\xbf" + json.dumps(GOOD).encode("utf-8"))
    assert load_contact(d).contact is not None


def test_startup_notes_go_to_terminal_only(tmp_path, capsys):
    print_startup_notes(Library(), Stages(), load_contact(tmp_path / "data"))
    assert "contact.json" in capsys.readouterr().err
    print_startup_notes(Library(), Stages(), load_contact(write(tmp_path, GOOD)))
    assert "contact" not in capsys.readouterr().err


# --- 卡片上的顯示 ---

def good_contact(tmp_path) -> Contact:
    return load_contact(write(tmp_path, GOOD)).contact


def test_block_lists_every_item_with_its_audience_or_unit(tmp_path):
    block = contact_block(good_contact(tmp_path))
    assert block["title"] == CONTACT_TITLE == "系所聯絡方式"
    assert block["hint"] == CONTACT_HINT
    assert block["lines"] == [
        "電話 03-111-0001：甲班、乙班（Class B）",
        "電話 03-111-0002：丙班",
        "電子郵件 a@example.test：甲單位",
        "電子郵件 b@example.test：乙單位",
        "地點：測試樓 101 室",
    ]
    assert block["checked"] == CONTACT_CHECKED_PREFIX + "2026-01-02"


def test_empty_office_hours_line_is_not_shown_and_filled_one_is(tmp_path):
    block = contact_block(good_contact(tmp_path))
    assert not any("辦公時間" in line for line in block["lines"])
    filled = load_contact(write(tmp_path, mutated(office_hours="週一至週五 9:00-17:00"))).contact
    assert "辦公時間：週一至週五 9:00-17:00" in contact_block(filled)["lines"]


def test_empty_location_line_is_not_shown(tmp_path):
    c = load_contact(write(tmp_path, mutated(location=""))).contact
    assert not any(line.startswith("地點") for line in contact_block(c)["lines"])


def test_source_urls_are_never_shown(tmp_path):
    text = json.dumps(contact_block(good_contact(tmp_path)), ensure_ascii=False)
    assert "example.test/a" not in text and "http" not in text


def test_block_has_no_links(tmp_path):
    text = json.dumps(contact_block(good_contact(tmp_path)), ensure_ascii=False).lower()
    for bad in ("mailto:", "tel:", "<", "href"):
        assert bad not in text


def test_no_contact_gives_no_block_and_unchanged_cards():
    assert contact_block(None) is None
    for kind, text in (
        ("no_info", NO_INFO_TEXT),
        ("out_of_scope", OUT_OF_SCOPE_TEXT),
        ("unavailable", UNAVAILABLE_TEXT),
    ):
        assert message_card(kind) == {"kind": kind, "message": text}
        assert message_card(kind, None) == {"kind": kind, "message": text}


@pytest.mark.parametrize("kind", ["no_info", "out_of_scope", "unavailable"])
def test_three_message_cards_carry_the_contact(tmp_path, kind):
    block = contact_block(good_contact(tmp_path))
    card = message_card(kind, block)
    assert card["kind"] == kind and card["contact"] == block


def test_control_characters_are_cleaned(tmp_path):
    c = load_contact(write(tmp_path, mutated(location="A\x00B\x07C室"))).contact
    assert "地點：ABC室" in contact_block(c)["lines"]


def test_html_in_contact_stays_plain_text_data(tmp_path):
    evil = "<script>alert(1)</script>"
    c = load_contact(write(tmp_path, mutated(location=evil))).contact
    assert f"地點：{evil}" in contact_block(c)["lines"]  # 原樣當文字交給前端；前端只用 textContent


def test_shipped_file_apostrophe_and_fullwidth_brackets_survive_clean_text():
    """出廠 data/contact.json 的 Int'l 撇號與全形括號，經過 clean_text 後仍完整顯示。"""
    lines = contact_block(load_contact(ROOT / "data").contact)["lines"]
    assert any("國際生（Int'l students）" in line for line in lines)
    assert any("碩士班（Master Program）" in line and "博士班（Ph.D. Program）" in line for line in lines)
    assert any(line.startswith("電話 03-890-3012：碩專 MBA、") for line in lines)


# --- 整合：/api/meta、/api/ask ---

NOT_IN_DOCS = {
    "status": "not_in_documents", "answer": "", "next_steps": [], "forms": [],
    "deadlines": [], "contacts": [], "citations": [],
}


class StubRunner:
    def __init__(self, output=None, error=None):
        self.output, self.error, self.prompts = output, error, []

    def run(self, prompt, system_prompt):
        self.prompts.append((prompt, system_prompt))
        if self.error:
            raise self.error
        return self.output


def envelope(payload):
    return json.dumps({"type": "result", "is_error": False, "structured_output": payload}, ensure_ascii=False)


def client_for(test_config, runner, contact: ContactLoad | None, library=None):
    library = library if library is not None else load_library(FIXTURES / "library_ok")
    app = create_app(
        test_config, runner=runner, library=library, stages=Stages(names=("口試前",)),
        contact=contact, web_dir=Path("does-not-exist"),
    )
    return TestClient(app, base_url=BASE)


def ask(client, question="一個問題"):
    return client.post("/api/ask", json={"question": question, "stage": None})


def test_meta_carries_the_contact_block(test_config, tmp_path):
    loaded = load_contact(write(tmp_path, GOOD))
    client = client_for(test_config, StubRunner(), loaded)
    assert client.get("/api/meta").json()["contact"] == contact_block(loaded.contact)


def test_meta_contact_is_null_when_file_is_unusable(test_config, tmp_path):
    client = client_for(test_config, StubRunner(), load_contact(tmp_path / "nope"))
    assert client.get("/api/meta").json()["contact"] is None


def test_server_starts_and_falls_back_when_contact_file_is_broken(test_config):
    """檔案壞掉：create_app 自己從 data_dir 載入，伺服器照常啟動，卡片退回只有「請洽系辦」。"""
    test_config.data_dir.mkdir(parents=True, exist_ok=True)
    (test_config.data_dir / "contact.json").write_text("{壞掉", encoding="utf-8")
    runner = StubRunner(error=RunnerError(ErrorType.TIMEOUT))
    app = create_app(
        test_config, runner=runner, library=load_library(FIXTURES / "library_ok"),
        stages=Stages(), web_dir=Path("does-not-exist"),
    )
    client = TestClient(app, base_url=BASE)
    assert client.get("/api/meta").status_code == 200
    assert ask(client).json() == {"kind": "unavailable", "message": UNAVAILABLE_TEXT}


def test_unavailable_no_info_and_out_of_scope_carry_contact_via_the_api(test_config, tmp_path):
    loaded = load_contact(write(tmp_path, GOOD))
    block = contact_block(loaded.contact)
    cases = {
        "unavailable": StubRunner(error=RunnerError(ErrorType.TIMEOUT)),
        "no_info": StubRunner(envelope(NOT_IN_DOCS)),
        "out_of_scope": StubRunner(envelope({**NOT_IN_DOCS, "status": "out_of_scope"})),
    }
    for kind, runner in cases.items():
        card = ask(client_for(test_config, runner, loaded)).json()
        assert card["kind"] == kind and card["contact"] == block, kind


def test_library_empty_unavailable_message_also_carries_contact(test_config, tmp_path):
    loaded = load_contact(write(tmp_path, GOOD))
    card = ask(client_for(test_config, StubRunner(), loaded, library=Library())).json()
    assert card["kind"] == "unavailable" and card["contact"]["lines"]


def test_answer_card_has_no_contact_block(test_config, tmp_path):
    loaded = load_contact(write(tmp_path, GOOD))
    payload = {
        "status": "answered", "answer": "請備妥文件。",
        "next_steps": [{"text": "備妥口試申請表", "cite": [0]}], "forms": [], "deadlines": [], "contacts": [],
        "citations": [{"doc_id": "thesis-oral-exam-sop", "version_date": "2025-09-01",
                       "quote": "口試申請應於口試日前14日內，備妥下列文件"}],
    }
    card = ask(client_for(test_config, StubRunner(envelope(payload)), loaded)).json()
    assert card["kind"] == "answer" and "contact" not in card
    assert CONTACT_TITLE not in json.dumps(card, ensure_ascii=False)


def test_contact_never_reaches_the_model(test_config, tmp_path):
    """聯絡資料不進 prompt（防護 1、3、4 的邊界）：模型看不到，也改不了。"""
    loaded = load_contact(write(tmp_path, GOOD))
    runner = StubRunner(envelope(NOT_IN_DOCS))
    ask(client_for(test_config, runner, loaded))
    assert runner.prompts
    sent = "\n".join(p + s for p, s in runner.prompts)
    for needle in ("03-111-0001", "a@example.test", "測試樓 101", "example.test", CONTACT_TITLE):
        assert needle not in sent


def test_model_cannot_inject_a_contact_block(test_config, tmp_path):
    """模型回傳裡多塞 contact 欄位：不會出現在卡片上（卡片的聯絡資料只來自我們的檔案）。"""
    loaded = load_contact(write(tmp_path, GOOD))
    runner = StubRunner(envelope({**NOT_IN_DOCS, "contact": {"lines": ["電話 000-FAKE"]}}))
    text = ask(client_for(test_config, runner, loaded)).text
    assert "000-FAKE" not in text
