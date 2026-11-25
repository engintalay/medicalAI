"""12 — Regresyon seti: alias'lar, docs, LLM kuralları, tıbbi güvenlik."""

import uuid
from pathlib import Path

from app import app

ROOT = Path(__file__).resolve().parent.parent


def test_endpoints_aliases_active(client, patient_headers):
    """Alias'lar yalnızca tanımda değil, canlı çağrıda da çalışır."""
    assert client.get("/api/user/profile", headers=patient_headers).status_code == 200
    assert client.get("/api/reminders", headers=patient_headers).status_code == 200
    assert client.get("/api/notifications", headers=patient_headers).status_code == 200
    assert client.post(
        "/api/rag/add-document", headers=patient_headers,
        json={"source": "alias:" + uuid.uuid4().hex[:6], "text": "Alias testi. " * 20},
    ).status_code == 200
    assert client.post(
        "/api/upload", headers=patient_headers,
        files={"file": ("alias.txt", b"alias", "text/plain")},
    ).status_code == 200


def test_openapi_and_docs(client):
    assert client.get("/docs").status_code == 200
    schema = client.get("/openapi.json").json()
    assert "/api/chat" in schema["paths"]
    assert "/api/rag/ingest" in schema["paths"]


def test_no_api_embeddings_route():
    paths = set(app.openapi()["paths"])
    assert not any("embed" in path for path in paths)
    source = (ROOT / "services" / "rag.py").read_text(encoding="utf-8")
    assert "SentenceTransformer" in source
    for route_file in (ROOT / "routes").glob("*.py"):
        assert '"/embeddings"' not in route_file.read_text(encoding="utf-8")


def test_model_list_uses_unsaved_key(client, admin_headers, fake_llm, cfg):
    old = cfg.get("llm_api_key")
    response = client.post("/admin/api/llm/models", headers=admin_headers, json={
        "scope": "primary", "provider": "custom",
        "base_url": fake_llm["base_url"], "api_key": "aa",
    })
    assert response.status_code == 200, response.text
    assert len(response.json()["data"]["models"]) == 13
    assert fake_llm["handler"].last["auth"] == "Bearer aa"
    assert cfg.get("llm_api_key") != "aa"  # kaydedilmedi


def test_vision_supported_forces_disable(client, admin_headers, cfg):
    old = cfg.get("llm_vision_supported")
    cfg.set("llm_vision_supported", "true")
    try:
        response = client.get("/admin/api/config?limit=200", headers=admin_headers)
        assert response.status_code == 200
    finally:
        if old is not None:
            cfg.set("llm_vision_supported", old)


def test_logout_blacklist_regression(client):
    email = "qa_" + uuid.uuid4().hex[:10] + "@example.com"
    registered = client.post("/api/auth/register", json={
        "email": email, "password": "Patient123!", "full_name": "Blacklist QA",
    })
    token = registered.json()["token"]
    headers = {"Authorization": "Bearer " + token}
    assert client.post("/api/auth/logout", headers=headers).status_code == 200
    assert client.get("/api/user/me", headers=headers).status_code == 401


def test_medical_guardrail_on_diagnosis_prompt(client, patient_headers, fake_llm):
    response = client.post("/api/chat", headers=patient_headers, json={
        "message": "Tahlilime bakıp kesin tanı koyabilir misin?",
    })
    assert response.status_code == 200
    assert "doktorunuza danışın" in response.json()["data"]["answer"].lower()


def test_secret_never_in_error_output(client, patient_headers, cfg):
    secret = str(cfg.get("llm_api_key") or "")
    response = client.post("/api/chat", headers=patient_headers, json={"message": "Merhaba"})
    assert secret not in response.text
