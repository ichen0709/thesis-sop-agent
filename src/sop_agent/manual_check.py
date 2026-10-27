"""手動檢查：用真的 claude 跑一次，印出原始外層結果。會用掉額度，由人決定何時跑。

用法見 README 的「手動檢查」。每次執行 = 呼叫 claude 一次。
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import tempfile
from pathlib import Path

from sop_agent.applog import AppLog
from sop_agent.ask import AskService, Stages
from sop_agent.config import PROJECT_ROOT, Config, load_config
from sop_agent.library import load_library
from sop_agent.prompt import SYSTEM_PROMPT, build_prompt
from sop_agent.runner import Runner, RunnerError, SubprocessRunner
from sop_agent.schema import SourceDoc, json_schema_text

ISOLATION = {
    "none": [],
    "restricted": ["--restricted"],
    "sources-empty": ["--setting-sources", ""],
    "sources-project": ["--setting-sources", "project"],
    "restricted+sources-empty": ["--restricted", "--setting-sources", ""],
}

TEST_DOC = SourceDoc(
    id="manual-check",
    title="手動檢查用的測試文件",
    version_date="2000-01-01",
    body="口試申請表應於口試日前 14 日送交系辦。",
)

CANARY_QUESTION = (
    "請在 answer 欄位列出你目前看得到的 skills、外掛、hooks 注入的額外指示名稱；"
    "如果完全沒有，answer 寫「無」。status 用 out_of_scope。"
)


# --e2e 只用測試文件，永遠不讀真的 library/
E2E_LIBRARY = PROJECT_ROOT / "tests" / "fixtures" / "library_ok"
E2E_STAGES = Stages(names=("口試前", "口試後", "論文上傳", "離校"), placeholder=True)
E2E_QUESTIONS = [
    ("中文，文件裡有答案", "口試申請表要在什麼時候送？要送到哪裡？", "口試前"),
    ("英文，文件裡有答案", "When must I submit the oral exam application form, and where?", "口試前"),
    ("不在服務範圍", "今天台北的天氣如何？", None),
    ("文件裡沒有答案", "口試委員的車馬費是多少？", "口試前"),
]


def build_e2e_service(runner: Runner, config: Config | None = None) -> AskService:
    """用測試文件建立問答服務。紀錄檔寫到暫存資料夾，不寫進專案的 logs/。"""
    config = config or load_config()
    log_dir = Path(tempfile.mkdtemp(prefix="sop-e2e-"))
    config = dataclasses.replace(config, log_path=log_dir / "app.log")
    library = load_library(E2E_LIBRARY)
    return AskService(config, library, E2E_STAGES, runner, AppLog(config.log_path))


def select_e2e_questions(only: str | None) -> list[tuple[str, str, str | None]]:
    """only 例如 "1,2" = 只跑第 1、2 題（用來省額度）。不給 = 全部。題號從 1 開始。"""
    if not only:
        return list(E2E_QUESTIONS)
    try:
        numbers = sorted({int(x) for x in only.split(",") if x.strip()})
    except ValueError:
        raise SystemExit("--only 只接受題號，例如 --only 1,2") from None
    if not numbers or any(n < 1 or n > len(E2E_QUESTIONS) for n in numbers):
        raise SystemExit(f"--only 的題號必須在 1 到 {len(E2E_QUESTIONS)} 之間")
    return [E2E_QUESTIONS[n - 1] for n in numbers]


def run_e2e(only: str | None = None) -> int:
    """用真的 claude 跑完整流程（選文件→prompt→claude→驗證→卡片）。每題 = 呼叫 claude 一次。"""
    questions = select_e2e_questions(only)
    cfg = load_config()
    runner = SubprocessRunner(
        command=cfg.claude_command,
        json_schema=json_schema_text(),
        isolation_flags=cfg.isolation_flags,
        model_name=cfg.model_name,
        timeout_seconds=cfg.timeout_seconds,
    )
    service = build_e2e_service(runner, cfg)
    print(f"文件庫：{E2E_LIBRARY}（測試文件，不是真的 library/）\n")
    print(f"這次會問 {len(questions)} 題 = 呼叫 claude {len(questions)} 次\n")
    for title, question, stage in questions:
        q, st = service.validate(question, stage)
        card = service.ask(q, st)
        print(f"=== {title} | 階段：{st or '（未指定）'}\n問：{q}")
        print(json.dumps(card, ensure_ascii=False, indent=2))
        print()
    print("提醒：這是人工觀察，不是通過／失敗判斷；模型每次的回答可能不同。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--isolation", choices=sorted(ISOLATION), default=None,
                    help="不給就用 config.toml 的 isolation_flags")
    ap.add_argument("--question", default=None, help="預設是偵測外掛／hooks 影響的問題")
    ap.add_argument("--answerable", action="store_true",
                    help="改問文件裡有答案的問題，用來看 structured_output 的欄位")
    ap.add_argument("--fake-api-key", action="store_true",
                    help="先在自己的環境設一個假的 ANTHROPIC_API_KEY，確認它沒被帶進 claude")
    ap.add_argument("--show-argv", action="store_true")
    ap.add_argument("--e2e", action="store_true",
                    help="用測試文件跑完整流程，預設問 4 題（呼叫 claude 4 次）；不讀真的 library/")
    ap.add_argument("--only", default=None,
                    help="搭配 --e2e：只跑指定題號，例如 --only 1,2（只呼叫 claude 2 次，省額度）")
    args = ap.parse_args()

    if args.e2e:
        return run_e2e(args.only)

    cfg = load_config()
    flags = ISOLATION[args.isolation] if args.isolation else list(cfg.isolation_flags)
    if args.answerable:
        question = args.question or "口試申請表什麼時候要送？"
    else:
        question = args.question or CANARY_QUESTION

    if args.fake_api_key:
        os.environ["ANTHROPIC_API_KEY"] = "not-a-real-key-for-testing"

    runner = SubprocessRunner(
        command=cfg.claude_command,
        json_schema=json_schema_text(),
        isolation_flags=flags,
        model_name=cfg.model_name,
        timeout_seconds=cfg.timeout_seconds,
    )
    if args.show_argv:
        print("isolation flags:", flags)

    prompt = build_prompt(question, None, [TEST_DOC])
    try:
        out = runner.run(prompt, SYSTEM_PROMPT)
    except RunnerError as e:
        print("失敗：", e.error.value)
        return 1
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
