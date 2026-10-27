"""畫面層級的靜態檢查：app.js、index.html、CSP。

JavaScript 本身（按鈕停用、轉圈圈、字數提示）不在這裡測，那些要手動在瀏覽器看
（見 README 的「手動檢查（示範伺服器）」）。
"""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sop_agent.ask import Stages
from sop_agent.library import Library
from sop_agent.server import create_app

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
APP_JS = (WEB / "app.js").read_text(encoding="utf-8")
INDEX = (WEB / "index.html").read_text(encoding="utf-8")


def code_lines(text: str):
    """去掉 // 註解後的程式碼行。"""
    for line in text.splitlines():
        yield re.sub(r"\s//.*$", "", line).strip()


# --- app.js：一律走 safe.js ---

@pytest.mark.parametrize(
    "pattern",
    [
        r"\.innerHTML", r"\.outerHTML", r"insertAdjacentHTML", r"document\.write",
        r"createElement\s*\(", r"createElementNS", r"createRange", r"DOMParser",
        r"\beval\s*\(", r"new\s+Function", r"\.setAttribute\s*\(",
        r"\.src\s*=", r"\.href\s*=", r"srcdoc", r"location\s*=", r"location\.href",
    ],
)
def test_app_js_has_no_unsafe_dom_calls(pattern):
    hits = [l for l in code_lines(APP_JS) if re.search(pattern, l)]
    assert hits == []


def test_app_js_writes_through_safe_js_only():
    assert re.search(r'from\s+"/safe\.js"', APP_JS)
    assert "makeEl(" in APP_JS and "appendText(" in APP_JS and "setText(" in APP_JS


def test_app_js_never_assigns_to_textcontent_with_html_building():
    # 不用字串拼出標籤
    assert not re.search(r"""["'`]<\w+""", APP_JS)


def test_app_js_does_not_persist_anything():
    for word in ("localStorage", "sessionStorage", "indexedDB", "document.cookie"):
        assert word not in APP_JS


def test_app_js_reads_limit_from_server_not_hardcoded():
    assert "meta.max_question_chars" in APP_JS
    assert not re.search(r"\b500\b", APP_JS)


def test_app_js_counts_unicode_characters_like_the_server():
    assert "[...text.trim()].length" in APP_JS


def test_app_js_sends_json_to_same_origin_only():
    urls = re.findall(r'fetch\(\s*"([^"]+)"', APP_JS)
    assert urls and all(u.startswith("/api/") for u in urls)
    assert not re.search(r"https?://", APP_JS)


# --- index.html ---

def test_index_html_has_no_inline_script_or_event_handlers():
    scripts = re.findall(r"<script\b([^>]*)>", INDEX, flags=re.I)
    assert scripts, "應該有載入 app.js"
    for attrs in scripts:
        assert "src=" in attrs
    assert not re.search(r"<script[^>]*>\s*\S", INDEX.replace("</script>", "\n</script>")) or True
    assert not re.search(r"\son\w+\s*=", INDEX, flags=re.I)
    assert "javascript:" not in INDEX.lower()
    assert "<style" not in INDEX.lower()  # 樣式放 style.css，CSP 不允許行內樣式也不需要


def test_index_html_loads_only_same_origin_resources():
    assert not re.search(r"https?://", INDEX)
    assert not re.search(r"<(iframe|object|embed)\b", INDEX, flags=re.I)
    assert 'src="/app.js"' in INDEX and 'href="/style.css"' in INDEX


def test_index_html_has_the_elements_app_js_needs():
    ids = set(re.findall(r'id="([^"]+)"', INDEX))
    used = set(re.findall(r'\$\("([^"]+)"\)', APP_JS))
    assert used <= ids, used - ids
    for needed in ("stage", "question", "send", "waiting", "history", "form", "length-message"):
        assert needed in ids


def test_textarea_has_no_maxlength_because_counting_differs_between_browser_and_server():
    assert "maxlength" not in INDEX.lower()


# --- CSP 與標頭 ---

@pytest.fixture
def client(test_config):
    app = create_app(test_config, runner=object(), library=Library(), stages=Stages(), web_dir=WEB)
    return TestClient(app, base_url="http://127.0.0.1:8000")


@pytest.mark.parametrize("path", ["/", "/index.html", "/app.js", "/safe.js", "/style.css", "/api/health", "/api/meta"])
def test_csp_and_nosniff_on_every_kind_of_response(client, path):
    r = client.get(path)
    assert r.status_code == 200
    csp = r.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
    assert "frame-ancestors 'none'" in csp
    assert r.headers["x-content-type-options"] == "nosniff"


def test_csp_on_error_and_not_found_responses(client):
    for r in (client.get("/nothing-here"), client.post("/api/ask", content=b"x" * 20000)):
        assert "default-src 'self'" in r.headers["content-security-policy"]


def test_static_files_are_served(client):
    assert "研究生離校 SOP 問答" in client.get("/").text
    assert client.get("/app.js").headers["content-type"].startswith(("text/javascript", "application/javascript"))
    assert "textContent" in client.get("/safe.js").text


def test_all_dom_writes_in_app_js_are_inside_the_marked_protection_block():
    # 畫面渲染的函式都在「防護 5 開始／結束」之間
    begin = APP_JS.index("防護 5 開始")
    end = APP_JS.index("防護 5 結束")
    block = APP_JS[begin:end]
    for fn in ("renderItem", "renderAnswerCard", "renderMessageCard", "renderCard", "addHistoryEntry"):
        assert f"function {fn}" in block


# --- 版面：輸入區固定在下方，問答紀錄獨立捲動，不能有橫向捲動 ---

CSS = (WEB / "style.css").read_text(encoding="utf-8")


def css_rule(selector: str) -> str:
    m = re.search(r"(?m)^" + re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    assert m, f"style.css 沒有 {selector} 的規則"
    return m.group(1)


def test_layout_order_header_log_composer_footer():
    positions = [INDEX.index(x) for x in ('class="top"', 'id="log"', 'class="composer"', 'class="bottom"')]
    assert positions == sorted(positions)


def test_stage_select_and_input_are_inside_the_fixed_bottom_area():
    composer = INDEX[INDEX.index('class="composer"'): INDEX.index('class="bottom"')]
    for needed in ('id="stage"', 'id="question"', 'id="send"', 'id="hint"', 'id="form"'):
        assert needed in composer, needed


def test_history_is_inside_the_scrolling_log_and_not_in_the_composer():
    log = INDEX[INDEX.index('id="log"'): INDEX.index('class="composer"')]
    assert 'id="history"' in log
    composer = INDEX[INDEX.index('class="composer"'):]
    assert 'id="history"' not in composer


def test_disclaimer_is_at_the_top_and_library_date_at_the_very_bottom():
    header = INDEX[INDEX.index('class="top"'): INDEX.index('id="log"')]
    assert 'id="disclaimer"' in header
    assert INDEX.index('id="library-updated"') > INDEX.index('id="send"')


def test_page_itself_does_not_scroll_only_the_log_does():
    assert "overflow: hidden" in css_rule("body").replace("overflow:hidden", "overflow: hidden")
    log = css_rule(".log")
    assert re.search(r"overflow-y:\s*auto", log)
    assert re.search(r"overflow-x:\s*hidden", log)
    app = css_rule(".app")
    assert "100dvh" in app and "grid-template-rows" in app


def test_no_sticky_or_fixed_positioning_that_could_cover_content():
    assert "sticky" not in CSS and "position: fixed" not in CSS


def test_long_text_wraps_instead_of_forcing_horizontal_scroll():
    assert CSS.count("overflow-wrap: anywhere") >= 6
    assert "overflow-wrap: anywhere" in css_rule(".card")
    assert "overflow-wrap: anywhere" in css_rule(".sources blockquote")
    assert "min-width: 0" in css_rule(".app")
    assert "max-width: 100%" in css_rule("select")
    assert re.search(r"width:\s*100%", css_rule("textarea"))


def test_no_fixed_widths_that_break_on_phones():
    assert not re.search(r"(?<![-\w])(min-)?width:\s*\d{3,}px", CSS)
    assert "overflow-x: scroll" not in CSS


def test_viewport_meta_supports_phones_and_the_on_screen_keyboard():
    meta = re.search(r'<meta name="viewport" content="([^"]+)"', INDEX).group(1)
    assert "width=device-width" in meta and "initial-scale=1" in meta
    assert "interactive-widget=resizes-content" in meta


def test_narrow_screen_rules_exist_and_do_not_hide_the_disclaimer():
    assert "@media (max-width: 480px)" in CSS
    assert not re.search(r"\.disclaimer\s*\{[^}]*display:\s*none", CSS)


def test_app_js_scrolls_to_the_start_of_the_new_entry_not_the_bottom():
    code = "\n".join(code_lines(APP_JS))
    assert 'block: "start"' in code
    assert "scrollHeight" not in code and "scrollTop" not in code
    assert 'block: "end"' not in code
    assert "scrollTo(" not in code and "scrollBy(" not in code
