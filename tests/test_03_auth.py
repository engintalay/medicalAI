"""03 — Kimlik doğrulama ve rol ayrımı."""

import uuid


def test_register_and_login(client):
    email = "qa_" + uuid.uuid4().hex[:10] + "@example.com"
    registered = client.post("/api/auth/register", json={
        "email": email, "password": "Patient123!", "full_name": "QA",
    })
    assert registered.status_code == 201
    logged = client.post("/api/auth/login", json={"email": email, "password": "Patient123!"})
    assert logged.status_code == 200
    assert logged.json()["token"]


def test_patient_cannot_use_admin_api(client, patient_headers):
    assert client.get("/admin/api/config", headers=patient_headers).status_code in (401, 403)


def test_admin_cannot_use_patient_api(client, admin_headers):
    assert client.get("/api/user/me", headers=admin_headers).status_code in (401, 403)


def test_logout_revokes_token(client):
    email = "qa_" + uuid.uuid4().hex[:10] + "@example.com"
    registered = client.post("/api/auth/register", json={
        "email": email, "password": "Patient123!", "full_name": "Logout QA",
    })
    headers = {"Authorization": "Bearer " + registered.json()["token"]}
    assert client.post("/api/auth/logout", headers=headers).status_code == 200
    assert client.get("/api/user/me", headers=headers).status_code == 401


def test_profile_alias_active(client, patient_headers):
    assert client.get("/api/user/profile", headers=patient_headers).status_code == 200
