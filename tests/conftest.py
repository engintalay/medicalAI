"""Ortak test fixture'ları — gerçek API anahtarı/uzak tıbbi veri kullanılmaz."""

import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from app import app
from config.loader import get_config_loader


@pytest.fixture(scope="session")
def cfg():
    return get_config_loader()


@pytest.fixture(scope="session")
def client():
    return TestClient(app)


@pytest.fixture(scope="session")
def admin_headers(client, cfg):
    response = client.post("/admin/api/auth/login", json={
        "email": "admin@medicalai.com",
        "password": cfg.get("admin_default_password", "changeme123"),
    })
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["token"]}


@pytest.fixture(scope="session")
def patient(client):
    email = "qa_" + uuid.uuid4().hex[:10] + "@example.com"
    response = client.post("/api/auth/register", json={
        "email": email,
        "password": "Patient123!",
        "full_name": "QA Hasta",
        "height_cm": 175,
        "weight_kg": 72,
        "birth_year": 1990,
        "city": "Ankara",
    })
    assert response.status_code == 201, response.text
    payload = response.json()
    return {
        "email": email,
        "password": "Patient123!",
        "user_id": payload["user"]["user_id"],
        "headers": {"Authorization": "Bearer " + payload["token"]},
    }


@pytest.fixture
def patient_headers(patient):
    return patient["headers"]


@pytest.fixture
def fake_llm(cfg):
    """Yerel sahte OpenAI uyumlu sunucu; config geçici olarak değiştirilir."""

    class Handler(BaseHTTPRequestHandler):
        last = {}

        def _read(self):
            length = int(self.headers.get("Content-Length", "0"))
            return json.loads(self.rfile.read(length) or b"{}")

        def do_GET(self):
            Handler.last = {
                "path": self.path,
                "auth": self.headers.get("Authorization", ""),
            }
            payload = {"data": [{"id": f"fake-model-{i}"} for i in range(13)]}
            self._send(payload)

        def do_POST(self):
            body = self._read()
            Handler.last = {
                "path": self.path,
                "messages": body.get("messages", []),
                "auth": self.headers.get("Authorization", ""),
                "api_key_in_body": body.get("api_key"),
            }
            if self.path.rstrip("/").endswith("/models"):
                payload = {"data": [{"id": f"fake-model-{i}"} for i in range(13)]}
            else:
                payload = {"choices": [{"message": {
                    "role": "assistant",
                    "content": "Hemoglobin kanın oksijen taşımasını sağlar.",
                }}]}
            self._send(payload)

        def _send(self, payload):
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}/v1"

    keys = (
        "llm_provider", "llm_base_url", "llm_api_key", "llm_model",
        "llm_vision_supported", "vision_llm_enabled", "vision_llm_provider",
        "vision_llm_model", "vision_llm_base_url",
    )
    old = {key: cfg.get(key) for key in keys}
    cfg.set("llm_provider", "custom")
    cfg.set("llm_base_url", base_url)
    cfg.set("llm_api_key", "fake-key")
    cfg.set("llm_model", "fake-model")
    try:
        yield {"base_url": base_url, "handler": Handler}
    finally:
        for key, value in old.items():
            if value is not None:
                cfg.set(key, value)
        server.shutdown()
        server.server_close()
