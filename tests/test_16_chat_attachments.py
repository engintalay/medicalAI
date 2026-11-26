"""16 parçası: sohbet ekranında dosya okuma ve otomatik ölçüm kaydı."""

from datetime import datetime, timezone

from services.measurements import extract_measurement_date, extract_measurements


def test_measurement_date_without_year_uses_fallback_year():
    parsed = extract_measurement_date("Tarih: 22/11", fallback=datetime(2026, 11, 26, tzinfo=timezone.utc))
    assert parsed == datetime(2026, 11, 22, tzinfo=timezone.utc)
    assert extract_measurement_date("Tansiyon 117/75") is None


def test_chat_attachment_date_is_used_for_metrics(client, patient_headers, fake_llm, monkeypatch):
    upload = client.post(
        "/api/uploads", headers=patient_headers,
        files={"file": ("tarihli.txt", "tarihli olcum", "text/plain")},
    )
    upload_id = upload.json()["data"]["id"]

    async def fake_extract(upload_id, user_id, api_key=None, prompt=None):
        return {"text": "Tarih: 22/11/2026\nSistolik 117 mmHg\nDiyastolik 75 mmHg\nNabız 81 bpm",
                "pages": 1, "source": "test", "model_used": True}

    monkeypatch.setattr("routes.chat.vision.extract_text", fake_extract)
    response = client.post("/api/chat", headers=patient_headers, json={
        "message": "Oku", "upload_id": upload_id,
    })
    assert response.status_code == 200, response.text
    dashboard = client.get("/api/user/dashboard", headers=patient_headers).json()["data"]
    dated = [item for item in dashboard["metrics"] if item["name"] == "sistolik" and item["value"] == 117]
    assert dated
    assert datetime.fromisoformat(dated[0]["date"].replace("Z", "+00:00")).date().isoformat() == "2026-11-22"


def test_blood_pressure_and_pulse_parsed():
    items = extract_measurements(
        "Tansiyon Ölçümü\nBüyük: 128 / 82 mmHg\nNabız: 74 bpm"
    )
    values = {item["name"]: (item["value"], item["unit"]) for item in items}
    assert values["sistolik"] == (128.0, "mmHg")
    assert values["diyastolik"] == (82.0, "mmHg")
    assert values["nabız"] == (74.0, "bpm")


def test_separate_labels_and_other_metrics():
    items = extract_measurements(
        "Sistolik 118, diyastolik 76. Kilo 68,4 kg. Kan şekeri 112 mg/dL. "
        "Vücut sıcaklığı 36,7 °C. SpO2 98%."
    )
    values = {item["name"]: (item["value"], item["unit"]) for item in items}
    assert values["sistolik"] == (118.0, "mmHg")
    assert values["diyastolik"] == (76.0, "mmHg")
    assert values["weight"] == (68.4, "kg")
    assert values["glucose"] == (112.0, "mg/dL")
    assert values["temperature"] == (36.7, "°C")
    assert values["spo2"] == (98.0, "%")


def test_invalid_measurements_are_ignored():
    assert extract_measurements("Tansiyon 999/999, nabız 999 bpm, kilo 9999 kg") == []


def test_chat_attachment_is_read_and_metrics_saved(
    client, patient_headers, fake_llm, monkeypatch
):
    upload = client.post(
        "/api/uploads", headers=patient_headers,
        files={"file": ("bp.txt", "128/82 mmHg nabiz 74", "text/plain")},
    )
    assert upload.status_code == 200, upload.text
    upload_id = upload.json()["data"]["id"]

    async def fake_extract(upload_id, user_id, api_key=None, prompt=None):
        return {
            "text": "Tansiyon 128/82 mmHg\nNabız 74 bpm",
            "pages": 1, "source": "test_vision", "model_used": True,
        }

    monkeypatch.setattr("routes.chat.vision.extract_text", fake_extract)
    response = client.post("/api/chat", headers=patient_headers, json={
        "message": "Bu ölçümü yorumlar mısın?", "upload_id": upload_id,
    })
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["attachment"]["filename"] == "bp.txt"
    assert data["attachment"]["model_used"] is True
    names = {item["name"] for item in data["recorded_metrics"]}
    assert {"sistolik", "diyastolik", "nabız"}.issubset(names)

    dashboard = client.get("/api/user/dashboard", headers=patient_headers)
    saved = dashboard.json()["data"]["metrics"]
    assert any(item["name"] == "sistolik" and item["value"] == 128 for item in saved)
    assert any(item["name"] == "diyastolik" and item["value"] == 82 for item in saved)
    assert any(item["name"] == "nabız" and item["value"] == 74 for item in saved)


def test_chat_attachment_can_skip_metric_save(
    client, patient_headers, fake_llm, monkeypatch
):
    upload = client.post(
        "/api/uploads", headers=patient_headers,
        files={"file": ("weight.txt", "68 kg", "text/plain")},
    )
    upload_id = upload.json()["data"]["id"]

    async def fake_extract(upload_id, user_id, api_key=None, prompt=None):
        return {"text": "Kilo 68 kg", "pages": 1, "source": "test", "model_used": False}

    monkeypatch.setattr("routes.chat.vision.extract_text", fake_extract)
    response = client.post("/api/chat", headers=patient_headers, json={
        "message": "", "upload_id": upload_id, "save_metrics": False,
    })
    assert response.status_code == 200, response.text
    assert response.json()["data"]["recorded_metrics"] == []


def test_attachment_vision_errors_are_returned(client, patient_headers, fake_llm, monkeypatch):
    upload = client.post(
        "/api/uploads", headers=patient_headers,
        files={"file": ("scan.txt", "ornek", "text/plain")},
    )
    upload_id = upload.json()["data"]["id"]

    async def fake_error(upload_id, user_id, api_key=None, prompt=None):
        from services.vision import VisionError
        raise VisionError("Görsel okunamadı", 422)

    monkeypatch.setattr("routes.chat.vision.extract_text", fake_error)
    response = client.post("/api/chat", headers=patient_headers, json={
        "message": "Oku", "upload_id": upload_id,
    })
    assert response.status_code == 422
    assert response.json()["error"] == "Görsel okunamadı"
