"""示範伺服器：假的 claude ＋ 假文件，不呼叫模型、不花額度。

用來在瀏覽器裡親眼確認四種卡片、等待提示，以及 HTML 字串不會被執行。
只綁 127.0.0.1，套用和正式伺服器同一個 create_app（同樣的 Host/Origin 檢查與 CSP）。

執行：  uv run python tests/demo_server.py
"""

from __future__ import annotations

import dataclasses
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

import uvicorn  # noqa: E402

from sop_agent.applog import ErrorType  # noqa: E402
from sop_agent.ask import Stages, print_startup_notes  # noqa: E402
from sop_agent.config import load_config  # noqa: E402
from sop_agent.contact import load_contact  # noqa: E402
from sop_agent.library import load_library  # noqa: E402
from sop_agent.runner import RunnerError  # noqa: E402
from sop_agent.server import create_app  # noqa: E402

DEMO_LIBRARY = ROOT / "tests" / "fixtures" / "library_xss"
ORAL_QUOTE = "口試申請應於口試日前 14 日內，備妥下列文件，送交系辦"
XSS_BODY_QUOTE = '<script>alert("body-xss")</script> 請於口試前確認所有文件'
EVIL = '<script>alert("evil")</script><img src=x onerror=alert(1)>'


def _envelope(payload: dict) -> str:
    return json.dumps({"type": "result", "is_error": False, "structured_output": payload}, ensure_ascii=False)


def _normal_answer() -> dict:
    return {
        "status": "answered",
        "answer": "請在口試日前 14 日內備妥文件並送交系辦。",
        "next_steps": [{"text": "備妥口試申請表與論文初稿", "cite": [0]}],
        "forms": [{"text": "口試申請表", "cite": [0]}],
        "deadlines": [{"text": "口試日前 14 日內", "term": "114 學年度第 1 學期", "cite": [0]}],
        "contacts": [],
        "citations": [{"doc_id": "demo-oral-exam", "version_date": "2025-09-01", "quote": ORAL_QUOTE}],
    }


def _xss_answer() -> dict:
    return {
        "status": "answered",
        "answer": EVIL + " 這是回答本文",
        "next_steps": [{"text": EVIL + " 下一步", "cite": [0, 1]}],
        "forms": [{"text": "<b>粗體表單</b>", "cite": [1]}],
        "deadlines": [{"text": EVIL + " 期限", "term": EVIL + " 學期", "cite": [1]}],
        "contacts": [{"text": EVIL + " 窗口", "cite": [0]}],
        "citations": [
            {"doc_id": "demo-oral-exam", "version_date": "2025-09-01", "quote": ORAL_QUOTE},
            {"doc_id": "demo-xss", "version_date": "2025-10-01", "quote": XSS_BODY_QUOTE},
        ],
    }


class DemoRunner:
    """依問題裡的關鍵字，回傳事先寫好的結果。"""

    def run(self, prompt: str, system_prompt: str) -> str:
        question = prompt.split("<student_question>", 1)[-1].lower()
        if "xss" in question:
            return _envelope(_xss_answer())
        if "慢" in question or "slow" in question:
            time.sleep(4)
            return _envelope(_normal_answer())
        if "天氣" in question or "範圍" in question:
            return _envelope({"status": "out_of_scope"})
        if "查不到" in question:
            return _envelope({"status": "not_in_documents"})
        if "壞掉" in question:
            raise RunnerError(ErrorType.TIMEOUT)
        if "格式" in question:
            return "這不是 JSON"
        if "偽造" in question:
            bad = _normal_answer()
            bad["citations"][0]["quote"] = "這段話文件裡根本沒有出現過，是模型編的"
            return _envelope(bad)
        if "未載明" in question:
            minimal = _normal_answer()
            minimal.update({"forms": [], "deadlines": [], "next_steps": []})
            return _envelope(minimal)
        return _envelope(_normal_answer())


HELP = """\
示範伺服器已啟動：http://127.0.0.1:{port}
（假的 claude，不花額度；文件是 tests/fixtures/library_xss/ 的假資料）

在問題裡打這些關鍵字，會看到對應的結果：
  （一般問題）  答案卡：有下一步、表單、期限（含適用學期與版本）、出處；窗口顯示「文件未載明」
  xss           答案卡，但每個欄位、文件標題、原文片段都含 <script> 與 <img onerror>
  慢 / slow     等 4 秒才回答，用來看「正在查文件…」與按鈕停用
  天氣 / 範圍   範圍外卡
  查不到        查不到卡
  格式          模型回傳格式不對 → 查不到卡（不顯示原因）
  偽造          引用的片段是編的 → 驗證失敗 → 查不到卡
  壞掉          逾時 → 「無法回答」訊息
  （查不到、範圍外、無法回答三種卡下方會有「系所聯絡方式」，取自 data/contact.json）
  未載明        答案卡，下一步、表單、期限都顯示「文件未載明」
選階段「離校」再問一般問題：這個階段沒有放口試文件進 prompt，但假 claude 仍引用它，
  出處驗證會擋下來 → 查不到卡（可以看到「引用沒放進這次 prompt 的文件」會被拒絕）。
不選階段問一般問題：答案卡最上面有「你還沒選目前階段…」；選「口試前」則沒有。
按 Ctrl+C 結束。
"""


def main() -> int:
    config = load_config()
    log_dir = tempfile.mkdtemp(prefix="sop-demo-")
    config = dataclasses.replace(config, log_path=Path(log_dir) / "app.log")  # 不寫進專案的 logs/
    library = load_library(DEMO_LIBRARY)
    stages = Stages(names=("口試前", "口試後", "論文上傳", "離校"), placeholder=True)
    contact = load_contact(config.data_dir)  # 用正式的 data/contact.json，才看得到真的聯絡區塊
    print_startup_notes(library, stages, contact)
    app = create_app(config, runner=DemoRunner(), library=library, stages=stages, contact=contact)
    print(HELP.format(port=config.port))
    uvicorn.run(app, host="127.0.0.1", port=config.port)  # 只綁 127.0.0.1
    return 0


if __name__ == "__main__":
    sys.exit(main())
