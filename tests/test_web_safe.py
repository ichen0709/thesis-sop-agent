"""確認 web/ 底下沒有不安全的寫入方式（階段 1 只做靜態掃描）。"""

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"

FORBIDDEN = re.compile(
    r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|\beval\s*\(|new\s+Function\b|setTimeout\s*\(\s*['\"]",
)


def scan(directory: Path) -> list[str]:
    hits = []
    for path in directory.rglob("*"):
        if path.suffix.lower() not in {".js", ".html", ".htm", ".mjs"}:
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if FORBIDDEN.search(line):
                hits.append(f"{path.name}:{n}")
    return hits


def test_web_has_no_innerhtml_or_similar():
    assert scan(WEB) == []


def test_scanner_actually_detects_bad_code(tmp_path):
    # 確認掃描本身有效，不是永遠回傳空的
    (tmp_path / "bad.js").write_text("el.innerHTML = x;\n", encoding="utf-8")
    (tmp_path / "bad2.html").write_text("<script>document.write(x)</script>", encoding="utf-8")
    (tmp_path / "ok.js").write_text("el.textContent = x;\n", encoding="utf-8")
    hits = scan(tmp_path)
    assert any(h.startswith("bad.js") for h in hits)
    assert any(h.startswith("bad2.html") for h in hits)
    assert not any(h.startswith("ok.js") for h in hits)


def test_safe_js_writes_text_only():
    src = (WEB / "safe.js").read_text(encoding="utf-8")
    assert "textContent" in src
    assert "createTextNode" in src


def test_html_files_have_no_inline_script_or_handlers():
    # CSP 不允許行內 script；也不要寫 onclick= 之類的事件屬性
    for path in WEB.rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", text, flags=re.I), path.name
        assert not re.search(r"\son\w+\s*=", text, flags=re.I), path.name
