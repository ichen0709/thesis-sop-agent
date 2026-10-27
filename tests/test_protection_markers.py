"""五項防護都要有成對的「開始／結束」註解，而且沒有被關掉。"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [*ROOT.glob("src/sop_agent/*.py"), *ROOT.glob("web/*.js")]

BEGIN = re.compile(r"(?:#|//)\s*防護\s*(\d)\s*開始")
END = re.compile(r"(?:#|//)\s*防護\s*(\d)\s*結束")


def markers():
    found: dict[int, list[tuple[str, int, str]]] = {n: [] for n in range(1, 6)}
    for path in SOURCES:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if m := BEGIN.search(line):
                found[int(m.group(1))].append((path.name, lineno, "begin"))
            if m := END.search(line):
                found[int(m.group(1))].append((path.name, lineno, "end"))
    return found


def test_all_five_protections_are_marked():
    found = markers()
    for n in range(1, 6):
        assert found[n], f"防護 {n} 沒有標記"


def test_begin_and_end_are_paired_in_the_same_file_and_in_order():
    for n, items in markers().items():
        by_file: dict[str, list[tuple[int, str]]] = {}
        for name, lineno, kind in items:
            by_file.setdefault(name, []).append((lineno, kind))
        for name, seq in by_file.items():
            seq.sort()
            kinds = [k for _, k in seq]
            assert kinds == ["begin", "end"] * (len(kinds) // 2), f"防護 {n} 在 {name} 沒有成對"


def test_protection_code_is_not_commented_out_or_switched_off():
    # 一開始全部開啟：程式裡不能有關閉防護的開關
    text = "\n".join(p.read_text(encoding="utf-8") for p in SOURCES)
    assert not re.search(r"(?i)(disable|skip|bypass)[_-]?(protection|guard|verify)", text)
    assert "--dangerously-skip-permissions" not in text
    assert "--allow-dangerously-skip-permissions" not in text
    assert "bypassPermissions" not in text
