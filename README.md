# thesis-sop-agent

企管系研究生離校 SOP 問答 agent：本機網頁，學生選階段、輸入問題，agent 只根據文件庫回答並附出處。

- 需求：`docs/requirements.md`
- 架構：`docs/architecture.md`
- 開發規則：`CLAUDE.md`

目前進度：階段 1（防護）、階段 2（文件庫）已 commit；**階段 3（問答畫面）已完成，等待驗收**。流程圖、文件清單、情境範例還沒做（階段 4、5）。

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

畫面邏輯（`web/app.js`）的測試用 Node 內建的測試執行器在假的 DOM 上執行（`tests/js/`，由 `tests/test_web_js.py` 呼叫）。
Node 只是開發用工具；沒有安裝 Node 時這幾個測試會被略過，其餘照跑。

## 啟動伺服器

```text
uv run python -m sop_agent.server
```

打開 <http://127.0.0.1:8000>。只綁定 `127.0.0.1`。

- 啟動時載入文件庫一次，**換新版文件要重啟伺服器**。
- 文件庫是空的，伺服器照常啟動（學生提問會看到「無法回答」訊息）；只有文件檔頭有錯才會停下來並列出檔名與問題。
- 階段選單來自 `data/stages.json`。目前是占位內容（`"placeholder": true`），畫面上標「範例資料，非正式規定」；拿到系辦文件、決定階段後再換掉並改成 `false`。
- 文件檔頭的 `stages` 有不在階段選單裡的名稱時，啟動時會印警告（那些文件選了階段後會選不到）。
- 請求本文上限在 `config.toml` 的 `limits.max_body_bytes`（預設 8192），超過回 400，不呼叫模型。

| 路徑 | 說明 |
|---|---|
| `GET /` | 問答頁 |
| `GET /api/meta` | 階段選單、文件庫最後更新日期、字數上限、固定文字 |
| `POST /api/ask` | `{"question": "...", "stage": "口試前" 或 null}` → 四種卡片之一（`answer`、`no_info`、`out_of_scope`、`unavailable`），都回 200；輸入不合格回 400；來源不符回 403 |

## 示範伺服器（不花額度）

```text
uv run python tests/demo_server.py
```

假的 claude ＋ 假文件（`tests/fixtures/library_xss/`），只綁 `127.0.0.1`，套用和正式伺服器同一個 `create_app`（同樣的 Host/Origin 檢查與 CSP）。
在問題裡打關鍵字會得到不同的結果，啟動時會印出完整對照。紀錄檔寫到暫存資料夾，不寫進專案的 `logs/`。

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
| 3 問題當資料（組 prompt、中和標記） | `src/sop_agent/prompt.py` | 14–77 |
| 3 問題當資料（輸入驗證、階段白名單） | `src/sop_agent/ask.py` | 85–102 |
| 4 輸出檢查（格式） | `src/sop_agent/schema.py` | 29–102 |
| 4 輸出檢查（出處驗證） | `src/sop_agent/verify.py` | 15–112 |
| 4 輸出檢查（解析、驗證、沒過改查不到卡） | `src/sop_agent/ask.py` | 138–153 |
| 5 請求來源檢查與回應標頭 | `src/sop_agent/server.py` | 28–56、113–125 |
| 5 請求本文大小限制 | `src/sop_agent/server.py` | 59–77 |
| 5 伺服器端移除控制字元 | `src/sop_agent/cards.py` | 46–53 |
| 5 前端安全寫入 | `web/safe.js` | 4–29 |
| 5 畫面只用 safe.js 寫入 | `web/app.js` | 16–80 |

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

### 5. 完整流程（`--e2e`，階段 3 新增）

```text
uv run python -m sop_agent.manual_check --e2e
```

用**測試文件**（`tests/fixtures/library_ok/`，永遠不讀真的 `library/`）跑完整流程：選文件 → prompt → claude → 驗證 → 卡片。問 4 題，**呼叫 claude 4 次**：

| 題目 | 階段 | 預期 |
|---|---|---|
| 口試申請表要在什麼時候送？要送到哪裡？ | 口試前 | 答案卡，出處片段是文件原文 |
| When must I submit the oral exam application form, and where? | 口試前 | 英文答案；出處片段維持文件原本的中文並通過驗證 |
| 今天台北的天氣如何？ | （不指定） | 範圍外卡 |
| 口試委員的車馬費是多少？ | 口試前 | 查不到卡 |

估計用量：每次約 3,000 到 4,000 token（階段 1 實測約 2,400，加上測試文件），合計約 1.2 萬到 1.6 萬 token。
這是人工觀察，不是通過／失敗判斷，因為模型每次的回答可能不同。紀錄檔寫到暫存資料夾。

## 手動檢查（示範伺服器，不花額度）

自動測試涵蓋了伺服器端的內容和（在假 DOM 上的）畫面邏輯，但沒有真正的瀏覽器。請在瀏覽器裡親自確認：

```text
uv run python tests/demo_server.py
```

打開 <http://127.0.0.1:8000>，依序做：

1. **XSS：** 在問題輸入 `<script>alert(1)</script><img src=x onerror=alert(1)>` 後送出。預期：問題顯示成純文字、沒有彈出視窗。
2. **XSS（回答端）：** 問 `xss 測試`。預期：回答、下一步、相關表單、期限（含「適用」）、窗口、出處標題、原文片段，所有欄位的 `<script>`、`<img onerror>` 都顯示成純文字，沒有彈窗。
3. **CSP：** 開瀏覽器 DevTools 的 Console（F12）。預期：沒有 Content Security Policy 違規訊息，也沒有其他紅字錯誤。
4. **四種卡片：** 分別問「口試申請表什麼時候送」（答案卡）、`今天天氣`（範圍外卡）、`這題查不到`（查不到卡）、`伺服器壞掉`（「無法回答」訊息）。預期：樣式不同、文字不同，查不到卡與範圍外卡沒有四個欄位。
5. **等待提示：** 問 `慢`。預期：送出後按鈕停用、輸入框停用、出現轉圈圈與「正在查文件…」，約 4 秒後恢復。
6. **字數：** 貼上超過 500 字的文字。預期：送出鈕停用、旁邊出現「問題太長，請縮短」；刪到 500 字以內恢復。空白也不能送出。
7. **階段：** 不選階段問一般問題 → 答案卡最上面有「你還沒選目前階段，以下回答是依整個流程的文件整理的」；選「口試前」再問 → 沒有這句。選「離校」再問 → 查不到卡（假 claude 引用了沒放進這次 prompt 的文件，被驗證擋下來）。階段選單旁有「範例資料，非正式規定」。
8. **版面與提示：** 輸入框旁有「每次提問是獨立的，請把完整情況寫在問題裡」；最上面標題下方有免責提示；最底下（輸入區下面）有「文件庫最後更新日期：2025-10-01」；重新整理後問答清空。
9. **問 5 題以上後，輸入區仍在畫面下方：** 連續問 5 題以上（問 `慢` 以外的任何問題，可以多問幾次 `xss 測試` 讓卡片變長）。預期：**階段選單、輸入框、送出鈕一直都在畫面下方看得到**，不需要捲到最上面；整個頁面本身不會捲動，只有中間的問答紀錄自己捲動。
10. **自動捲到新問答的開頭：** 問一個長答案（`xss 測試`）。預期：畫面捲到「那一則」問答的開頭（先看到你的問題，再看到答案卡的開頭），不是捲到最底；答案比紀錄區高時，仍然從開頭看起。用滑鼠往上捲可以看到之前的問答。
11. **窄螢幕與手機寬度：** 把瀏覽器視窗縮窄到約 360px（或 F12 的手機模式，例如 iPhone SE／Pixel）。預期：整頁**沒有橫向捲動**；輸入區仍在下方、階段選單看得到；長字串（例如貼一段很長的網址當問題）會換行，不會把版面撐寬；可以正常輸入與送出。
12. **矮視窗：** 把視窗高度縮到約 480px。預期：輸入區仍完整可用，問答紀錄區變小但還能捲動（空間會比較緊，這是預期的）。

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

## 驗證清單（架構文件第 15 節，步驟 3：問答）對應的測試

「假 DOM」指 `tests/js/app_flow.test.mjs`，在假的 DOM 上實際執行 `web/app.js`（需要 Node）。「手動」指上面的「手動檢查（示範伺服器）」。

| 項目 | 自動 | 手動 |
|---|---|---|
| 空白不能送出；501 字不能送出（前端和直接打 API 都擋） | API：`test_ask_api.py`（空白、500 字通過、501 字拒絕、不呼叫模型、字元計算）；前端：假 DOM（空白、500、501、表情符號、直接觸發送出） | 手動 6 |
| 送出後按鈕停用並顯示「正在查文件…」，回來後恢復 | 假 DOM（停用、顯示、恢復、失敗後也恢復、處理中再送被忽略） | 手動 5 |
| 回答卡四欄俱全，沒寫的欄位顯示「文件未載明」 | `test_cards.py`（四欄、整欄缺、只缺期限或窗口）；假 DOM（畫出來） | 手動 4 |
| 出處欄顯示「文件名稱（版本日期）」和原文片段 | `test_cards.py`；`test_ask_api.py`（片段是文件原文、含換行）；假 DOM | 手動 4 |
| 期限旁標示適用學期與引用文件的版本日期 | `test_cards.py`（有學期、沒學期、兩份文件、空白學期） | 手動 4 |
| 沒選階段顯示提醒，選了不顯示 | `test_cards.py`、`test_ask_api.py`；假 DOM | 手動 7 |
| 模型回 `not_in_documents` 顯示查不到卡；回 `out_of_scope` 顯示範圍外卡；文字不同 | `test_cards.py`、`test_ask_api.py`；假 DOM | 手動 4 |
| 逾時、沒登入、找不到 claude、忙碌：「無法回答」訊息，沒有技術細節 | `test_ask_api.py`（四種錯誤、忙碌、未預期的例外、`library_empty`、`over_budget`、訊息不含技術字眼）；假 DOM（連線失敗） | 手動 4 |
| 每次提問獨立：第二次的 prompt 沒有第一次的問答 | `test_ask_api.py::test_each_question_is_independent` | 手動 8（舊問答可往上捲） |
| 輸入框旁有「每次提問是獨立的，請把完整情況寫在問題裡」 | `test_cards.py`、`test_ask_api.py`（/api/meta）；假 DOM（畫面上有這句） | 手動 8 |
| 版面：輸入區（階段選單、輸入框、送出鈕、提示）固定在下方，問答紀錄獨立捲動，整頁不捲動 | `test_web_static.py`（區塊順序、輸入區內容、紀錄區 `overflow-y: auto`、`100dvh`、沒有 sticky／fixed）；另外我用 Edge 無頭模式量過實際版面（見下） | 手動 9 |
| 新問答出現後捲到「那一則」的開頭，不是最底 | 假 DOM（`block: "start"`、問題加入與卡片加入各對齊一次、不捲整個紀錄區）；`test_web_static.py`（沒有 `scrollHeight`／`scrollTop`／`block: "end"`） | 手動 10 |
| 窄螢幕與手機寬度沒有橫向捲動 | `test_web_static.py`（長字串換行規則、沒有固定大寬度、viewport meta）；Edge 無頭實測 300／320／360／390px | 手動 11、12 |
| 英文提問，答案是英文，片段維持原語言並通過驗證 | `test_ask_api.py`（片段以文件原文顯示、通過驗證；答案語言由模型決定，無法自動測） | **`--e2e` 第 2 題（真的 claude）** |
| 畫面上的 `<script>` 顯示為純文字（延自階段 1） | `test_web_static.py`、`test_web_js.py`（假 DOM）、`test_ask_api.py`（HTML 字串原樣回傳）、`test_web_safe.py` | 手動 1、2、3 |
| 請求本文大小限制（config 的 `max_body_bytes`） | `test_ask_api.py`（超過、剛好等於、分段傳送沒有 Content-Length、由 config 決定） | — |
| `--e2e` 只用測試文件、示範伺服器只綁 127.0.0.1 並套用來源檢查 | `test_demo_and_e2e.py` | — |
