"""出處驗證（架構文件第 6 節）。

驗證只證明：引用的文件存在、版本日期對得上、片段真的出現在那份文件裡。
不證明回答的內容正確，那部分靠承辦人驗收。
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass

from sop_agent.schema import ModelResponse, SourceDoc

# 防護 4 開始：輸出檢查（出處驗證）

# 標準化時額外視為空白的字元（零寬空白、BOM、軟連字號等）。
_EXTRA_BLANKS = {"​", "‌", "‍", "⁠", "﻿", "­"}


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    reason: str | None = None
    # 與 response.citations 一一對應：文件原文中對應的那一段。ok 為 False 時是空的。
    shown_quotes: tuple[str, ...] = ()


def _is_blank(ch: str) -> bool:
    return ch.isspace() or ch in _EXTRA_BLANKS


def normalize_with_map(text: str) -> tuple[str, list[int]]:
    """逐字元做 NFKC 並刪除空白類字元，同時記下每個保留字元對應原文的位置。

    逐字元處理才能對回原文。代價：少數組合字元（例如 e 加組合重音）與整串 NFKC 結果不同，
    這種情況會判定不通過，寧可不放行。
    """
    out: list[str] = []
    mapping: list[int] = []
    for i, ch in enumerate(text):
        for c in unicodedata.normalize("NFKC", ch):
            if _is_blank(c):
                continue
            out.append(c)
            mapping.append(i)
    return "".join(out), mapping


def normalize(text: str) -> str:
    return normalize_with_map(text)[0]


def find_original_span(body: str, quote: str, min_chars: int) -> str | None:
    """在文件內文中找片段；找到就回傳文件原文中對應的那一段，找不到回傳 None。"""
    nq = normalize(quote)
    if len(nq) < min_chars:
        return None
    nbody, mapping = normalize_with_map(body)
    pos = nbody.find(nq)
    if pos < 0:
        return None
    start = mapping[pos]
    end = mapping[pos + len(nq) - 1] + 1
    return body[start:end]


def verify(
    response: ModelResponse,
    docs: Mapping[str, SourceDoc],
    min_quote_chars: int,
) -> VerifyResult:
    """docs 必須是這次 prompt 實際放進去的文件。

    status 不是 answered 時不需要引用，直接通過（卡片由呼叫端決定）。
    answered 時：至少一則引用，全部引用都通過；任何一則沒過，整則作廢。
    """
    if response.status != "answered":
        return VerifyResult(ok=True)

    if not response.answer.strip():
        return VerifyResult(ok=False, reason="empty_answer")
    if not response.citations:
        return VerifyResult(ok=False, reason="no_citation")

    shown: list[str] = []
    for c in response.citations:
        doc = docs.get(c.doc_id)
        if doc is None:
            return VerifyResult(ok=False, reason="unknown_doc")
        if c.version_date != doc.version_date:
            return VerifyResult(ok=False, reason="version_mismatch")
        span = find_original_span(doc.body, c.quote, min_quote_chars)
        if span is None:
            return VerifyResult(ok=False, reason="quote_not_found")
        shown.append(span)

    n = len(response.citations)
    for items in (
        response.next_steps,
        response.forms,
        response.deadlines,
        response.contacts,
    ):
        for item in items:
            if not item.cite:
                return VerifyResult(ok=False, reason="item_without_cite")
            if any(not 0 <= idx < n for idx in item.cite):
                return VerifyResult(ok=False, reason="cite_out_of_range")

    return VerifyResult(ok=True, shown_quotes=tuple(shown))


# 「適用」欄的 term：必須像學年度或學期，而且要出現在該條目 cite 所指文件的內文裡。
# 兩項都過才顯示；沒過只省略「適用」那一段，其他內容照常顯示。
_SEMESTER_LIKE = re.compile(
    r"學年|學期|semester|academic\s*year|\b(?:fall|spring|summer|winter)\b", flags=re.IGNORECASE
)

TERM_OK = "ok"
TERM_NOT_A_SEMESTER = "not_a_semester"
TERM_NOT_IN_DOCUMENT = "not_in_document"


def check_term(term: str, cited_bodies: list[str]) -> str:
    """回傳 TERM_OK、TERM_NOT_A_SEMESTER 或 TERM_NOT_IN_DOCUMENT。term 不可是空白。"""
    if not _SEMESTER_LIKE.search(unicodedata.normalize("NFKC", term)):
        return TERM_NOT_A_SEMESTER
    needle = normalize(term)
    if any(needle in normalize(body) for body in cited_bodies):
        return TERM_OK
    return TERM_NOT_IN_DOCUMENT


def sanitize_terms(
    response: ModelResponse, docs: Mapping[str, SourceDoc]
) -> tuple[ModelResponse, list[str]]:
    """檢查每個期限的 term。回傳 (處理後的回答, 被拿掉的 term 的原因清單)。

    - term 是 None 或空白：視為沒有 term，不算被拿掉。
    - term 沒過：只把該條目的 term 改成 None，其他內容不動。
    - 原因清單只有固定代號（TERM_NOT_A_SEMESTER、TERM_NOT_IN_DOCUMENT），不含 term 的內容。
    呼叫前必須已通過 verify()（cite 索引與文件都存在）。
    """
    reasons: list[str] = []
    deadlines = []
    for d in response.deadlines:
        if d.term is None:
            deadlines.append(d)
        elif not d.term.strip():
            deadlines.append(d.model_copy(update={"term": None}))
        else:
            bodies = [docs[response.citations[i].doc_id].body for i in d.cite]
            verdict = check_term(d.term, bodies)
            if verdict == TERM_OK:
                deadlines.append(d)
            else:
                reasons.append(verdict)
                deadlines.append(d.model_copy(update={"term": None}))
    return response.model_copy(update={"deadlines": deadlines}), reasons
# 防護 4 結束
