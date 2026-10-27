"""本機網頁伺服器：請求來源檢查、安全標頭、問答 API，只綁 127.0.0.1。

路徑：
- GET  /api/health  健康檢查
- GET  /api/meta    給前端的設定（階段選單、文件庫最後更新日期、字數上限、固定文字）
- POST /api/ask     問答；四種卡片都回 200，輸入不合格回 400，來源不符回 403
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from sop_agent.applog import AppLog, ErrorType, Step
from sop_agent.ask import AskService, InputError, Stages, load_stages, print_startup_notes
from sop_agent.cards import DISCLAIMER, UI_TEXT, UNAVAILABLE_TEXT
from sop_agent.config import PROJECT_ROOT, Config, load_config
from sop_agent.library import Library, LibraryError, load_library
from sop_agent.runner import Runner, SubprocessRunner
from sop_agent.schema import json_schema_text

# 防護 5 開始：請求來源檢查與回應標頭
_ALLOWED_HOSTNAMES = {"127.0.0.1", "localhost"}
_CSP = "default-src 'self'; frame-ancestors 'none'"


def _host_allowed(host_header: str | None, port: int) -> bool:
    """Host 必須是 127.0.0.1 或 localhost；有帶埠號時必須等於設定的埠號。"""
    if not host_header:
        return False
    name, sep, host_port = host_header.partition(":")
    if name.lower() not in _ALLOWED_HOSTNAMES:
        return False
    if sep and host_port != str(port):
        return False
    return True


def _origin_allowed(origin: str | None, host_header: str) -> bool:
    """沒有 Origin 通過；有 Origin 必須與本機網頁同源（包含 "null" 一律拒絕）。"""
    if origin is None:
        return True
    return origin.lower() == f"http://{host_header}".lower()


def _add_security_headers(response) -> None:
    response.headers["Content-Security-Policy"] = _CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
# 防護 5 結束


# 防護 5 開始：請求本文大小限制（在解析 JSON 之前）
async def _read_limited_body(request: Request, limit: int) -> bytes | None:
    """讀取請求本文；超過 limit 位元組就回傳 None，不繼續讀，也不解析。"""
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > limit:
                return None
        except ValueError:
            return None
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)
# 防護 5 結束


def _bad_request(code: str) -> JSONResponse:
    return JSONResponse({"error": code}, status_code=400)


def default_runner(config: Config) -> SubprocessRunner:
    return SubprocessRunner(
        command=config.claude_command,
        json_schema=json_schema_text(),
        isolation_flags=config.isolation_flags,
        model_name=config.model_name,
        timeout_seconds=config.timeout_seconds,
    )


def create_app(
    config: Config | None = None,
    runner: Runner | None = None,
    web_dir: Path | None = None,
    library: Library | None = None,
    stages: Stages | None = None,
) -> FastAPI:
    config = config or load_config()
    library = library if library is not None else load_library(config.library_dir)
    stages = stages if stages is not None else load_stages(config.data_dir)
    runner = runner if runner is not None else default_runner(config)
    log = AppLog(config.log_path)
    service = AskService(config, library, stages, runner, log)

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.runner = runner
    app.state.log = log
    app.state.service = service

    # 防護 5 開始：請求來源檢查（套用在所有路徑）
    @app.middleware("http")
    async def guard(request: Request, call_next):
        host = request.headers.get("host")
        origin = request.headers.get("origin")
        if not _host_allowed(host, config.port) or not _origin_allowed(origin, host or ""):
            log.record(ErrorType.BAD_ORIGIN, Step.REQUEST_CHECK)  # 不記 Host、Origin 的值
            response = JSONResponse({"error": "forbidden"}, status_code=403)
        else:
            response = await call_next(request)
        _add_security_headers(response)
        return response
    # 防護 5 結束

    @app.get("/api/health")
    async def health():
        return {"ok": True}

    @app.get("/api/meta")
    async def meta():
        return {
            "stages": list(stages.names),
            "stages_placeholder": stages.placeholder,
            "library_updated": library.last_updated,
            "max_question_chars": config.max_question_chars,
            "disclaimer": DISCLAIMER,
            "unavailable_text": UNAVAILABLE_TEXT,  # 連不上伺服器時前端顯示的訊息
            "text": UI_TEXT,
        }

    @app.post("/api/ask")
    async def ask(request: Request):
        raw = await _read_limited_body(request, config.max_body_bytes)
        if raw is None:
            return _bad_request("body_too_large")
        try:
            data = json.loads(raw)
        except (ValueError, RecursionError):
            return _bad_request("bad_json")
        if not isinstance(data, dict):
            return _bad_request("bad_json")
        try:
            question, stage = service.validate(data.get("question"), data.get("stage"))
        except InputError as e:
            return _bad_request(e.code)
        # ask() 會呼叫 claude，可能等很久，所以放到執行緒裡跑
        card = await run_in_threadpool(service.ask, question, stage)
        return JSONResponse(card)

    static_dir = web_dir if web_dir is not None else PROJECT_ROOT / "web"
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="web")

    return app


def main() -> int:
    import uvicorn

    config = load_config()
    try:
        library = load_library(config.library_dir)
    except LibraryError as e:
        # 只有檔頭有錯才停下來；文件庫是空的照常啟動
        print("文件庫有問題，伺服器沒有啟動：", file=sys.stderr)
        for name, problem in e.problems:
            print(f"  {name}：{problem}", file=sys.stderr)
        return 1
    stages = load_stages(config.data_dir)
    print_startup_notes(library, stages)
    uvicorn.run(create_app(config, library=library, stages=stages), host=config.host, port=config.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
