"""Real HTTP smoke test: the stdlib server on an ephemeral port must
serve all three OpenAI-compatible endpoints with the right shapes."""
import json
import threading
import urllib.request
from datetime import datetime
from http.server import ThreadingHTTPServer

from tesla_cabin_sentinel.config import Settings, VehicleConfig
from tesla_cabin_sentinel.server import make_handler
from tesla_cabin_sentinel.service import CabinSentinelService


def _start_server():
    settings = Settings(vehicles=[VehicleConfig("Model Y", "VINY")],
                        ai_mode="never", alert_after_minutes=0)
    service = CabinSentinelService(
        settings, now_fn=lambda: datetime(2026, 10, 30, 12, 0),
        alert_sink=lambda m: None)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def _call(base, method, path, payload=None):
    req = urllib.request.Request(
        base + path, method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        return resp.status, json.loads(resp.read())


def test_http_surface():
    httpd, base = _start_server()
    try:
        status, body = _call(base, "GET", "/health")
        assert status == 200 and body["status"] == "ok"
        status, body = _call(base, "GET", "/v1/models")
        assert status == 200
        assert body["data"][0]["id"] == "tesla-cabin-sentinel"
        status, body = _call(base, "POST", "/v1/chat/completions", {
            "model": "tesla-cabin-sentinel",
            "messages": [{"role": "user",
                          "content": "child alone in the Model Y"}]})
        assert status == 200
        assert body["choices"][0]["message"]["role"] == "assistant"
        assert "ALERT" in body["choices"][0]["message"]["content"]
        status, body = _call(base, "POST", "/v1/embeddings", {
            "input": "child left behind"})
        assert status == 200
        assert len(body["data"][0]["embedding"]) == 384
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_http_bearer_auth_enforced():
    settings = Settings(vehicles=[VehicleConfig("Model Y", "VINY")],
                        ai_mode="never", server_api_key="secret123")
    service = CabinSentinelService(settings, alert_sink=lambda m: None)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        try:
            _call(base, "GET", "/v1/models")
            raise AssertionError("should have been 401")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401
    finally:
        httpd.shutdown()
        httpd.server_close()
