"""14 parçası: ekranların servis edilmesi ve admin RAG yönetim API'leri."""

import uuid

PATIENT_PAGES = (
    "/patient",
    "/patient/chat",
    "/patient/metrics",
    "/patient/uploads",
    "/patient/reminders",
    "/patient/profile",
    "/patient/rag",
)

ADMIN_PAGES = ("/admin/research", "/admin/rag")


def test_patient_pages_serve_spa(client):
    for path in PATIENT_PAGES:
        response = client.get(path)
        assert response.status_code == 200, (path, response.text[:200])
        assert "patient.js" in response.text
        assert "Hasta Paneli" in response.text


def test_admin_content_pages_serve_spa(client):
    for path in ADMIN_PAGES:
        response = client.get(path)
        assert response.status_code == 200, (path, response.text[:200])
        assert "admin.js" in response.text
    research = client.get("/admin/research").text
    rag = client.get("/admin/rag").text
    assert "Araştırma / İçerik" in research
    assert "RAG Bilgi Tabanı" in rag


def test_admin_rag_ingest_list_delete(client, admin_headers):
    source = "qa_ui_" + uuid.uuid4().hex[:8]
    try:
        created = client.post(
            "/admin/api/rag/ingest",
            json={"source": source, "text": "Kan basıncı ölçümü hakkında genel bilgi.", "chunk_size": 800, "overlap": 100},
            headers=admin_headers,
        )
        assert created.status_code == 200, created.text
        assert created.json()["data"]["chunks"] >= 1

        listed = client.get("/admin/api/rag/documents", headers=admin_headers)
        assert listed.status_code == 200, listed.text
        match = [row for row in listed.json()["data"] if row["source"] == source]
        assert len(match) == 1
        assert match[0]["public_chunks"] == match[0]["chunks"]
    finally:
        client.delete("/admin/api/rag/documents/" + source, headers=admin_headers)

    after = client.get("/admin/api/rag/documents", headers=admin_headers)
    assert source not in [row["source"] for row in after.json()["data"]]


def test_admin_rag_requires_token(client):
    assert client.get("/admin/api/rag/documents").status_code == 401
    assert client.post(
        "/admin/api/rag/ingest", json={"source": "x", "text": "y"}
    ).status_code == 401
