import json

import pytest
from fastapi.testclient import TestClient

from sop_agent.server import create_app

BASE = "http://127.0.0.1:8000"


class CountingRunner:
    def __init__(self):
        self.calls = 0

    def run(self, prompt, system_prompt):
        self.calls += 1
        return "{}"


@pytest.fixture
def runner():
    return CountingRunner()


@pytest.fixture
def client(test_config, runner, tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    (web / "hello.txt").write_text("hi", encoding="utf-8")
    return TestClient(create_app(test_config, runner=runner, web_dir=web), base_url=BASE)


def log_lines(test_config):
    if not test_config.log_path.exists():
        return []
    return [json.loads(l) for l in test_config.log_path.read_text(encoding="utf-8").splitlines()]


# --- 通過的請求 ---

def test_no_origin_is_allowed(client):
    assert client.get("/api/health").status_code == 200


def test_same_origin_is_allowed(client):
    r = client.post("/api/ask", headers={"Origin": BASE})
    assert r.status_code == 501  # 通過檢查，只是還沒實作


def test_localhost_host_and_origin_are_allowed(client):
    r = client.post(
        "/api/ask",
        headers={"Host": "localhost:8000", "Origin": "http://localhost:8000"},
    )
    assert r.status_code == 501


def test_host_without_port_is_allowed(client):
    assert client.get("/api/health", headers={"Host": "localhost"}).status_code == 200


# --- 被拒絕的請求 ---

@pytest.mark.parametrize(
    "origin",
    ["http://evil.example", "null", "http://localhost:8000", "https://127.0.0.1:8000", "http://127.0.0.1:9999"],
)
def test_other_origin_is_rejected_with_403(client, runner, origin):
    # 注意：上面的 "http://localhost:8000" 與 Host 127.0.0.1:8000 不同源，也要拒絕
    r = client.post("/api/ask", headers={"Origin": origin})
    assert r.status_code == 403
    assert runner.calls == 0


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8000", "127.0.0.1.evil.example", "127.0.0.1:9999", "0.0.0.0:8000"])
def test_bad_host_is_rejected_with_403(client, runner, host):
    r = client.get("/api/health", headers={"Host": host})
    assert r.status_code == 403
    assert runner.calls == 0


def test_guard_applies_to_static_files_too(client):
    assert client.get("/hello.txt").status_code == 200
    assert client.get("/hello.txt", headers={"Origin": "http://evil.example"}).status_code == 403


def test_no_cors_allow_headers(client):
    r = client.get("/api/health")
    assert "access-control-allow-origin" not in r.headers
    r = client.options("/api/ask", headers={"Origin": "http://evil.example"})
    assert r.status_code == 403
    assert "access-control-allow-origin" not in r.headers


# --- 紀錄檔 ---

def test_rejection_logs_only_type_and_step(client, test_config):
    client.get(
        "/api/health",
        headers={"Origin": "http://SECRET-ORIGIN.example", "Host": "SECRET-HOST.example"},
    )
    lines = log_lines(test_config)
    assert len(lines) == 1
    assert set(lines[0]) == {"time", "error", "step"}
    assert lines[0]["error"] == "bad_origin" and lines[0]["step"] == "request_check"
    raw = test_config.log_path.read_text(encoding="utf-8")
    assert "SECRET" not in raw


def test_allowed_requests_write_nothing_to_log(client, test_config):
    client.get("/api/health")
    assert log_lines(test_config) == []


# --- 回應標頭 ---

def test_csp_header_on_normal_response(client):
    r = client.get("/api/health")
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"


def test_csp_header_on_rejected_response(client):
    r = client.get("/api/health", headers={"Origin": "http://evil.example"})
    assert r.status_code == 403
    assert "default-src 'self'" in r.headers["content-security-policy"]


def test_csp_header_on_static_file(client):
    assert "default-src 'self'" in client.get("/hello.txt").headers["content-security-policy"]


# --- 只綁 127.0.0.1 ---

def test_config_rejects_non_loopback_host(tmp_path):
    from sop_agent.config import ConfigError, load_config

    cfg = tmp_path / "config.toml"
    cfg.write_text('[server]\nhost = "0.0.0.0"\n', encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(cfg)


def test_default_config_binds_loopback():
    from sop_agent.config import load_config

    assert load_config().host == "127.0.0.1"
