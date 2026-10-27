"""最小的伺服器骨架：請求來源檢查、安全標頭、只綁 127.0.0.1。

階段 1 只有 /api/health 和一個還沒實作的 /api/ask，用來測試防護。問答在階段 3 才做。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from sop_agent.applog import AppLog, ErrorType, Step
from sop_agent.config import PROJECT_ROOT, Config, load_config
from sop_agent.runner import Runner

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


def create_app(
    config: Config | None = None,
    runner: Runner | None = None,
    web_dir: Path | None = None,
) -> FastAPI:
    config = config or load_config()
    log = AppLog(config.log_path)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.runner = runner
    app.state.log = log

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

    @app.post("/api/ask")
    async def ask():
        # 階段 3 才實作。這裡不呼叫模型。
        return JSONResponse({"kind": "not_implemented"}, status_code=501)

    static_dir = web_dir if web_dir is not None else PROJECT_ROOT / "web"
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="web")

    return app


def main() -> None:
    import uvicorn

    config = load_config()
    uvicorn.run(create_app(config), host=config.host, port=config.port)


if __name__ == "__main__":
    main()
