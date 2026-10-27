"""假的 claude：測試用，不呼叫模型、不花額度。

行為由環境變數控制（測試透過 SubprocessRunner 的 extra_env 傳入）：
  FAKE_CLAUDE_RECORD  把自己看到的 argv、cwd、stdin、環境變數是否有金鑰寫到這個檔案
  FAKE_CLAUDE_MODE    ok（預設）、sleep、fail_login、fail_other
  FAKE_CLAUDE_SENTINEL  sleep 模式睡醒後寫這個檔案；有檔案代表沒被終止
"""

import json
import os
import sys
import time

mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")
record_path = os.environ.get("FAKE_CLAUDE_RECORD")
stdin_text = sys.stdin.buffer.read().decode("utf-8")

if record_path:
    cwd = os.getcwd()
    with open(record_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "argv": sys.argv[1:],
                "cwd": cwd,
                "cwd_listing": os.listdir(cwd),
                "stdin": stdin_text,
                "has_api_key": any(k.upper() == "ANTHROPIC_API_KEY" for k in os.environ),
                "has_auth_token": any(k.upper() == "ANTHROPIC_AUTH_TOKEN" for k in os.environ),
                "has_oauth_token": any(k.upper() == "CLAUDE_CODE_OAUTH_TOKEN" for k in os.environ),
            },
            f,
            ensure_ascii=False,
        )

if mode == "sleep":
    time.sleep(float(os.environ.get("FAKE_CLAUDE_SLEEP", "3")))
    sentinel = os.environ.get("FAKE_CLAUDE_SENTINEL")
    if sentinel:
        with open(sentinel, "w", encoding="utf-8") as f:
            f.write("finished")
elif mode == "fail_login":
    print("Not logged in. Please run /login", file=sys.stderr)
    sys.exit(1)
elif mode == "fail_other":
    print("something broke", file=sys.stderr)
    sys.exit(2)
else:
    payload = {"status": "not_in_documents"}
    print(json.dumps({"type": "result", "is_error": False, "structured_output": payload}))
