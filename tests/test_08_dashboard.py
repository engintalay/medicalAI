"""08 — Hasta dashboard, metrik yazma ve CSV/PDF export."""

import uuid
from datetime import datetime, timedelta, timezone


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


def test_metric_measurement_date_and_future_rejection(client, patient_headers):
    measured_at = datetime(2024, 2, 3, 10, 11, 12, tzinfo=timezone.utc)
    marker = "dated-" + uuid.uuid4().hex[:8]
    created = client.post("/api/user/metrics", headers=patient_headers, json={
        "name": marker, "value": 42, "unit": "test",
        "recorded_at": measured_at.isoformat(),
    })
    assert created.status_code == 201, created.text
    dashboard = client.get("/api/user/dashboard", headers=patient_headers).json()["data"]
    item = next(row for row in dashboard["metrics"] if row["name"] == marker)
    assert datetime.fromisoformat(item["date"].replace("Z", "+00:00")) == measured_at
    assert item["created_at"] is not None

    future = client.post("/api/user/metrics", headers=patient_headers, json={
        "name": "future", "value": 1,
        "recorded_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    })
    assert future.status_code == 400


def test_metric_update_and_validation(client, patient_headers):
    marker = "update-" + uuid.uuid4().hex[:8]
    created = client.post("/api/user/metrics", headers=patient_headers, json={
        "name": marker, "value": 10, "unit": "eski", "recorded_at": "2024-01-01T00:00:00Z",
    })
    metric_id = created.json()["data"]["id"]
    updated = client.put(f"/api/user/metrics/{metric_id}", headers=patient_headers, json={
        "name": marker, "value": 12.5, "unit": "yeni", "recorded_at": "2024-02-03T04:05:06Z",
    })
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["value"] == 12.5
    dashboard = client.get("/api/user/dashboard", headers=patient_headers).json()["data"]
    item = next(row for row in dashboard["metrics"] if row["id"] == metric_id)
    assert item["value"] == 12.5
    assert item["unit"] == "yeni"
    assert item["date"].startswith("2024-02-03")

    future = client.put(f"/api/user/metrics/{metric_id}", headers=patient_headers, json={
        "name": marker, "value": 13, "recorded_at": "2099-01-01T00:00:00Z",
    })
    assert future.status_code == 400
    assert client.put("/api/user/metrics/99999999", headers=patient_headers,
                      json={"name": "yok", "value": 1}).status_code == 404


def test_metric_delete_and_ownership(client, patient_headers, cfg):
    marker = "delete-" + uuid.uuid4().hex[:8]
    created = client.post("/api/user/metrics", headers=patient_headers, json={
        "name": marker, "value": 12.5, "unit": "test",
    })
    assert created.status_code == 201, created.text
    dashboard = client.get("/api/user/dashboard", headers=patient_headers).json()["data"]
    metric_id = next(item["id"] for item in dashboard["metrics"] if item["name"] == marker)

    deleted = client.delete(f"/api/user/metrics/{metric_id}", headers=patient_headers)
    assert deleted.status_code == 200, deleted.text
    dashboard = client.get("/api/user/dashboard", headers=patient_headers).json()["data"]
    assert all(item["id"] != metric_id for item in dashboard["metrics"])

    # Başka hasta aynı metriği silemez.
    client.post("/api/user/metrics", headers=patient_headers, json={
        "name": marker, "value": 13, "unit": "test",
    })
    dashboard = client.get("/api/user/dashboard", headers=patient_headers).json()["data"]
    protected_id = next(item["id"] for item in dashboard["metrics"] if item["name"] == marker)
    email = "qa_" + uuid.uuid4().hex[:10] + "@example.com"
    other = client.post("/api/auth/register", json={
        "email": email, "password": "Patient123!", "full_name": "Diger Hasta",
    })
    other_id = other.json()["user"]["user_id"]
    try:
        other_headers = {"Authorization": "Bearer " + other.json()["token"]}
        blocked = client.delete(f"/api/user/metrics/{protected_id}", headers=other_headers)
        assert blocked.status_code == 404, blocked.text
        dashboard = client.get("/api/user/dashboard", headers=patient_headers).json()["data"]
        assert any(item["id"] == protected_id for item in dashboard["metrics"])
    finally:
        conn = cfg.connect_db()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM users WHERE user_id = %s", (other_id,))
            conn.commit()
        finally:
            conn.close()


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
