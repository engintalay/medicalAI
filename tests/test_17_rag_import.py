"""17 parçası: RAG PDF/TXT yükleme ve prospektus.co ilaç içe aktarma."""

import io
import uuid

from reportlab.pdfgen import canvas

from config.loader import get_config_loader
from services import rag, vision


def _cleanup_source(cfg, source, user_id):
    conn = cfg.connect_db()
    try:
        rag.delete_source(conn, source, user_id)
        conn.commit()
    finally:
        conn.close()


def test_ascii85_pdf_text_extracted_locally():
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.drawString(72, 800, "Majezik 100 mg prospectus")
    pdf.drawString(72, 780, "Etken madde: Flurbiprofen")
    pdf.save()
    result = vision.extract_text_from_data(buffer.getvalue(), "application/pdf")
    assert result["source"] == "local_pdf"
    assert result["model_used"] is False
    assert "Majezik" in result["text"]
    assert "Flurbiprofen" in result["text"]


def test_drug_search_endpoint(client, patient_headers, monkeypatch):
    expected = [{
        "title": "Majezik 100 mg 15 film tablet",
        "url": "https://prospektus.co/ilaclar/majezik-100-mg-15-film-tablet",
    }]
    monkeypatch.setattr("routes.rag.web_import.search_drugs", lambda q, limit: expected)
    response = client.get("/api/rag/drug-search?q=majezik", headers=patient_headers)
    assert response.status_code == 200, response.text
    assert response.json()["data"] == expected


def test_patient_txt_upload_to_rag(client, patient_headers, patient):
    source = "qa:upload:" + uuid.uuid4().hex[:8]
    try:
        response = client.post(
            "/api/rag/upload", headers=patient_headers,
            data={"source": source},
            files={"file": ("prospektus.txt", "Majezik etken maddesi flurbiprofen.", "text/plain")},
        )
        assert response.status_code == 200, response.text
        info = response.json()["data"]
        assert info["chunks"] >= 1
        assert info["filename"] == "prospektus.txt"
        assert info["model_used"] is False
    finally:
        _cleanup_source(get_config_loader(), source, patient["user_id"])


def test_patient_pdf_upload_uses_vision(client, patient_headers, patient, monkeypatch):
    source = "qa:pdf:" + uuid.uuid4().hex[:8]
    monkeypatch.setattr(
        "routes.rag.vision.extract_text_from_data",
        lambda data, mime, prompt=None, api_key=None: {
            "text": "Majezik 100 mg prospektüsü metni.", "pages": 2,
            "source": "test_vision", "model_used": True,
        },
    )
    try:
        response = client.post(
            "/api/rag/upload", headers=patient_headers,
            data={"source": source},
            files={"file": ("prospektus.pdf", b"%PDF-1.4 test", "application/pdf")},
        )
        assert response.status_code == 200, response.text
        info = response.json()["data"]
        assert info["pages"] == 2
        assert info["model_used"] is True
    finally:
        _cleanup_source(get_config_loader(), source, patient["user_id"])


def test_url_import_and_public_scope(client, patient_headers, patient, admin_headers, monkeypatch):
    monkeypatch.setattr(
        "routes.rag.web_import.fetch_url_text",
        lambda url: {"title": "Majezik", "text": "Etken madde flurbiprofen. " * 30,
                     "url": url, "characters": 800},
    )
    url = "https://prospektus.co/ilaclar/majezik-100-mg-15-film-tablet"
    patient_source = "qa:url:" + uuid.uuid4().hex[:8]
    public_source = "qa:public-url:" + uuid.uuid4().hex[:8]
    cfg = get_config_loader()
    try:
        response = client.post("/api/rag/import-url", headers=patient_headers,
                               json={"source": patient_source, "url": url})
        assert response.status_code == 200, response.text
        assert response.json()["data"]["title"] == "Majezik"

        public = client.post("/admin/api/rag/import-url", headers=admin_headers,
                             json={"source": public_source, "url": url})
        assert public.status_code == 200, public.text
        conn = cfg.connect_db()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM rag_documents WHERE source_type=%s AND user_id IS NULL",
                            (public_source,))
                assert cur.fetchone()[0] >= 1
        finally:
            conn.close()
    finally:
        _cleanup_source(cfg, patient_source, patient["user_id"])
        _cleanup_source(cfg, public_source, None)


def test_import_rejects_non_prospektus_host(client, patient_headers):
    response = client.post("/api/rag/import-url", headers=patient_headers, json={
        "source": "qa:bad-url", "url": "http://127.0.0.1/private",
    })
    assert response.status_code == 400
    assert "prospektus.co" in response.json()["error"]


def test_upload_requires_auth_and_file_type(client, admin_headers):
    assert client.post("/api/rag/upload", data={"source": "x"},
                       files={"file": ("x.txt", "x", "text/plain")}).status_code == 401
    bad = client.post("/admin/api/rag/upload", headers=admin_headers,
                      data={"source": "x"}, files={"file": ("x.png", b"x", "image/png")})
    assert bad.status_code == 400
