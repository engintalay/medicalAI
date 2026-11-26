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
