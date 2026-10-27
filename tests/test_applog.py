import json

import pytest

from sop_agent.applog import AppLog, ErrorType, Step


def read_lines(path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]


def test_record_writes_time_type_and_step_only(tmp_path):
    path = tmp_path / "logs" / "app.log"
    AppLog(path).record(ErrorType.TIMEOUT, Step.RUN_CLAUDE)
    (line,) = read_lines(path)
    assert set(line) == {"time", "error", "step"}
    assert line["error"] == "timeout"
    assert line["step"] == "run_claude"
    assert "T" in line["time"]


def test_every_code_can_be_recorded(tmp_path):
    path = tmp_path / "app.log"
    log = AppLog(path)
    for e in ErrorType:
        for s in Step:
            log.record(e, s)
    lines = read_lines(path)
    assert len(lines) == len(ErrorType) * len(Step)
    allowed_errors = {e.value for e in ErrorType}
    allowed_steps = {s.value for s in Step}
    for l in lines:
        assert set(l) == {"time", "error", "step"}
        assert l["error"] in allowed_errors and l["step"] in allowed_steps


@pytest.mark.parametrize(
    "error, step",
    [
        ("timeout", Step.RUN_CLAUDE),
        (ErrorType.TIMEOUT, "run_claude"),
        ("學生的問題內容", "C:\\Users\\someone\\secret"),
        (ValueError("例外訊息含路徑 C:\\x"), Step.PARSE),
    ],
)
def test_arbitrary_values_are_rejected(tmp_path, error, step):
    path = tmp_path / "app.log"
    with pytest.raises(TypeError):
        AppLog(path).record(error, step)
    assert not path.exists()


def test_log_contains_no_free_text(tmp_path):
    path = tmp_path / "app.log"
    AppLog(path).record(ErrorType.VERIFY_FAILED, Step.VERIFY)
    raw = path.read_text(encoding="utf-8")
    assert str(tmp_path) not in raw
    assert "C:\\" not in raw


def test_appends_one_line_per_record(tmp_path):
    path = tmp_path / "app.log"
    log = AppLog(path)
    log.record(ErrorType.BUSY, Step.RUN_CLAUDE)
    log.record(ErrorType.BAD_FORMAT, Step.PARSE)
    assert len(read_lines(path)) == 2
