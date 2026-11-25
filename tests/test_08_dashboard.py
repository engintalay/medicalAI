"""08 — Hasta dashboard, metrik yazma ve CSV/PDF export."""

import uuid


def test_dashboard_shape(client, patient_headers):
    response = client.get("/api/user/dashboard", headers=patient_headers)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    for key in ("profile", "weight_trend", "upload_count", "reminders", "metrics", "uploads"):
        assert key in data


def test_metric_add_updates_trend(client, patient_headers):
    value = 70 + (uuid.uuid4().int % 100) / 100
    created = client.post("/api/user/metrics", headers=patient_headers, json={
        "name": "weight", "value": value,
    })
    assert created.status_code == 201, created.text
    dashboard = client.get("/api/user/dashboard", headers=patient_headers).json()["data"]
    assert any(abs(float(point["value"]) - value) < 0.001 for point in dashboard["weight_trend"])


def test_export_formats_and_isolation(client, patient):
    csv_response = client.get("/api/user/export?format=csv", headers=patient["headers"])
    assert csv_response.status_code == 200
    assert "text/csv" in csv_response.headers["content-type"]
    assert str(patient["user_id"]) in csv_response.headers["content-disposition"]

    pdf_response = client.get("/api/user/export?format=pdf", headers=patient["headers"])
    assert pdf_response.status_code == 200
    assert pdf_response.content[:4] == b"%PDF"

    assert client.get("/api/user/export?format=xyz", headers=patient["headers"]).status_code == 400
    assert client.get("/api/user/dashboard").status_code == 401


def test_other_user_metric_invisible(client, patient_headers):
    marker = "isolated-" + uuid.uuid4().hex[:8]
    client.post("/api/user/metrics", headers=patient_headers, json={"name": marker, "value": 1})
    email = "qa_" + uuid.uuid4().hex[:10] + "@example.com"
    other = client.post("/api/auth/register", json={
        "email": email, "password": "Patient123!", "full_name": "Diger Hasta",
    })
    headers = {"Authorization": "Bearer " + other.json()["token"]}
    data = client.get("/api/user/dashboard", headers=headers).json()["data"]
    assert all(item["name"] != marker for item in data["metrics"])
