"""用 Node 內建的測試執行器，在假的 DOM 上實際執行 web/app.js 與 web/safe.js。

需要安裝 Node（開發用，不是專案的執行環境）；沒有 Node 就略過這些測試，
略過時畫面邏輯只剩手動檢查（見 README）。
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="沒有安裝 Node，略過畫面邏輯的自動測試")


def run_node(*args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "WEB_DIR": str(ROOT / "web")}
    return subprocess.run([NODE, *args], capture_output=True, text=True, encoding="utf-8", env=env, timeout=120)


@pytest.mark.parametrize("name", ["app.js", "safe.js"])
def test_javascript_syntax_is_valid(name):
    result = run_node("--check", str(ROOT / "web" / name))
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("test_file", ["safe.test.mjs", "app_flow.test.mjs"])
def test_node_tests_pass(test_file):
    result = run_node("--test", str(ROOT / "tests" / "js" / test_file))
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-1000:]
