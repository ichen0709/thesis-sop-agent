# thesis-sop-agent

企管系研究生離校 SOP 問答 agent：本機網頁，學生選階段、輸入問題，agent 只根據文件庫回答並附出處。

- 需求：`docs/requirements.md`
- 架構：`docs/architecture.md`
- 開發規則：`CLAUDE.md`

目前進度：**階段 1（防護）已完成，階段 2（文件庫）完成**。還沒有問答、流程圖或任何畫面。

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

## 文件庫

系辦的文件轉成 Markdown 後放在 `library/`。原始檔（PDF、Word）放 `raw_docs/`，這個資料夾已被 git 忽略，不要 commit。

### 文件命名規則

- **檔名與 `id` 一律用小寫英文與連字號**，例如 `thesis-oral-exam-sop.md`，`id` 也是 `thesis-oral-exam-sop`。
- **檔名（不含 `.md`）必須和 `id` 完全相同。** 不一致程式會報錯。
- 程式實際允許的字元是英數字、底線、連字號，開頭必須是英數字；我們約定只用小寫英文與連字號，統一好找。
- **中文名稱放在檔頭的 `title`**，不要放在檔名。
- 一份文件一個檔案。新版不要改檔名：直接替換檔案，並更新 `version_date`。
- 舊版移到 `library_archive/`（程式不讀）。

### 範例檔頭

每份文件的最前面都要有檔頭，用 `---` 包起來；檔頭下面才是內文。這是 `library/thesis-oral-exam-sop.md` 的樣子（內容為示意）：

```text
---
id: thesis-oral-exam-sop
title: 論文口試辦理流程
source: 系辦（例如：系辦公告、系網頁網址，或提供者與提供日期）
version_date: 2025-09-01
public: true
stages: [口試前, 口試後]
---
（這裡開始是內文，逐字照系辦原文，不要改寫、不要翻譯。）
```

欄位說明：

| 欄位 | 必填 | 說明 |
|---|---|---|
| `id` | 是 | 唯一代號，等於檔名 |
| `title` | 是 | 文件的中文名稱，顯示在網頁的出處上 |
| `source` | 是 | 來源：誰提供、從哪裡取得 |
| `version_date` | 是 | 這份文件的版本日期，格式一定要 `YYYY-MM-DD`（例如 `2025-09-01`），必須是真的日期 |
| `public` | 是 | 只能寫 `true` 或 `false`。`false` 的文件**不會被載入**，也不會給模型讀 |
| `stages` | 否 | 適用的階段，寫成 `[階段一, 階段二]`。不寫或寫 `[]`，代表所有階段都適用。階段名稱要和網頁的階段選單一致（名稱還沒決定） |

轉文件時請注意：

- 內文要逐字照系辦原文。網頁顯示的出處片段會和內文逐字比對，改寫過的內文會讓引用對不上。
- 欄位名稱打錯（例如把 `stages` 打成 `stage`）會報錯，不會被默默忽略。
- 轉完檢查一次：

```text
uv run python -m sop_agent.library
```

這個指令會列出載入了哪些文件、略過幾份不公開的、文件庫最後更新日期；檔頭有問題會一次列出所有檔案和問題（只有檔名與問題種類，不印檔案內容），結束碼不是 0。

「文件庫最後更新日期」由程式從所有已載入文件的 `version_date` 取最大值，不需要手動輸入。

### 程式怎麼用文件庫

- `src/sop_agent/library.py`：掃描、讀檔頭、建登記表。`library_archive/` 不讀；`public: false` 不載入。
- `src/sop_agent/selector.py`：依階段選文件。沒選階段放全部；選了階段放「`stages` 為空」加上「`stages` 含該階段」的文件。結果有四種狀態：

| 狀態 | 意思 | 上層（階段 3）怎麼處理 |
|---|---|---|
| `ok` | 有文件可用 | 組 prompt |
| `library_empty` | 文件庫完全沒有可用文件 | 「無法回答」訊息，紀錄 `library_empty` |
| `no_docs_for_stage` | 有文件，但沒有任何一份適用於該階段 | 「查不到卡」 |
| `over_budget` | 總字數超過 `max_prompt_chars` | 暫時走「無法回答」訊息；挑段落尚未實作，等拿到真文件、量過大小再決定 |

- 選出的文件用 `Selection.by_id()` 交給 `verify.py` 核對 `doc_id`、`version_date`，並比對內文（檔頭不算內文）。

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

### 3. 金鑰環境變數確實被移除（已驗證，通過）

```text
uv run python -m sop_agent.manual_check --fake-api-key
```

這個指令會在自己的環境放一個假的 `ANTHROPIC_API_KEY`。預期：照常回答。
如果出現 invalid API key 之類的錯誤，代表假金鑰被帶進了 `claude`，要回頭查 `runner.py` 的 `build_env`。

**結果（已驗證，通過）：** 用真的 claude 執行，照常回答，`is_error` 為 false，沒有認證錯誤，代表假金鑰沒有被帶進子行程。

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
| 手動（已驗證，通過）：假金鑰實機確認 | 上面的「手動檢查」3 |
| 手動（尚未驗證）：沒登入的錯誤訊息 | 上面的「手動檢查」4 |

## 驗證清單（架構文件第 15 節，步驟 2：文件庫）對應的測試

| 項目 | 測試 |
|---|---|
| 檔頭缺 `source`、`version_date` 或 `public`：啟動時報錯並指出檔名 | `test_library.py::test_missing_required_field_names_the_file`（`id`、`title`、`source`、`version_date`、`public` 各一個）、`test_all_problems_are_reported_at_once` |
| `version_date` 格式錯誤：啟動時報錯 | `test_library.py::test_bad_version_date_is_rejected_and_names_the_file`（9 種錯誤寫法，含不存在的日期） |
| `public: false` 的文件不被載入 | `test_library.py::test_private_document_is_not_loaded`、`test_private_document_body_is_not_kept_anywhere`、`test_fixture_private_document_is_skipped`；`test_selector.py::test_private_document_is_never_selected`、`test_private_document_cannot_be_cited` |
| 最後更新日期等於所有已載入文件版本日期的最大值 | `test_library.py::test_last_updated_is_the_latest_version_date`、`test_last_updated_ignores_private_documents` |
| 新增更新的文件後，最後更新日期自動變動 | `test_library.py::test_last_updated_changes_automatically_when_a_newer_document_is_added`、`test_last_updated_follows_a_replaced_document` |
| 文件庫為空：不崩潰，問答回「無法回答」訊息 | `test_library.py::test_empty_folder_does_not_crash`、`test_folder_with_only_gitkeep_does_not_crash`、`test_missing_folder_does_not_crash`、`test_only_private_documents_gives_empty_library`、`test_real_library_folder_is_empty_except_gitkeep`；`test_selector.py::test_empty_library_gives_explicit_status_without_crashing`（狀態 `library_empty`，「無法回答」訊息本身在階段 3 接上） |
| 選了階段，只放該階段適用與不限階段的文件 | `test_selector.py::test_stage_selects_matching_and_all_stage_documents`、`test_stage_excludes_documents_for_other_stages`、`test_document_listing_several_stages_matches_each_of_them`、`test_stage_with_no_applicable_documents` |
| 沒選階段放全部 | `test_selector.py::test_no_stage_selects_all_loaded_documents`、`test_empty_string_stage_means_no_stage` |
| 與階段 1 銜接：登記表核對 `doc_id`、`version_date` 與內文（檔頭不算內文） | `test_selector.py` 最後一組（`test_selection_by_id_feeds_verify_and_a_body_quote_passes` 等） |
| 其他：`id` 與檔名一致、`id` 不重複、封存資料夾不讀、沒有檔頭、BOM／CRLF、錯誤訊息不含檔案內容 | `test_library.py` |
