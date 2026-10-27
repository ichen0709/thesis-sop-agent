"""讀取 config.toml。設定檔不放金鑰。"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.toml"


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    host: str
    port: int
    model_name: str
    timeout_seconds: float
    claude_command: tuple[str, ...]
    isolation_flags: tuple[str, ...]
    result_fields: tuple[str, ...]
    max_question_chars: int
    max_prompt_chars: int
    min_quote_chars: int
    library_dir: Path
    data_dir: Path
    log_path: Path


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> Config:
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    root = path.resolve().parent

    server = raw.get("server", {})
    model = raw.get("model", {})
    claude = raw.get("claude", {})
    limits = raw.get("limits", {})
    paths = raw.get("paths", {})

    host = server.get("host", "127.0.0.1")
    if host != "127.0.0.1":
        raise ConfigError("server.host 只能是 127.0.0.1")
    port = server.get("port", 8000)
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise ConfigError("server.port 必須是 1 到 65535 的整數")

    timeout = model.get("timeout_seconds", 120)
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ConfigError("model.timeout_seconds 必須大於 0")

    command = claude.get("command", ["claude"])
    if not command or not all(isinstance(c, str) for c in command):
        raise ConfigError("claude.command 必須是字串清單")

    max_question = limits.get("max_question_chars", 500)
    if not isinstance(max_question, int) or max_question <= 0:
        raise ConfigError("limits.max_question_chars 必須大於 0")
    min_quote = limits.get("min_quote_chars", 8)
    if not isinstance(min_quote, int) or min_quote <= 0:
        raise ConfigError("limits.min_quote_chars 必須大於 0")

    return Config(
        host=host,
        port=port,
        model_name=model.get("name", ""),
        timeout_seconds=float(timeout),
        claude_command=tuple(command),
        isolation_flags=tuple(claude.get("isolation_flags", ["--restricted", "--setting-sources", ""])),
        result_fields=tuple(claude.get("result_fields", ["structured_output"])),
        max_question_chars=max_question,
        max_prompt_chars=limits.get("max_prompt_chars", 0),
        min_quote_chars=min_quote,
        library_dir=root / paths.get("library", "library"),
        data_dir=root / paths.get("data", "data"),
        log_path=root / paths.get("log", "logs/app.log"),
    )
