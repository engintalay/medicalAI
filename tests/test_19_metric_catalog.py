"""19 parçası: admin yönetimli metrik kataloğu ve hasta combobox verisi."""

import uuid

import psycopg2

from config.loader import get_config_loader


def _cleanup(keys):
    cfg = get_config_loader()
    conn = psycopg2.connect(
        host=cfg.get("db_host"), port=int(cfg.get("db_port", "5432")),
        dbname=cfg.get("db_name"), user=cfg.get("db_user"), password=cfg.get("db_password", ""),
    )
    try:
        with conn.cursor() as cur:
            for key in keys:
                cur.execute("DELETE FROM health_metrics WHERE metric_name=%s", (key,))
                cur.execute("DELETE FROM health_metric_definitions WHERE metric_key=%s", (key,))
        conn.commit()
    finally:
        conn.close()


def test_metric_catalog_crud_and_patient_visibility(client, admin_headers, patient_headers):
    key = "qa_def_" + uuid.uuid4().hex[:8]
    try:
        created = client.post("/admin/api/health/metric-definitions", headers=admin_headers, json={
            "metric_key": key, "label": "QA Metrik", "unit": "birim",
            "category": "other", "min_value": 1, "max_value": 100,
        })
        assert created.status_code == 201, created.text
        definition_id = created.json()["data"]["id"]

        visible = client.get("/api/user/metric-definitions", headers=patient_headers)
        assert any(item["metric_key"] == key for item in visible.json()["data"])

        duplicate = client.post("/admin/api/health/metric-definitions", headers=admin_headers, json={
            "metric_key": key, "label": "Tekrar", "category": "other",
        })
        assert duplicate.status_code == 400

        inactive = client.patch(f"/admin/api/health/metric-definitions/{definition_id}",
                                headers=admin_headers, json={"is_active": False})
        assert inactive.status_code == 200
        hidden = client.get("/api/user/metric-definitions", headers=patient_headers)
        assert all(item["metric_key"] != key for item in hidden.json()["data"])

        active = client.patch(f"/admin/api/health/metric-definitions/{definition_id}",
                              headers=admin_headers, json={"is_active": True})
        assert active.status_code == 200
        saved = client.post("/api/user/metrics", headers=patient_headers, json={
            "name": key, "value": 50, "recorded_at": "2026-01-01T00:00:00Z",
        })
        assert saved.status_code == 201, saved.text
        blocked_delete = client.delete(f"/admin/api/health/metric-definitions/{definition_id}",
                                       headers=admin_headers)
        assert blocked_delete.status_code == 400
    finally:
        _cleanup([key])


def test_unused_metric_definition_can_be_deleted(client, admin_headers):
    key = "qa_unused_" + uuid.uuid4().hex[:8]
    try:
        created = client.post("/admin/api/health/metric-definitions", headers=admin_headers, json={
            "metric_key": key, "label": "Kullanılmayan", "category": "other",
        })
        definition_id = created.json()["data"]["id"]
        deleted = client.delete(f"/admin/api/health/metric-definitions/{definition_id}",
                                headers=admin_headers)
        assert deleted.status_code == 200, deleted.text
    finally:
        _cleanup([key])


def test_metric_definition_validation(client, admin_headers):
    bad_key = client.post("/admin/api/health/metric-definitions", headers=admin_headers, json={
        "metric_key": "Geçersiz Key", "label": "Hatalı", "category": "other",
    })
    assert bad_key.status_code == 400
    bad_range = client.post("/admin/api/health/metric-definitions", headers=admin_headers, json={
        "metric_key": "qa_range", "label": "Aralık", "category": "other",
        "min_value": 100, "max_value": 1,
    })
    assert bad_range.status_code == 400
    _cleanup(["qa_range"])


def test_patient_metric_uses_definition_unit_and_range(client, patient_headers):
    too_low = client.post("/api/user/metrics", headers=patient_headers, json={
        "name": "weight", "value": 10, "recorded_at": "2026-01-01T00:00:00Z",
    })
    assert too_low.status_code == 400
    created = client.post("/api/user/metrics", headers=patient_headers, json={
        "name": "weight", "value": 70, "recorded_at": "2026-01-01T00:00:00Z",
    })
    assert created.status_code == 201, created.text
    metric_id = created.json()["data"]["id"]
    dashboard = client.get("/api/user/dashboard", headers=patient_headers).json()["data"]
    item = next(row for row in dashboard["metrics"] if row["id"] == metric_id)
    assert item["unit"] == "kg"
    client.delete(f"/api/user/metrics/{metric_id}", headers=patient_headers)


def test_admin_can_edit_user_metric(client, admin_headers, patient):
    user_id = patient["user_id"]
    created = client.post("/admin/api/health/metrics", headers=admin_headers,
                          params={"user_id": user_id}, json={
                              "metric_name": "weight", "value": 70, "unit": "kg",
                              "recorded_at": "2026-01-01T00:00:00Z",
                          })
    assert created.status_code == 201, created.text
    metric_id = created.json()["data"]["metric_id"]
    try:
        updated = client.put(f"/admin/api/health/metrics/{metric_id}", headers=admin_headers,
                             params={"user_id": user_id}, json={
                                 "metric_name": "weight", "value": 69.5, "unit": "kg",
                                 "recorded_at": "2026-01-02T00:00:00Z",
                             })
        assert updated.status_code == 200, updated.text
        assert updated.json()["data"]["value"] == 69.5
    finally:
        client.delete(f"/admin/api/health/metrics/{metric_id}", headers=admin_headers,
                      params={"user_id": user_id})


def test_metric_definitions_require_admin(client):
    assert client.get("/admin/api/health/metric-definitions").status_code == 401
    assert client.get("/api/user/metric-definitions").status_code == 401
