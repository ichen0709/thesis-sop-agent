import json
import sys
import time
from pathlib import Path

import pytest

from sop_agent.applog import ErrorType
from sop_agent.runner import RunnerError, SubprocessRunner, build_argv, build_env

FAKE = str(Path(__file__).parent / "fakes" / "fake_claude.py")
SCHEMA = '{"type":"object"}'
SYSTEM = "系統規則"


def make_runner(tmp_path, mode="ok", timeout=10.0, **extra):
    record = tmp_path / "record.json"
    env = {"FAKE_CLAUDE_RECORD": str(record), "FAKE_CLAUDE_MODE": mode, **extra}
    runner = SubprocessRunner(
        command=[sys.executable, FAKE],
        json_schema=SCHEMA,
        isolation_flags=["--restricted"],
        timeout_seconds=timeout,
        extra_env=env,
    )
    return runner, record


def read_record(record: Path) -> dict:
    return json.loads(record.read_text(encoding="utf-8"))


# --- 環境變數 ---

def test_build_env_strips_key_variables():
    base = {
        "ANTHROPIC_API_KEY": "x",
        "anthropic_auth_token": "x",
        "CLAUDE_CODE_USE_BEDROCK": "1",
        "CLAUDE_CODE_OAUTH_TOKEN": "keep",
        "PATH": "p",
    }
    env = build_env(base)
    assert set(env) == {"CLAUDE_CODE_OAUTH_TOKEN", "PATH"}


def test_child_process_does_not_see_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "not-a-real-token")
    runner, record = make_runner(tmp_path)
    runner.run("問題", SYSTEM)
    seen = read_record(record)
    assert seen["has_api_key"] is False
    assert seen["has_auth_token"] is False


# --- 暫存資料夾 ---

def test_runs_in_empty_temp_directory_and_removes_it(tmp_path):
    runner, record = make_runner(tmp_path)
    runner.run("問題", SYSTEM)
    seen = read_record(record)
    assert seen["cwd_listing"] == []
    cwd = Path(seen["cwd"])
    assert "sop-agent-" in cwd.name
    assert not cwd.exists()
    assert cwd != Path.cwd()


def test_each_run_uses_a_new_directory(tmp_path):
    runner, record = make_runner(tmp_path)
    runner.run("a", SYSTEM)
    first = read_record(record)["cwd"]
    runner.run("b", SYSTEM)
    assert read_record(record)["cwd"] != first


def test_temp_directory_removed_when_claude_fails(tmp_path):
    runner, record = make_runner(tmp_path, mode="fail_other")
    with pytest.raises(RunnerError):
        runner.run("問題", SYSTEM)
    assert not Path(read_record(record)["cwd"]).exists()


# --- 問題只走 stdin ---

def test_question_goes_only_through_stdin(tmp_path):
    runner, record = make_runner(tmp_path)
    question = "我的獨特問題內容-98765"
    runner.run(question, SYSTEM)
    seen = read_record(record)
    assert question in seen["stdin"]
    assert all(question not in arg for arg in seen["argv"])


# --- 旗標 ---

def test_argv_has_required_flags_and_no_permission_bypass():
    argv = build_argv(["claude"], SYSTEM, SCHEMA, ["--restricted"], "sonnet")
    assert argv[:2] == ["claude", "-p"]
    i = argv.index("--tools")
    assert argv[i + 1] == ""
    for flag in (
        "--disable-slash-commands",
        "--strict-mcp-config",
        "--no-session-persistence",
        "--restricted",
    ):
        assert flag in argv
    assert argv[argv.index("--output-format") + 1] == "json"
    assert argv[argv.index("--json-schema") + 1] == SCHEMA
    assert argv[argv.index("--model") + 1] == "sonnet"
    joined = " ".join(argv)
    assert "dangerously" not in joined
    assert "bypassPermissions" not in joined
    assert "--bare" not in argv


def test_empty_setting_sources_value_reaches_the_child(tmp_path):
    # --setting-sources 後面的空字串必須原樣傳給 claude，不能被吃掉
    from sop_agent.config import load_config

    cfg = load_config()
    runner = SubprocessRunner(
        command=[sys.executable, FAKE],
        json_schema=SCHEMA,
        isolation_flags=cfg.isolation_flags,
        extra_env={"FAKE_CLAUDE_RECORD": str(tmp_path / "r.json")},
    )
    runner.run("問題", SYSTEM)
    argv = read_record(tmp_path / "r.json")["argv"]
    i = argv.index("--setting-sources")
    assert argv[i + 1] == ""
    assert "--restricted" in argv
    assert argv[argv.index("--tools") + 1] == ""


def test_model_flag_omitted_when_name_empty():
    assert "--model" not in build_argv(["claude"], SYSTEM, SCHEMA, [], "")


def test_flags_reach_the_child_as_a_list(tmp_path):
    runner, record = make_runner(tmp_path)
    runner.run("問題", SYSTEM)
    argv = read_record(record)["argv"]
    assert "-p" in argv
    assert argv[argv.index("--system-prompt") + 1] == SYSTEM
    assert argv[argv.index("--tools") + 1] == ""


# --- 成功與失敗 ---

def test_success_returns_stdout(tmp_path):
    runner, _ = make_runner(tmp_path)
    out = runner.run("問題", SYSTEM)
    assert json.loads(out)["structured_output"]["status"] == "not_in_documents"


def test_claude_not_found(tmp_path):
    runner = SubprocessRunner(command=["definitely-not-a-real-command-xyz"], json_schema=SCHEMA)
    with pytest.raises(RunnerError) as e:
        runner.run("問題", SYSTEM)
    assert e.value.error is ErrorType.CLAUDE_NOT_FOUND


def test_not_logged_in_is_classified(tmp_path):
    runner, _ = make_runner(tmp_path, mode="fail_login")
    with pytest.raises(RunnerError) as e:
        runner.run("問題", SYSTEM)
    assert e.value.error is ErrorType.NOT_LOGGED_IN


def test_other_failure_is_nonzero_exit(tmp_path):
    runner, _ = make_runner(tmp_path, mode="fail_other")
    with pytest.raises(RunnerError) as e:
        runner.run("問題", SYSTEM)
    assert e.value.error is ErrorType.NONZERO_EXIT


def test_runner_error_carries_no_message_content(tmp_path):
    runner, _ = make_runner(tmp_path, mode="fail_other")
    with pytest.raises(RunnerError) as e:
        runner.run("機密問題內容", SYSTEM)
    assert "機密問題內容" not in str(e.value)
    assert "something broke" not in str(e.value)


# --- 逾時 ---

def test_timeout_kills_the_child(tmp_path):
    sentinel = tmp_path / "sentinel.txt"
    runner, record = make_runner(
        tmp_path, mode="sleep", timeout=1.0,
        FAKE_CLAUDE_SLEEP="3", FAKE_CLAUDE_SENTINEL=str(sentinel),
    )
    start = time.monotonic()
    with pytest.raises(RunnerError) as e:
        runner.run("問題", SYSTEM)
    assert e.value.error is ErrorType.TIMEOUT
    assert time.monotonic() - start < 3.0
    time.sleep(3.5)  # 如果子行程沒被終止，這段時間內它會醒來並寫出 sentinel
    assert not sentinel.exists()
    assert not Path(read_record(record)["cwd"]).exists()
