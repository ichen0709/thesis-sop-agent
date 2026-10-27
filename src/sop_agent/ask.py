"""問答流程：驗證輸入 → 選文件 → 組 prompt → 呼叫 claude → 驗證 → 決定卡片。

學生永遠看不到技術原因：任何失敗都轉成「查不到卡」或「無法回答」訊息，
技術原因只用固定代號記進紀錄檔（時間、錯誤類型、失敗的步驟）。
"""

from __future__ import annotations

import json
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sop_agent.applog import AppLog, ErrorType, Step
from sop_agent.cards import build_answer_card, clean_text, message_card
from sop_agent.config import Config
from sop_agent.library import Library
from sop_agent.prompt import SYSTEM_PROMPT, build_prompt, validate_stage
from sop_agent.runner import Runner, RunnerError
from sop_agent.schema import SchemaError, extract_payload, parse_model_response
from sop_agent.selector import SelectionStatus, select_documents
from sop_agent.verify import verify


class StagesError(Exception):
    """data/stages.json 格式不對。訊息不含檔案內容。"""


class InputError(Exception):
    """學生的輸入不合格。code 是固定代號，會回給前端（HTTP 400）。"""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Stages:
    names: tuple[str, ...] = ()
    placeholder: bool = False  # True = 還是占位內容，畫面標「範例資料，非正式規定」


def load_stages(data_dir: Path) -> Stages:
    """讀階段選單。檔案不存在 = 沒有可選的階段（只剩「不指定階段」）。"""
    path = Path(data_dir) / "stages.json"
    if not path.exists():
        return Stages()
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raise StagesError("stages.json 不是合法的 JSON") from None
    if not isinstance(raw, dict):
        raise StagesError("stages.json 最外層必須是物件")
    names = raw.get("stages", [])
    if (
        not isinstance(names, list)
        or not all(isinstance(n, str) and n.strip() for n in names)
        or len(set(names)) != len(names)
    ):
        raise StagesError("stages.json 的 stages 必須是不重複的非空字串清單")
    placeholder = raw.get("placeholder", False)
    if not isinstance(placeholder, bool):
        raise StagesError("stages.json 的 placeholder 必須是 true 或 false")
    return Stages(names=tuple(names), placeholder=placeholder)


def unknown_library_stages(library: Library, stages: Stages) -> list[str]:
    """文件檔頭的 stages 裡，不在階段選單中的名稱。這些名稱的文件選了階段後會選不到。"""
    known = set(stages.names)
    return sorted({s for d in library.docs for s in d.stages if s not in known})


class AskService:
    def __init__(self, config: Config, library: Library, stages: Stages, runner: Runner, log: AppLog):
        self._config = config
        self._library = library
        self._stages = stages
        self._runner = runner
        self._log = log
        self._lock = threading.Lock()  # 同一時間只處理一個問題
        self._current_step = Step.SELECT_DOCS  # 未預期的例外發生時，紀錄是在哪一步

    # 防護 3 開始：問題當資料（輸入驗證與階段白名單）
    def validate(self, question: object, stage: object) -> tuple[str, str | None]:
        """回傳清理後的 (問題, 階段)。不合格丟 InputError，不呼叫模型。"""
        if not isinstance(question, str):
            raise InputError("empty_question")
        cleaned = clean_text(question).strip()
        if not cleaned:
            raise InputError("empty_question")
        if len(cleaned) > self._config.max_question_chars:  # 以 Unicode 字元數計算
            raise InputError("question_too_long")
        if stage is not None and not isinstance(stage, str):
            raise InputError("bad_stage")
        try:
            checked_stage = validate_stage(stage, self._stages.names)
        except ValueError:
            raise InputError("bad_stage") from None
        return cleaned, checked_stage
    # 防護 3 結束

    def ask(self, question: str, stage: str | None) -> dict[str, Any]:
        """question、stage 必須是 validate() 的回傳值。回傳要顯示的卡片。"""
        if not self._lock.acquire(blocking=False):
            self._log.record(ErrorType.BUSY, Step.RUN_CLAUDE)
            return message_card("unavailable")
        try:
            return self._ask_locked(question, stage)
        except Exception:  # 未預期的例外：學生只會看到「無法回答」，不會看到內容
            self._log.record(ErrorType.INTERNAL_ERROR, self._current_step)
            return message_card("unavailable")
        finally:
            self._lock.release()

    def _ask_locked(self, question: str, stage: str | None) -> dict[str, Any]:
        self._current_step = Step.SELECT_DOCS
        selection = select_documents(self._library, stage, self._config.max_prompt_chars)
        if selection.status is SelectionStatus.LIBRARY_EMPTY:
            self._log.record(ErrorType.LIBRARY_EMPTY, Step.SELECT_DOCS)
            return message_card("unavailable")
        if selection.status is SelectionStatus.OVER_BUDGET:
            # 挑段落尚未實作，所以暫時無法回答
            self._log.record(ErrorType.OVER_BUDGET, Step.SELECT_DOCS)
            return message_card("unavailable")
        if selection.status is SelectionStatus.NO_DOCS_FOR_STAGE:
            return message_card("no_info")  # 正常結果，不算錯誤，不記錄

        self._current_step = Step.RUN_CLAUDE
        prompt = build_prompt(question, stage, selection.docs)
        try:
            stdout = self._runner.run(prompt, SYSTEM_PROMPT)
        except RunnerError as e:
            self._log.record(e.error, Step.RUN_CLAUDE)
            return message_card("unavailable")

        # 防護 4 開始：輸出檢查（格式與出處驗證，沒過就改成查不到卡）
        self._current_step = Step.PARSE
        try:
            payload = extract_payload(stdout, self._config.result_fields)
            response = parse_model_response(payload)
        except SchemaError:
            self._log.record(ErrorType.BAD_FORMAT, Step.PARSE)
            return message_card("no_info")

        self._current_step = Step.VERIFY
        docs = selection.by_id()
        verified = verify(response, docs, self._config.min_quote_chars)
        if not verified.ok:
            self._log.record(ErrorType.VERIFY_FAILED, Step.VERIFY)
            return message_card("no_info")
        # 防護 4 結束

        if response.status == "not_in_documents":
            return message_card("no_info")
        if response.status == "out_of_scope":
            return message_card("out_of_scope")
        return build_answer_card(response, verified.shown_quotes, docs, stage_selected=stage is not None)


def print_startup_notes(library: Library, stages: Stages) -> None:
    """啟動時的提醒，印在終端機。不是錯誤，不影響啟動。"""
    if not library.docs:
        print("提醒：文件庫是空的，學生提問時會看到「無法回答」訊息。", file=sys.stderr)
    unknown = unknown_library_stages(library, stages)
    if unknown:
        print(
            "警告：有文件的 stages 不在階段選單裡，選了階段後這些文件會選不到："
            + "、".join(unknown),
            file=sys.stderr,
        )
