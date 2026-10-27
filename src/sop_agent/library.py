"""文件庫：掃描 library/、讀檔頭、建登記表（架構文件第 7 節）。

檔頭是唯一的登記處，不另外維護第二份清單。
- 檔案開頭用 `---` 包住檔頭，其後才是內文。內文不含檔頭，出處驗證只比對內文。
- `public: false` 的文件檔頭照樣檢查，但不載入，內文也不留在記憶體裡。
- 資料夾 `library_archive/`（舊版封存）不讀。
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from sop_agent.schema import SourceDoc

ARCHIVE_DIR_NAME = "library_archive"

REQUIRED_FIELDS = ("id", "title", "source", "version_date", "public")
OPTIONAL_FIELDS = ("stages",)
_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")
_FRONT_MATTER = re.compile(
    r"\A---[ \t]*\r?\n(?P<fm>.*?)^---[ \t]*\r?$\r?\n?(?P<body>.*)\Z",
    flags=re.DOTALL | re.MULTILINE,
)


class LibraryError(Exception):
    """文件庫載入失敗。problems 是 (檔名, 問題) 的清單；訊息只有檔名與問題種類，不含檔案內容。"""

    def __init__(self, problems: list[tuple[str, str]]):
        self.problems = list(problems)
        super().__init__("\n".join(f"{name}：{problem}" for name, problem in self.problems))


@dataclass(frozen=True)
class LibraryDoc:
    id: str
    title: str
    source: str
    version_date: str  # YYYY-MM-DD
    stages: tuple[str, ...]  # 空 = 所有階段適用
    body: str  # 內文，不含檔頭
    path: str  # 相對於文件庫資料夾的路徑

    def to_source_doc(self) -> SourceDoc:
        """轉成階段 1 的 SourceDoc，給 prompt.py 與 verify.py 用。"""
        return SourceDoc(id=self.id, title=self.title, version_date=self.version_date, body=self.body)


@dataclass(frozen=True)
class Library:
    """已載入的文件（只有 public: true 的）。"""

    docs: tuple[LibraryDoc, ...] = ()
    skipped_private: int = 0

    @property
    def by_id(self) -> dict[str, LibraryDoc]:
        return {d.id: d for d in self.docs}

    @property
    def last_updated(self) -> str | None:
        """文件庫最後更新日期：已載入文件版本日期的最大值。沒有文件就是 None。"""
        return max((d.version_date for d in self.docs), default=None)

    def source_docs(self) -> dict[str, SourceDoc]:
        return {d.id: d.to_source_doc() for d in self.docs}


def _parse_file(path: Path, rel: str) -> tuple[LibraryDoc | None, bool, list[str]]:
    """回傳 (文件, 是否公開, 問題清單)。有問題時文件是 None。"""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return None, True, ["不是 UTF-8 編碼"]

    m = _FRONT_MATTER.match(text)
    if not m:
        if text.lstrip().startswith("---") and not text.startswith("---"):
            return None, True, ["檔頭必須從第一行開始"]
        if text.startswith("---"):
            return None, True, ["檔頭沒有結尾的 ---"]
        return None, True, ["沒有檔頭"]

    try:
        # BaseLoader：所有純量都當字串，不自動轉日期或布林，由下面自己驗證
        meta = yaml.load(m.group("fm"), Loader=yaml.BaseLoader)
    except yaml.YAMLError:
        return None, True, ["檔頭不是合法的 YAML"]
    if meta is None:
        meta = {}
    if not isinstance(meta, dict):
        return None, True, ["檔頭必須是「欄位: 值」的格式"]

    problems: list[str] = []
    allowed = set(REQUIRED_FIELDS) | set(OPTIONAL_FIELDS)
    for key in meta:
        if key not in allowed:
            problems.append(f"不認得的欄位 {key}")

    for field in REQUIRED_FIELDS:
        if field not in meta:
            problems.append(f"缺少欄位 {field}")
        elif not isinstance(meta[field], str) or not meta[field].strip():
            problems.append(f"欄位 {field} 是空的或格式不對")

    doc_id = meta.get("id")
    if isinstance(doc_id, str) and doc_id.strip():
        if not _ID_PATTERN.fullmatch(doc_id):
            problems.append("id 只能用英數字、底線、連字號，且開頭是英數字")
        elif doc_id != path.stem:
            problems.append("id 與檔名不一致")

    version = meta.get("version_date")
    if isinstance(version, str) and version.strip():
        valid = bool(_DATE_PATTERN.fullmatch(version))
        if valid:
            try:
                date.fromisoformat(version)
            except ValueError:
                valid = False
        if not valid:
            problems.append("version_date 格式錯誤（需要 YYYY-MM-DD 的真實日期）")

    public_raw = meta.get("public")
    is_public = True
    if isinstance(public_raw, str) and public_raw.strip():
        if public_raw == "true":
            is_public = True
        elif public_raw == "false":
            is_public = False
        else:
            problems.append("public 只能是 true 或 false")

    stages: list[str] = []
    if "stages" in meta:
        raw = meta["stages"]
        if raw == "":
            stages = []
        elif isinstance(raw, list) and all(isinstance(s, str) and s.strip() for s in raw):
            stages = list(raw)
        else:
            problems.append("stages 必須是清單，例如 [口試前, 離校]")

    if problems:
        return None, is_public, problems

    doc = LibraryDoc(
        id=meta["id"],
        title=meta["title"].strip(),
        source=meta["source"].strip(),
        version_date=meta["version_date"],
        stages=tuple(stages),
        body=m.group("body"),
        path=rel,
    )
    return doc, is_public, []


def load_library(directory: Path) -> Library:
    """掃描文件庫。有任何檔案的檔頭不合格，就一次報完所有問題（LibraryError）。

    資料夾不存在或沒有任何 .md，回傳空的 Library，不報錯。
    """
    directory = Path(directory)
    if not directory.is_dir():
        return Library()

    loaded: list[LibraryDoc] = []
    problems: list[tuple[str, str]] = []
    seen_ids: dict[str, str] = {}
    skipped_private = 0

    for path in sorted(directory.rglob("*.md")):
        rel_parts = path.relative_to(directory).parts
        if ARCHIVE_DIR_NAME in rel_parts[:-1]:
            continue
        rel = "/".join(rel_parts)

        doc, is_public, file_problems = _parse_file(path, rel)
        for p in file_problems:
            problems.append((rel, p))
        if doc is None:
            continue

        # id 不可重複，連 public: false 的文件也算
        if doc.id in seen_ids:
            problems.append((rel, f"id 重複（也出現在 {seen_ids[doc.id]}）"))
            continue
        seen_ids[doc.id] = rel

        if is_public:
            loaded.append(doc)
        else:
            skipped_private += 1  # 不載入，內文也不保留

    if problems:
        raise LibraryError(problems)
    return Library(docs=tuple(loaded), skipped_private=skipped_private)


def main() -> int:
    """檢查文件庫：列出載入了哪些文件。系辦換新版文件後可以先跑一次。"""
    from sop_agent.config import load_config

    ap = argparse.ArgumentParser(description="檢查文件庫")
    ap.add_argument("directory", nargs="?", default=None)
    args = ap.parse_args()
    directory = Path(args.directory) if args.directory else load_config().library_dir

    try:
        lib = load_library(directory)
    except LibraryError as e:
        print("文件庫有問題：")
        for name, problem in e.problems:
            print(f"  {name}：{problem}")
        return 1

    if not lib.docs:
        print("文件庫是空的（沒有可載入的文件）。")
    for d in lib.docs:
        scope = "、".join(d.stages) if d.stages else "所有階段"
        print(f"  {d.id}  {d.version_date}  [{scope}]  {d.title}")
    print(f"已載入 {len(lib.docs)} 份；略過不公開 {lib.skipped_private} 份。")
    print(f"文件庫最後更新日期：{lib.last_updated or '（無）'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
