"""06 — RAG ingestion: yerel embedding, cache, idempotent source."""

import uuid

from services import rag

TEXT = ("Hemoglobin kırmızı kan hücrelerinde oksijen taşır. " * 30)


def test_local_embedding_cached():
    first = rag.embed_texts(["Hemoglobin nedir?"])
    loads = rag.load_count()
    second = rag.embed_texts(["Tahlil sonucu"])
    assert len(first[0]) == 384
    assert abs(sum(x * x for x in second[0]) - 1.0) < 0.01
    assert rag.load_count() == loads == 1


def test_ingest_creates_chunks(client, patient_headers):
    source = "qa:" + uuid.uuid4().hex[:8]
    response = client.post("/api/rag/ingest", headers=patient_headers, json={
        "source": source, "text": TEXT,
    })
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["chunks"] >= 3
    assert data["dimensions"] == 384
    return source, data["chunks"]


def test_alias_and_idempotent(client, patient_headers, cfg):
    source = "qa:" + uuid.uuid4().hex[:8]
    first = client.post("/api/rag/add-document", headers=patient_headers, json={
        "source": source, "text": TEXT,
    })
    assert first.status_code == 200
    chunks = first.json()["data"]["chunks"]
    second = client.post("/api/rag/ingest", headers=patient_headers, json={
        "source": source, "text": TEXT,
    })
    assert second.status_code == 200
    conn = cfg.connect_db()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM rag_documents WHERE source_type = %s", (source,))
        count = cur.fetchone()[0]
        cur.execute("SELECT content_vector FROM rag_documents WHERE source_type = %s LIMIT 1", (source,))
        vector = cur.fetchone()[0]
    conn.close()
    assert count == chunks
    assert isinstance(vector, dict) and len(vector["values"]) == 384


def test_empty_text_rejected(client, patient_headers):
    response = client.post("/api/rag/ingest", headers=patient_headers, json={
        "source": "qa:empty", "text": "   ",
    })
    assert response.status_code == 400
