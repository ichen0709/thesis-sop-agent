"""模型回傳格式（架構文件第 5 節）與 claude 外層結果的取出。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

_STRICT = ConfigDict(extra="forbid", strict=True)


class SchemaError(Exception):
    """模型回傳的內容不符合格式。學生只會看到「文件中沒有這項資訊」。"""


@dataclass(frozen=True)
class SourceDoc:
    """放進 prompt 的一份文件。body 是內文，不含檔頭。"""

    id: str
    title: str
    version_date: str
    body: str


# 防護 4 開始：輸出檢查（格式）
class Item(BaseModel):
    model_config = _STRICT
    text: str
    cite: list[int]


class Deadline(Item):
    term: str | None = None


class Citation(BaseModel):
    model_config = _STRICT
    doc_id: str
    version_date: str
    quote: str


class ModelResponse(BaseModel):
    model_config = _STRICT
    status: Literal["answered", "not_in_documents", "out_of_scope"]
    answer: str = ""
    next_steps: list[Item] = []
    forms: list[Item] = []
    deadlines: list[Deadline] = []
    contacts: list[Item] = []
    citations: list[Citation] = []


def parse_model_response(payload: str | dict[str, Any]) -> ModelResponse:
    """把模型內容（JSON 字串或已解析的 dict）驗證成 ModelResponse。"""
    if isinstance(payload, str):
        try:
            payload = json.loads(_strip_code_fence(payload))
        except json.JSONDecodeError as e:
            raise SchemaError("不是合法的 JSON") from e
    if not isinstance(payload, dict):
        raise SchemaError("最外層必須是物件")
    try:
        return ModelResponse.model_validate(payload)
    except ValidationError as e:
        raise SchemaError("欄位缺漏或型別錯誤") from e


def extract_payload(stdout: str, result_fields: tuple[str, ...]) -> str | dict[str, Any]:
    """從 `claude --output-format json` 的外層結果取出模型內容。

    欄位名稱在 config.toml 的 claude.result_fields，依序嘗試。實測結論：用 structured_output（物件）。
    """
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError as e:
        raise SchemaError("外層結果不是 JSON") from e
    if not isinstance(envelope, dict):
        raise SchemaError("外層結果必須是物件")
    if envelope.get("is_error") is True:
        raise SchemaError("claude 回報錯誤")
    for name in result_fields:
        value = envelope.get(name)
        if isinstance(value, (dict, str)) and value != "":
            return value
    raise SchemaError("外層結果找不到模型內容")


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    m = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL)
    return m.group(1) if m else text


def json_schema_text() -> str:
    """給 `--json-schema` 的 JSON 字串。"""
    return json.dumps(ModelResponse.model_json_schema(), ensure_ascii=False)
# 防護 4 結束


if __name__ == "__main__":
    print(json_schema_text())
