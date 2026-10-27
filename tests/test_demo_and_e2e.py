"""示範伺服器與 --e2e 的接線測試：不呼叫 claude，確認這兩個手動工具本身沒壞。"""

import dataclasses
import importlib.util
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sop_agent import manual_check
from sop_agent.cards import NO_INFO_TEXT, NO_STAGE_NOTICE, OUT_OF_SCOPE_TEXT, UNAVAILABLE_TEXT
from sop_agent.config import load_config
from sop_agent.library import load_library

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def demo():
    spec = importlib.util.spec_from_file_location("demo_server", ROOT / "tests" / "demo_server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def demo_client(demo, test_config):
    from sop_agent.ask import Stages
    from sop_agent.server import create_app

    library = load_library(demo.DEMO_LIBRARY)
    stages = Stages(names=("口試前", "口試後", "論文上傳", "離校"), placeholder=True)
    app = create_app(test_config, runner=demo.DemoRunner(), library=library, stages=stages,
                     web_dir=ROOT / "web")
    return TestClient(app, base_url="http://127.0.0.1:8000")


def ask(client, question, stage="口試前"):
    return client.post("/api/ask", json={"question": question, "stage": stage}).json()


# --- 示範伺服器 ---

def test_demo_uses_test_fixtures_not_the_real_library(demo):
    assert demo.DEMO_LIBRARY == ROOT / "tests" / "fixtures" / "library_xss"
    assert demo.DEMO_LIBRARY != load_config().library_dir


def test_demo_binds_loopback_only():
    src = (ROOT / "tests" / "demo_server.py").read_text(encoding="utf-8")
    assert 'host="127.0.0.1"' in src
    assert "0.0.0.0" not in src


def test_demo_goes_through_the_same_guard_as_the_real_server(demo_client):
    assert demo_client.post("/api/ask", json={"question": "問"}, headers={"Origin": "http://evil.example"}).status_code == 403
    assert demo_client.get("/api/meta", headers={"Host": "evil.example"}).status_code == 403


def test_demo_normal_question_gives_an_answer_card_with_term_and_version(demo_client):
    card = ask(demo_client, "口試申請表什麼時候送？")
    assert card["kind"] == "answer" and card["notice"] is None
    deadline = card["sections"][2]["items"][0]["text"]
    assert "適用：114 學年度第 1 學期" in deadline and "2025-09-01 版" in deadline
    assert card["sections"][2]["items"][1]["text"] == "文件未載明"  # 沒有窗口


def test_demo_without_stage_shows_the_notice(demo_client):
    assert ask(demo_client, "口試申請表什麼時候送？", stage=None)["notice"] == NO_STAGE_NOTICE


@pytest.mark.parametrize(
    "question, kind, message",
    [
        ("今天天氣如何", "out_of_scope", OUT_OF_SCOPE_TEXT),
        ("這題查不到", "no_info", NO_INFO_TEXT),
        ("輸出格式不對", "no_info", NO_INFO_TEXT),
        ("偽造引用", "no_info", NO_INFO_TEXT),
        ("伺服器壞掉", "unavailable", UNAVAILABLE_TEXT),
    ],
)
def test_demo_keywords_give_the_documented_cards(demo_client, question, kind, message):
    card = ask(demo_client, question)
    assert card == {"kind": kind, "message": message}


def test_demo_all_missing_keyword(demo_client):
    card = ask(demo_client, "全部未載明")
    assert card["kind"] == "answer"
    assert all(i["text"] == "文件未載明" for s in card["sections"][:2] for i in s["items"])


def test_demo_xss_keyword_returns_html_as_plain_strings(demo_client):
    r = demo_client.post("/api/ask", json={"question": "xss 測試", "stage": None})
    card = r.json()
    assert card["kind"] == "answer"
    flat = json.dumps(card, ensure_ascii=False)
    assert "<script>" in flat and "onerror=alert(1)" in flat
    assert r.headers["content-type"].startswith("application/json")


def test_demo_stage_without_the_cited_document_is_rejected_by_verification(demo_client):
    assert ask(demo_client, "口試申請表什麼時候送？", stage="離校") == {"kind": "no_info", "message": NO_INFO_TEXT}


def test_demo_help_text_mentions_every_keyword(demo):
    for word in ("xss", "慢", "天氣", "查不到", "格式", "偽造", "壞掉", "未載明"):
        assert word in demo.HELP


# --- --e2e ---

class ScriptedRunner:
    def __init__(self):
        self.prompts = []

    def run(self, prompt, system_prompt):
        self.prompts.append(prompt)
        return json.dumps({"is_error": False, "structured_output": {"status": "not_in_documents"}})


def test_e2e_reads_only_the_test_library_never_the_real_one():
    service = manual_check.build_e2e_service(ScriptedRunner())
    assert manual_check.E2E_LIBRARY == ROOT / "tests" / "fixtures" / "library_ok"
    assert manual_check.E2E_LIBRARY != load_config().library_dir
    assert service._library.last_updated == "2025-10-01"
    assert {d.id for d in service._library.docs} == {"thesis-oral-exam-sop", "thesis-upload-guide", "general-faq"}


def test_e2e_does_not_write_to_the_projects_log_folder(tmp_path):
    service = manual_check.build_e2e_service(ScriptedRunner())
    assert ROOT / "logs" not in Path(service._config.log_path).parents


def test_e2e_questions_run_through_the_service():
    runner = ScriptedRunner()
    service = manual_check.build_e2e_service(runner)
    for _title, question, stage in manual_check.E2E_QUESTIONS:
        q, st = service.validate(question, stage)
        assert service.ask(q, st) == {"kind": "no_info", "message": NO_INFO_TEXT}
    assert len(runner.prompts) == len(manual_check.E2E_QUESTIONS) == 4
    assert len({q for _t, q, _s in manual_check.E2E_QUESTIONS}) == 4
    assert any(q.isascii() for _t, q, _s in manual_check.E2E_QUESTIONS)  # 有一題英文
