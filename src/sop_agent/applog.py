"""紀錄檔：每行一筆 JSON，只記時間、錯誤類型、失敗的步驟。

錯誤類型與步驟都是固定列舉，函式不接受任意字串，
所以學生的問題、模型的回答、設定值、例外訊息、本機路徑都沒有地方可以寫進去。
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path


class ErrorType(StrEnum):
    TIMEOUT = "timeout"
    NOT_LOGGED_IN = "not_logged_in"
    CLAUDE_NOT_FOUND = "claude_not_found"
    NONZERO_EXIT = "nonzero_exit"
    BAD_FORMAT = "bad_format"
    VERIFY_FAILED = "verify_failed"
    LIBRARY_EMPTY = "library_empty"
    BUSY = "busy"
    BAD_ORIGIN = "bad_origin"


class Step(StrEnum):
    RUN_CLAUDE = "run_claude"
    PARSE = "parse"
    VERIFY = "verify"
    REQUEST_CHECK = "request_check"


class AppLog:
    def __init__(self, path: Path):
        self._path = Path(path)
        self._lock = threading.Lock()

    def record(self, error: ErrorType, step: Step) -> None:
        if not isinstance(error, ErrorType) or not isinstance(step, Step):
            raise TypeError("紀錄檔只接受 ErrorType 與 Step")
        line = json.dumps(
            {
                "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "error": error.value,
                "step": step.value,
            },
            ensure_ascii=False,
        )
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
