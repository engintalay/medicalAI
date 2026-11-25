"""13 — Public research: idempotent URL, admin yetkisi, RAG yenileme/silme."""

import uuid

from config.loader import get_config_loader

cfg = get_config_loader()


def _body():
    return {
        "source": "prospektus",
        "title": "QA Prospektüs " + uuid.uuid4().hex[:6],
        "content": "QA ilaç prospectüsü. Dozaj bilgisi. " * 20,
        "url": "https://example.invalid/" + uuid.uuid4().hex,
    }


def test_admin_only_and_unreachable_url_still_saves(client, admin_headers, patient_headers):
    body = _body()
    assert client.post("/api/research", headers=patient_headers, json=body).status_code in (401, 403)
    assert client.get("/admin/api/research", headers=patient_headers).status_code in (401, 403)
    created = client.post("/api/research", headers=admin_headers, json=body)
    assert created.status_code == 201, created.text
    return created.json()["data"]["id"]


def test_same_url_is_idempotent(client, admin_headers):
    body = _body()
    first = client.post("/api/research", headers=admin_headers, json=body)
    second = client.post("/api/research", headers=admin_headers, json=body)
    assert first.status_code == second.status_code == 201
    assert first.json()["data"]["id"] == second.json()["data"]["id"]


def test_update_refreshes_rag_and_delete_cleans(client, admin_headers):
    body = _body()
    created = client.post("/api/research", headers=admin_headers, json=body)
    data_id = created.json()["data"]["id"]
    source = f"research:{data_id}"
    conn = cfg.connect_db()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM rag_documents WHERE source_type = %s", (source,))
        before = cur.fetchone()[0]
    conn.close()
    assert before >= 1

    updated = client.put(f"/admin/api/research/{data_id}", headers=admin_headers, json={
        "content": "Tamamen yeni içerik. " * 20,
    })
    assert updated.status_code == 200
    conn = cfg.connect_db()
    with conn.cursor() as cur:
        cur.execute("SELECT content FROM rag_documents WHERE source_type = %s LIMIT 1", (source,))
        content = cur.fetchone()[0]
    conn.close()
    assert "Tamamen yeni" in content
    assert body["content"].split(".")[0] not in content

    assert client.delete(f"/admin/api/research/{data_id}", headers=admin_headers).status_code == 200
    conn = cfg.connect_db()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM rag_documents WHERE source_type = %s", (source,))
        left = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM research_data WHERE data_id = %s", (data_id,))
        rows = cur.fetchone()[0]
    conn.close()
    assert left == 0 and rows == 0


def test_admin_list_pagination(client, admin_headers):
    response = client.get("/admin/api/research?limit=5&offset=0", headers=admin_headers)
    assert response.status_code == 200
    assert "total" in response.json() and "data" in response.json()
