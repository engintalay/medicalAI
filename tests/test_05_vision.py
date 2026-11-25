"""05 — Vision extraction: kapalıyken 400, eksik dosya 404, desteklenmeyen tip 400."""

def _upload(client, headers):
    return client.post(
        "/api/uploads",
        headers=headers,
        files={"file": ("qa-vision.txt", b"lab sonucu", "text/plain")},
    )


def test_vision_disabled_returns_400(client, patient_headers, cfg):
    old = (cfg.get("llm_vision_supported"), cfg.get("vision_llm_enabled"))
    cfg.set("llm_vision_supported", "false")
    cfg.set("vision_llm_enabled", "false")
    try:
        created = _upload(client, patient_headers)
        upload_id = created.json()["data"]["id"]
        response = client.post(f"/api/uploads/{upload_id}/extract", headers=patient_headers)
        assert response.status_code == 400
        assert "yapılandırılmadı" in response.text.lower()
    finally:
        cfg.set("llm_vision_supported", old[0] or "false")
        cfg.set("vision_llm_enabled", old[1] or "false")


def test_missing_upload_returns_404(client, patient_headers):
    response = client.post("/api/uploads/99999999/extract", headers=patient_headers)
    assert response.status_code in (400, 404)


def test_text_file_extracted_locally(client, patient_headers, cfg, fake_llm):
    old_vision = cfg.get("vision_llm_enabled")
    cfg.set("vision_llm_enabled", "true")
    try:
        created = _upload(client, patient_headers)
        upload_id = created.json()["data"]["id"]
        response = client.post(f"/api/uploads/{upload_id}/extract", headers=patient_headers)
        assert response.status_code == 200
        assert response.json()["data"]["source"] == "local_text"
    finally:
        cfg.set("vision_llm_enabled", old_vision or "false")
