from pathlib import Path

import pytest

from sop_agent.config import Config
from sop_agent.schema import SourceDoc

FIXTURES = Path(__file__).parent / "fixtures"
FAKES = Path(__file__).parent / "fakes"


@pytest.fixture
def oral_doc() -> SourceDoc:
    return SourceDoc(
        id="oral-exam",
        title="口試辦理流程（測試用）",
        version_date="2025-09-01",
        body=(FIXTURES / "doc_oral.txt").read_text(encoding="utf-8"),
    )


@pytest.fixture
def other_doc() -> SourceDoc:
    return SourceDoc(
        id="upload",
        title="論文上傳（測試用）",
        version_date="2025-10-01",
        body="論文定稿後，請至系統上傳電子檔並列印授權書。",
    )


@pytest.fixture
def docs(oral_doc, other_doc):
    return {oral_doc.id: oral_doc, other_doc.id: other_doc}


@pytest.fixture
def test_config(tmp_path) -> Config:
    return Config(
        host="127.0.0.1",
        port=8000,
        model_name="",
        timeout_seconds=5.0,
        claude_command=("claude",),
        isolation_flags=("--restricted", "--setting-sources", ""),
        result_fields=("structured_output",),
        max_question_chars=500,
        max_prompt_chars=0,
        min_quote_chars=8,
        library_dir=tmp_path / "library",
        data_dir=tmp_path / "data",
        log_path=tmp_path / "logs" / "app.log",
    )
