"""依階段選文件，給 prompt 用（架構文件第 7 節「選哪些文件給模型」）。

結果用明確的狀態表示，讓上層決定學生看到什麼：
- OK：有文件可以用。
- LIBRARY_EMPTY：文件庫完全沒有可用文件。上層走「無法回答」訊息（紀錄 library_empty）。
- NO_DOCS_FOR_STAGE：文件庫有文件，但沒有任何一份適用於該階段。上層走「查不到卡」。
- OVER_BUDGET：總字數超過 max_prompt_chars。目前不處理，docs 一律是空的，
  避免上層忘了檢查就把過量的文件送出去。上層暫時走「無法回答」訊息。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sop_agent.library import Library
from sop_agent.schema import SourceDoc


class SelectionStatus(StrEnum):
    OK = "ok"
    LIBRARY_EMPTY = "library_empty"
    NO_DOCS_FOR_STAGE = "no_docs_for_stage"
    OVER_BUDGET = "over_budget"


@dataclass(frozen=True)
class Selection:
    status: SelectionStatus
    docs: tuple[SourceDoc, ...] = ()

    def by_id(self) -> dict[str, SourceDoc]:
        """這次 prompt 實際放進去的文件，給 verify.verify() 核對 doc_id、版本日期與內文。"""
        return {d.id: d for d in self.docs}


def select_documents(library: Library, stage: str | None, max_prompt_chars: int = 0) -> Selection:
    """沒選階段放全部；選了階段放「stages 為空的」加上「stages 含該階段的」。

    max_prompt_chars 為 0 代表不限制。
    """
    if not library.docs:
        return Selection(SelectionStatus.LIBRARY_EMPTY)

    if stage:
        chosen = [d for d in library.docs if not d.stages or stage in d.stages]
        if not chosen:
            return Selection(SelectionStatus.NO_DOCS_FOR_STAGE)
    else:
        chosen = list(library.docs)

    total_chars = sum(len(d.body) for d in chosen)
    if max_prompt_chars and total_chars > max_prompt_chars:
        return Selection(SelectionStatus.OVER_BUDGET)

    return Selection(SelectionStatus.OK, tuple(d.to_source_doc() for d in chosen))


def narrow_to_budget(*_args, **_kwargs):
    """【尚未實作】總字數超過 max_prompt_chars 時，改成挑段落。

    預計做法（見架構文件第 7 節）：把文件切段，用字元二連詞（bigram）關鍵字評分，取前幾段。
    要等拿到真的系辦文件、量過大小，才決定要不要做、閾值多少。
    做的時候要保留每段所屬的 doc_id，讓出處驗證仍能核對 doc_id、版本日期與內文。
    """
    raise NotImplementedError("挑段落尚未實作：等拿到真文件、量過大小再決定")
