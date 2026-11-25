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


def test_upload_alias_and_no_token(client, patient_headers):
    assert _upload(client, patient_headers, "alias.txt").status_code == 200
    assert client.post("/api/upload", files={"file": ("x.txt", b"x", "text/plain")}).status_code == 401
