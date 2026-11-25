"""09 — Hatırlatmalar, alias ve bildirim tercihleri."""

import uuid
from datetime import datetime, timedelta, timezone


def _future(days=2):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def test_create_list_soft_delete(client, patient_headers):
    title = "Sabah ilacı " + uuid.uuid4().hex[:6]
    created = client.post("/api/reminders", headers=patient_headers, json={
        "type": "medication", "title": title, "due_date": _future(),
    })
    assert created.status_code == 201, created.text
    reminder_id = created.json()["data"]["id"]
    listed = client.get("/api/reminders", headers=patient_headers).json()["data"]
    assert any(item["id"] == reminder_id for item in listed)
    assert client.delete(f"/api/reminders/{reminder_id}", headers=patient_headers).status_code == 200
    listed = client.get("/api/reminders", headers=patient_headers).json()["data"]
    assert all(item["id"] != reminder_id for item in listed)


def test_past_date_rejected(client, patient_headers):
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    response = client.post("/api/reminders", headers=patient_headers, json={
        "type": "lab", "title": "Gecmis", "due_date": past,
    })
    assert response.status_code == 400


def test_preferences_roundtrip(client, patient_headers):
    saved = client.put("/api/user/notification-preferences", headers=patient_headers, json={
        "email_enabled": True, "push_enabled": False, "quiet_hours": "22:00-08:00",
    })
    assert saved.status_code == 200
    loaded = client.get("/api/user/notification-preferences", headers=patient_headers)
    assert loaded.status_code == 200
    assert loaded.json()["data"]["quiet_hours"] == "22:00-08:00"


def test_notifications_alias_and_dashboard_feed(client, patient_headers):
    title = "Kontrol " + uuid.uuid4().hex[:6]
    created = client.post("/api/notifications", headers=patient_headers, json={
        "type": "checkup", "title": title, "due_date": _future(),
    })
    assert created.status_code == 201
    assert any(item["title"] == title
               for item in client.get("/api/notifications", headers=patient_headers).json()["data"])
    assert any(item["title"] == title
               for item in client.get("/api/user/dashboard", headers=patient_headers)
               .json()["data"]["reminders"])
