"""手動檢查：用真的 claude 跑一次，印出原始外層結果。會用掉額度，由人決定何時跑。

用法見 README 的「手動檢查」。每次執行 = 呼叫 claude 一次。
"""

from __future__ import annotations

import argparse
import os
import sys

from sop_agent.config import load_config
from sop_agent.prompt import SYSTEM_PROMPT, build_prompt
from sop_agent.runner import RunnerError, SubprocessRunner
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
    args = ap.parse_args()

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
