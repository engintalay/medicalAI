"""20 parçası: admin RAG kaynak içeriğini görüntüleme, düzenleme ve reindex."""

import uuid

from services import rag


def _cleanup(cfg, source):
    conn = cfg.connect_db()
    try:
        rag.delete_source(conn, source, None)
        conn.commit()
    finally:
        conn.close()


def test_rag_content_view_edit_and_reindex(client, admin_headers, cfg):
    source = "qa:content:" + uuid.uuid4().hex[:8]
    try:
        created = client.post("/admin/api/rag/ingest", headers=admin_headers, json={
            "source": source, "text": "Eski içerik. " * 40, "chunk_size": 800, "overlap": 100,
        })
        assert created.status_code == 200, created.text

        detail = client.get("/admin/api/rag/document-content", headers=admin_headers,
                            params={"source": source})
        assert detail.status_code == 200, detail.text
        assert "Eski içerik" in detail.json()["data"]["text"]
        assert detail.json()["data"]["chunks"]

        edited = client.put("/admin/api/rag/document-content", headers=admin_headers, json={
            "source": source, "content": "Yeni düzenlenmiş içerik. " * 40,
        })
        assert edited.status_code == 200, edited.text
        after = client.get("/admin/api/rag/document-content", headers=admin_headers,
                           params={"source": source}).json()["data"]
        assert "Yeni düzenlenmiş içerik" in after["text"]
        assert "Eski içerik" not in after["text"]

        reindexed = client.post("/admin/api/rag/reindex", headers=admin_headers,
                                params={"source": source})
        assert reindexed.status_code == 200, reindexed.text
        assert reindexed.json()["data"]["chunks"] >= 1
    finally:
        _cleanup(cfg, source)


def test_rag_content_missing_and_auth(client, admin_headers):
    missing = client.get("/admin/api/rag/document-content", headers=admin_headers,
                         params={"source": "qa:missing"})
    assert missing.status_code == 404
    assert client.get("/admin/api/rag/document-content", params={"source": "x"}).status_code == 401
