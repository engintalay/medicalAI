"""04 — Dosya yükleme: tip kontrolü, izolasyon, alias."""

import uuid


def _upload(client, headers, filename="qa.txt", mime="text/plain", data=b"lab sonucu"):
    return client.post(
        "/api/uploads",
        headers=headers,
        files={"file": (filename, data, mime)},
    )


def test_exe_rejected(client, patient_headers):
    response = _upload(client, patient_headers, "malware.exe", "application/octet-stream", b"MZ")
    assert response.status_code == 400
    assert response.json()["success"] is False


def test_txt_upload_list_delete(client, patient_headers):
    created = _upload(client, patient_headers, f"qa-{uuid.uuid4().hex[:6]}.txt")
    assert created.status_code == 200, created.text
    upload_id = created.json()["data"]["id"]
    listed = client.get("/api/uploads", headers=patient_headers)
    assert listed.status_code == 200
    assert any(item["id"] == upload_id for item in listed.json()["data"])
    assert client.delete(f"/api/uploads/{upload_id}", headers=patient_headers).status_code == 200


def test_file_preview_and_ownership(client, patient_headers):
    created = _upload(client, patient_headers, "onizleme.txt", data=b"onizleme metni")
    upload_id = created.json()["data"]["id"]
    try:
        preview = client.get(f"/api/uploads/{upload_id}/file", headers=patient_headers)
        assert preview.status_code == 200
        assert preview.content == b"onizleme metni"
        assert client.get(f"/api/uploads/{upload_id}/file").status_code == 401
        assert client.get("/api/uploads/99999999/file", headers=patient_headers).status_code == 404
    finally:
        client.delete(f"/api/uploads/{upload_id}", headers=patient_headers)


def test_extraction_result_is_persisted(client, patient_headers, cfg):
    old = cfg.get("vision_llm_enabled")
    cfg.set("vision_llm_enabled", "true")
    created = _upload(client, patient_headers, "metin-cikarma.txt", data=b"Kalici metin sonucu")
    upload_id = created.json()["data"]["id"]
    try:
        extracted = client.post(f"/api/uploads/{upload_id}/extract", headers=patient_headers)
        assert extracted.status_code == 200, extracted.text
        listed = client.get("/api/uploads", headers=patient_headers).json()["data"]
        item = next(row for row in listed if row["id"] == upload_id)
        assert item["extracted_text"] == "Kalici metin sonucu"
        assert item["extracted_at"] is not None
        assert item["extraction_source"] == "local_text"
        exported = client.get("/api/user/export?format=csv", headers=patient_headers)
        assert exported.status_code == 200
        assert "Kalici metin sonucu" in exported.content.decode("utf-8-sig")
    finally:
        client.delete(f"/api/uploads/{upload_id}", headers=patient_headers)
        cfg.set("vision_llm_enabled", old or "false")


def test_upload_alias_and_no_token(client, patient_headers):
    assert _upload(client, patient_headers, "alias.txt").status_code == 200
    assert client.post("/api/upload", files={"file": ("x.txt", b"x", "text/plain")}).status_code == 401
