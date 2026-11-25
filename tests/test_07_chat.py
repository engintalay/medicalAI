"""07 — RAG retrieval + /api/chat + çok turlu sohbet."""

import uuid

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
