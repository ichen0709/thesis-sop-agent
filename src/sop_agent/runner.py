"""啟動 `claude -p`。

- 每次在全新的暫存資料夾裡執行，結束後刪除。
- 關掉所有工具、隔離使用者設定、移除金鑰環境變數。
- 指令用清單啟動（不經 shell），問題與文件只走 stdin。
- 可以換成假的 runner 或假的 claude 指令來測試。
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from typing import Protocol

from sop_agent.applog import ErrorType


class RunnerError(Exception):
    """啟動或執行 claude 失敗。只帶固定的錯誤類型，不帶任何訊息內容。"""

    def __init__(self, error: ErrorType):
        super().__init__(error.value)
        self.error = error


class Runner(Protocol):
    def run(self, prompt: str, system_prompt: str) -> str:
        """回傳 claude 的標準輸出（外層 JSON 字串）。失敗時丟 RunnerError。"""
        ...


# 防護 2 開始：權限限制（環境變數）
# 這些變數存在時，claude -p 會改用 API 計費或雲端帳號，而不是已登入的帳號。
# CLAUDE_CODE_OAUTH_TOKEN 是訂閱登入用的，不移除。
_STRIPPED_ENV = {
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
}


def build_env(base: Mapping[str, str], extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """複製環境變數並移除金鑰類變數（Windows 的變數名稱不分大小寫）。"""
    env = {k: v for k, v in base.items() if k.upper() not in _STRIPPED_ENV}
    if extra:
        env.update(extra)
    return env


def build_argv(
    command: Sequence[str],
    system_prompt: str,
    json_schema: str,
    isolation_flags: Sequence[str],
    model_name: str = "",
) -> list[str]:
    argv = [
        *command,
        "-p",
        "--system-prompt", system_prompt,
        "--tools", "",                    # 關掉所有內建工具
        "--disable-slash-commands",
        "--strict-mcp-config",            # 沒給 --mcp-config，等於不載入任何 MCP
        "--no-session-persistence",
        "--output-format", "json",
        "--json-schema", json_schema,
        *isolation_flags,                 # 隔離使用者設定，見 config.toml
    ]
    if model_name:
        argv += ["--model", model_name]
    return argv
# 防護 2 結束


def _kill_tree(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
    else:
        proc.kill()


def _classify_failure(output: str) -> ErrorType:
    """從輸出判斷是不是沒登入。判斷用的關鍵字待手動檢查確認。"""
    low = output.lower()
    if "not logged in" in low or "/login" in low or "invalid api key" in low:
        return ErrorType.NOT_LOGGED_IN
    return ErrorType.NONZERO_EXIT


class SubprocessRunner:
    def __init__(
        self,
        command: Sequence[str],
        json_schema: str,
        isolation_flags: Sequence[str] = (),
        model_name: str = "",
        timeout_seconds: float = 120.0,
        extra_env: Mapping[str, str] | None = None,
    ):
        self._command = list(command)
        self._json_schema = json_schema
        self._isolation_flags = list(isolation_flags)
        self._model_name = model_name
        self._timeout = timeout_seconds
        self._extra_env = dict(extra_env) if extra_env else None

    def run(self, prompt: str, system_prompt: str) -> str:
        argv = build_argv(
            self._command,
            system_prompt,
            self._json_schema,
            self._isolation_flags,
            self._model_name,
        )
        env = build_env(os.environ, self._extra_env)

        # 防護 1 開始：暫存資料夾
        with tempfile.TemporaryDirectory(prefix="sop-agent-") as workdir:
            try:
                proc = subprocess.Popen(
                    argv,                  # 清單，不經 shell
                    cwd=workdir,
                    env=env,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            except FileNotFoundError:
                raise RunnerError(ErrorType.CLAUDE_NOT_FOUND) from None
            except OSError:
                raise RunnerError(ErrorType.NONZERO_EXIT) from None

            try:
                out, err = proc.communicate(prompt.encode("utf-8"), timeout=self._timeout)
            except subprocess.TimeoutExpired:
                _kill_tree(proc)
                proc.communicate()
                raise RunnerError(ErrorType.TIMEOUT) from None
        # 防護 1 結束

        stdout = out.decode("utf-8", errors="replace")
        if proc.returncode != 0:
            stderr = err.decode("utf-8", errors="replace")
            raise RunnerError(_classify_failure(stdout + "\n" + stderr))
        return stdout
