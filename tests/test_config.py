import re
from pathlib import Path

import pytest

from sop_agent.config import DEFAULT_CONFIG_PATH, ConfigError, load_config


def test_default_config_loads():
    cfg = load_config()
    assert cfg.port == 8000
    assert cfg.max_question_chars == 500
    assert cfg.min_quote_chars == 8
    assert cfg.claude_command == ("claude",)
    # 手動檢查的結論：--restricted 加 --setting-sources ""（空字串）；模型內容用 structured_output
    assert cfg.isolation_flags == ("--restricted", "--setting-sources", "")
    assert cfg.result_fields == ("structured_output",)


def test_missing_claude_section_falls_back_to_checked_defaults(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("", encoding="utf-8")
    cfg = load_config(cfg_file)
    assert cfg.isolation_flags == ("--restricted", "--setting-sources", "")
    assert cfg.result_fields == ("structured_output",)


def test_default_config_has_no_secret_fields():
    text = DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")
    assert not re.search(r"(?im)^\s*[\w.]*(api[_-]?key|token|secret|password)[\w.]*\s*=", text)
    assert "sk-" not in text


def test_paths_are_resolved_against_config_folder(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('[paths]\nlog = "x/app.log"\n', encoding="utf-8")
    assert load_config(cfg_file).log_path == tmp_path / "x" / "app.log"


@pytest.mark.parametrize(
    "body",
    [
        '[server]\nhost = "0.0.0.0"\n',
        "[server]\nport = 0\n",
        "[model]\ntimeout_seconds = 0\n",
        "[limits]\nmax_question_chars = 0\n",
        "[claude]\ncommand = []\n",
    ],
)
def test_invalid_values_are_rejected(tmp_path, body):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(body, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(cfg_file)
