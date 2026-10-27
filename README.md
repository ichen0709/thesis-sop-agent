# thesis-sop-agent

企管系研究生離校 SOP 問答 agent：本機網頁，學生選階段、輸入問題，agent 只根據文件庫回答並附出處。

- 需求：`docs/requirements.md`
- 架構：`docs/architecture.md`
- 開發規則：`CLAUDE.md`

目前進度：**階段 1（防護）**。還沒有問答、文件庫載入、流程圖或任何畫面。

## 環境

- Python 3.12、[uv](https://docs.astral.sh/uv/)
- 已登入的 Claude Code（`claude`）。不需要 API 金鑰，也不要設 `ANTHROPIC_API_KEY`。

```text
uv sync
```

## 執行測試

```text
uv run pytest
```

全部使用假的 `claude`（`tests/fakes/fake_claude.py`），不花額度，約 15 秒。

## 啟動伺服器骨架

```text
uv run python -m sop_agent.server
```

只綁定 `127.0.0.1:8000`。目前只有 `GET /api/health` 和還沒實作的 `POST /api/ask`。

## 五項防護在哪裡

每項在程式裡用「防護 N 開始／結束」註解標出，一開始全部開啟。行號是大約值，以搜尋「防護 N 開始」為準。

| 防護 | 檔案 | 大約行號 |
|---|---|---|
| 1 暫存資料夾 | `src/sop_agent/runner.py` | 125–147 |
| 2 權限限制（旗標、移除金鑰環境變數） | `src/sop_agent/runner.py` | 34–76 |
| 3 問題當資料 | `src/sop_agent/prompt.py` | 14–77 |
| 4 輸出檢查（格式） | `src/sop_agent/schema.py` | 29–102 |
| 4 輸出檢查（出處驗證） | `src/sop_agent/verify.py` | 15–112 |
| 5 請求來源檢查與回應標頭 | `src/sop_agent/server.py` | 18–46、60–72 |
| 5 前端安全寫入 | `web/safe.js` | 4–29 |

`tests/test_protection_markers.py` 會檢查五項標記都在、開始與結束成對，也會檢查沒有關閉防護的開關。

## 手動檢查（會用掉額度）

這些要用真的 `claude`，由你決定何時跑。每次執行 = 呼叫 claude 一次。

實測用量：每次呼叫約 2,400 到 3,700 token（不隔離最多）。實際數字會印在每次輸出的外層結果裡，方案額度的比例我無法得知。

### 1. 旗標組合在實際環境的效果，與 `--restricted` 對照 `--setting-sources`

問題預設是請模型列出它看得到的 skills、外掛、hooks 注入的指示。跑法（已跑過）：

```text
uv run python -m sop_agent.manual_check --isolation none
uv run python -m sop_agent.manual_check --isolation restricted
uv run python -m sop_agent.manual_check --isolation sources-empty
uv run python -m sop_agent.manual_check --isolation sources-project
uv run python -m sop_agent.manual_check --isolation restricted+sources-empty
```

**結果（已完成）：**

| 隔離方式 | 約用 token | 回合數 |
|---|---|---|
| 不隔離（`none`） | 3,697 | 未記錄 |
| 只用 `--restricted` | 2,654 | 多一個回合 |
| `sources-empty`（`--setting-sources ""`） | 約 2,390 | 2 |
| `sources-project` | 約 2,390 | 2 |
| `restricted+sources-empty` | 約 2,390 | 2 |

結論：使用者設定約佔 1,300 token，被 `--setting-sources ""` 擋掉。**採用 `--restricted` 加 `--setting-sources ""`**，再加 `--tools ""`（`runner.py` 固定帶）。單用 `--restricted` 比較貴而且多一個回合。已寫入 `config.toml` 的 `claude.isolation_flags`。

### 2. `--output-format json` 外層結果裡，模型內容的欄位名稱

```text
uv run python -m sop_agent.manual_check --answerable
```

**結果（已完成）：** 用 `structured_output`（物件），不用外層的 `result` 字串。已寫入 `config.toml` 的 `claude.result_fields`。

### 3. 金鑰環境變數確實被移除（尚未驗證）

```text
uv run python -m sop_agent.manual_check --fake-api-key
```

這個指令會在自己的環境放一個假的 `ANTHROPIC_API_KEY`。預期：照常回答。
如果出現 invalid API key 之類的錯誤，代表假金鑰被帶進了 `claude`，要回頭查 `runner.py` 的 `build_env`。

### 4. 沒登入時的錯誤訊息（尚未驗證）

`runner.py` 的 `_classify_failure` 是用關鍵字猜「沒登入」，關鍵字還沒用真的輸出確認。
有機會看到真的沒登入的輸出時，核對一次。

### 這一階段無法測的項目

「畫面上的 `<script>` 顯示為純文字」需要真正的問答畫面，延到階段 3。階段 1 只有 `innerHTML` 掃描（`tests/test_web_safe.py`）和 `web/safe.js`。

## 驗證清單（架構文件第 15 節，步驟 1）對應的測試

| 項目 | 測試 |
|---|---|
| 子行程沒有 `ANTHROPIC_API_KEY` | `test_runner.py::test_child_process_does_not_see_api_key`、`test_build_env_strips_key_variables` |
| 工作目錄是空的暫存資料夾，結束與失敗後已刪除 | `test_runner.py::test_runs_in_empty_temp_directory_and_removes_it`、`test_temp_directory_removed_when_claude_fails` |
| 問題只在 stdin，不在命令列 | `test_runner.py::test_question_goes_only_through_stdin` |
| 旗標齊全、沒有跳過權限的旗標 | `test_runner.py::test_argv_has_required_flags_and_no_permission_bypass` |
| 逾時終止子行程 | `test_runner.py::test_timeout_kills_the_child` |
| 問題含 `</student_question>` 與假指令，結構沒破壞 | `test_prompt.py::test_question_cannot_close_its_block`、`test_tag_variants_are_neutralized` |
| 文件含 `</document>`，結構沒破壞 | `test_prompt.py::test_document_cannot_close_its_block` |
| 階段不在白名單被拒絕 | `test_prompt.py::test_stage_not_in_whitelist_is_rejected` |
| 前端沒有 `innerHTML` | `test_web_safe.py` |
| 回應有 CSP | `test_server_guard.py::test_csp_header_*` |
| 其他 Origin、`null`、錯誤 Host 被拒絕且沒呼叫模型；無 Origin 與同源通過 | `test_server_guard.py` |
| 被拒絕只記 `bad_origin`、`request_check` | `test_server_guard.py::test_rejection_logs_only_type_and_step` |
| 出處驗證（通過／不通過各情形、換行不同通過、全形半形、顯示文件原文、整則作廢、`cite` 範圍） | `test_verify.py` |
| 格式不對、缺欄位、型別錯 | `test_schema.py` |
| 紀錄檔只有時間、類型、步驟，無問題內容、設定值、本機路徑 | `test_applog.py`、`test_server_guard.py` |
| 手動（已完成）：旗標組合效果、`--setting-sources`、外層欄位名稱 | 上面的「手動檢查」1、2 |
| 手動（尚未驗證）：假金鑰實機確認、沒登入的錯誤訊息 | 上面的「手動檢查」3、4 |
