"""07 — RAG retrieval + /api/chat + çok turlu sohbet."""

import threading
import time
import uuid

from routes.chat import _llm_settings
from services import rag


def _ingest(client, headers, source):
    return client.post("/api/rag/ingest", headers=headers, json={
        "source": source, "text": "Hemoglobin oksijen taşıyan bir proteindir. " * 20,
    })


def test_chat_uses_rag_and_guardrail(client, patient_headers, fake_llm):
    source = "qa:" + uuid.uuid4().hex[:8]
    assert _ingest(client, patient_headers, source).status_code == 200
    response = client.post("/api/chat", headers=patient_headers, json={
        "message": "Hemoglobin nedir?",
    })
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert "doktorunuza danışın" in data["answer"].lower()
    assert data["sources"]
    assert fake_llm["handler"].last["auth"] == "Bearer fake-key"
    assert any("RAG KAYITLARI" in (m.get("content") or "")
               for m in fake_llm["handler"].last["messages"])


def test_multi_turn_history(client, patient_headers, fake_llm):
    source = "qa:" + uuid.uuid4().hex[:8]
    _ingest(client, patient_headers, source)
    first = client.post("/api/chat", headers=patient_headers, json={"message": "Hemoglobin nedir?"})
    conversation_id = first.json()["data"]["conversation_id"]
    second = client.post("/api/chat", headers=patient_headers, json={
        "message": "Devamını anlatır mısın?", "conversation_id": conversation_id,
    })
    assert second.status_code == 200
    assert any(m.get("content") == "Hemoglobin nedir?"
               for m in fake_llm["handler"].last["messages"])
    detail = client.get(f"/api/conversations/{conversation_id}", headers=patient_headers)
    assert len(detail.json()["data"]["messages"]) == 4


def test_chat_messages_alternate_for_strict_templates(client, patient_headers, fake_llm):
    """medgemma gibi Jinja şablonları tek system ve user/assistant sırası ister."""
    _ingest(client, patient_headers, "qa:strict:" + uuid.uuid4().hex[:8])
    first = client.post("/api/chat", headers=patient_headers, json={
        "message": "Hemoglobin nedir?"
    })
    assert first.status_code == 200, first.text
    conversation_id = first.json()["data"]["conversation_id"]
    second = client.post("/api/chat", headers=patient_headers, json={
        "message": "Devamını anlatır mısın?", "conversation_id": conversation_id,
    })
    assert second.status_code == 200, second.text

    roles = [m["role"] for m in fake_llm["handler"].last["messages"]]
    assert roles.count("system") == 1
    assert roles[0] == "system"
    conversation_roles = roles[1:]
    assert conversation_roles[0] == "user"
    assert conversation_roles[-1] == "user"
    for index, role in enumerate(conversation_roles):
        assert role == ("user" if index % 2 == 0 else "assistant")


def test_conversation_archive_restore_delete(client, patient_headers, fake_llm):
    created = client.post("/api/chat", headers=patient_headers, json={"message": "Arşiv testi"})
    assert created.status_code == 200, created.text
    cid = created.json()["data"]["conversation_id"]

    archived = client.patch(f"/api/conversations/{cid}/archive", headers=patient_headers,
                            json={"archived": True})
    assert archived.status_code == 200, archived.text
    active = client.get("/api/conversations", headers=patient_headers).json()["data"]
    assert cid not in [item["id"] for item in active]
    all_items = client.get("/api/conversations?include_archived=true", headers=patient_headers).json()["data"]
    assert any(item["id"] == cid and item["is_archived"] for item in all_items)
    assert client.get(f"/api/conversations/{cid}", headers=patient_headers).status_code == 200
    blocked = client.post("/api/chat", headers=patient_headers,
                          json={"message": "Devam", "conversation_id": cid})
    assert blocked.status_code == 400

    restored = client.patch(f"/api/conversations/{cid}/archive", headers=patient_headers,
                            json={"archived": False})
    assert restored.status_code == 200
    assert client.post("/api/chat", headers=patient_headers,
                       json={"message": "Devam", "conversation_id": cid}).status_code == 200
    deleted = client.delete(f"/api/conversations/{cid}", headers=patient_headers)
    assert deleted.status_code == 200
    assert client.get(f"/api/conversations/{cid}", headers=patient_headers).status_code == 404


def test_conversation_search_matches_message_content(client, patient_headers, fake_llm):
    marker = "arama-" + uuid.uuid4().hex[:8]
    created = client.post("/api/chat", headers=patient_headers, json={"message": marker})
    cid = created.json()["data"]["conversation_id"]
    client.post("/api/chat", headers=patient_headers, json={"message": "Başka bir konu"})
    response = client.get("/api/conversations?q=" + marker, headers=patient_headers)
    assert response.status_code == 200, response.text
    ids = [item["id"] for item in response.json()["data"]]
    assert cid in ids
    assert len(ids) == 1


def test_slow_llm_does_not_block_other_requests(client, patient_headers, monkeypatch):
    """LLM thread'de beklerken /health ve diğer istekler event loop'u kullanabilmeli."""
    started = threading.Event()
    release = threading.Event()
    result = {}

    def slow_llm(messages, settings):
        started.set()
        release.wait(5)
        return "Test yanıtı"

    monkeypatch.setattr("routes.chat._call_llm", slow_llm)

    def run_chat():
        result["response"] = client.post("/api/chat", headers=patient_headers, json={
            "message": "Yavaş istek"
        })

    worker = threading.Thread(target=run_chat)
    worker.start()
    assert started.wait(10), "LLM çağrısı başlamadı"
    before = time.monotonic()
    health = client.get("/health")
    elapsed = time.monotonic() - before
    release.set()
    worker.join(5)

    assert health.status_code == 200
    assert elapsed < 1.0, f"/health {elapsed:.2f}s bloke oldu"
    assert result["response"].status_code == 200, result["response"].text


def test_chat_token_and_timeout_config(client, patient_headers, fake_llm, cfg):
    old_tokens = cfg.get("llm_max_tokens")
    old_timeout = cfg.get("llm_timeout")
    cfg.set("llm_max_tokens", "64")
    cfg.set("llm_timeout", "120")
    try:
        response = client.post("/api/chat", headers=patient_headers, json={
            "message": "Kısa bir yanıt verir misin?"
        })
        assert response.status_code == 200, response.text
        settings = _llm_settings()
        assert settings["max_tokens"] == 64
        assert settings["timeout"] == 120
    finally:
        if old_tokens is not None:
            cfg.set("llm_max_tokens", old_tokens)
        else:
            cfg.set("llm_max_tokens", "256")
        if old_timeout is not None:
            cfg.set("llm_timeout", old_timeout)
        else:
            cfg.set("llm_timeout", "180")


def test_empty_and_unconfigured(client, patient_headers, cfg):
    assert client.post("/api/chat", headers=patient_headers, json={"message": "  "}).status_code == 400
    old_key = cfg.get("llm_api_key")
    old_provider = cfg.get("llm_provider")
    cfg.set("llm_api_key", "")
    cfg.set("llm_provider", "custom")
    try:
        response = client.post("/api/chat", headers=patient_headers, json={"message": "Merhaba"})
        assert response.status_code == 400
    finally:
        if old_key is not None:
            cfg.set("llm_api_key", old_key)
        if old_provider is not None:
            cfg.set("llm_provider", old_provider)


def test_search_excludes_other_users(client, patient_headers, cfg):
    source = "qa:" + uuid.uuid4().hex[:8]
    _ingest(client, patient_headers, source)
    conn = cfg.connect_db()
    try:
        results = rag.search(conn, 99999999, "Hemoglobin", top_k=5)
        assert all(item["source"] != source for item in results)
    finally:
        conn.close()
