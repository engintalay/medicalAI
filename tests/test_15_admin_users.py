"""15 parçası: admin kullanıcı oluşturma ve aktiflik yönetimi."""

import uuid

import psycopg2

from config.loader import get_config_loader


def _email(prefix):
    return prefix + "_" + uuid.uuid4().hex[:8] + "@example.com"


def _cleanup(user_ids):
    cfg = get_config_loader()
    conn = psycopg2.connect(
        host=cfg.get("db_host"),
        port=int(cfg.get("db_port", "5432")),
        dbname=cfg.get("db_name"),
        user=cfg.get("db_user"),
        password=cfg.get("db_password", ""),
    )
    try:
        with conn.cursor() as cur:
            for user_id in user_ids:
                cur.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
        conn.commit()
    finally:
        conn.close()


def test_admin_creates_patient_and_patient_can_login(client, admin_headers):
    email = _email("qa_admin_patient")
    created = client.post("/admin/api/users", json={
        "email": email,
        "password": "AdminCreated123!",
        "full_name": "Admin Yarattigi Hasta",
        "role": "patient",
        "city": "Ankara",
        "height_cm": 170,
        "weight_kg": 65,
        "birth_year": 1991,
    }, headers=admin_headers)
    assert created.status_code == 201, created.text
    body = created.json()
    user = body["data"]
    assert user["role"] == "patient"
    assert user["is_active"] is True
    assert "password" not in user and "password_hash" not in user
    assert "password_hash" not in body

    login = client.post("/api/auth/login", json={
        "email": email, "password": "AdminCreated123!"
    })
    assert login.status_code == 200, login.text
    assert login.json()["user"]["user_id"] == user["user_id"]

    _cleanup([user["user_id"]])


def test_admin_creates_admin_and_login(client, admin_headers):
    email = _email("qa_admin_admin")
    created = client.post("/admin/api/users", json={
        "email": email,
        "password": "AdminCreated123!",
        "full_name": "Ikinci Admin",
        "role": "admin",
    }, headers=admin_headers)
    assert created.status_code == 201, created.text
    user = created.json()["data"]
    assert user["role"] == "admin"

    login = client.post("/admin/api/auth/login", json={
        "email": email, "password": "AdminCreated123!"
    })
    assert login.status_code == 200, login.text

    _cleanup([user["user_id"]])


def test_admin_user_validation(client, admin_headers):
    email = _email("qa_admin_valid")
    created = client.post("/admin/api/users", json={
        "email": email, "password": "AdminCreated123!",
        "full_name": "Validasyon", "role": "patient",
    }, headers=admin_headers)
    assert created.status_code == 201, created.text
    user_id = created.json()["data"]["user_id"]

    duplicate = client.post("/admin/api/users", json={
        "email": email, "password": "OtherPassword123!",
        "full_name": "Tekrar", "role": "patient",
    }, headers=admin_headers)
    assert duplicate.status_code == 400

    bad_role = client.post("/admin/api/users", json={
        "email": _email("qa_admin_role"), "password": "AdminCreated123!",
        "full_name": "Rol", "role": "superuser",
    }, headers=admin_headers)
    assert bad_role.status_code == 400

    short_password = client.post("/admin/api/users", json={
        "email": _email("qa_admin_short"), "password": "123",
        "full_name": "Kisa", "role": "patient",
    }, headers=admin_headers)
    assert short_password.status_code == 400

    _cleanup([user_id])


def test_admin_toggle_user_active(client, admin_headers):
    email = _email("qa_admin_toggle")
    created = client.post("/admin/api/users", json={
        "email": email, "password": "AdminCreated123!",
        "full_name": "Ac Kapat", "role": "patient",
    }, headers=admin_headers)
    user_id = created.json()["data"]["user_id"]

    try:
        payload = {"email": email, "password": "AdminCreated123!"}
        assert client.post("/api/auth/login", json=payload).status_code == 200

        deactivated = client.patch(
            "/admin/api/users/" + str(user_id),
            json={"is_active": False}, headers=admin_headers,
        )
        assert deactivated.status_code == 200, deactivated.text
        assert deactivated.json()["data"]["is_active"] is False
        assert client.post("/api/auth/login", json=payload).status_code == 401

        activated = client.patch(
            "/admin/api/users/" + str(user_id),
            json={"is_active": True}, headers=admin_headers,
        )
        assert activated.status_code == 200, activated.text
        assert client.post("/api/auth/login", json=payload).status_code == 200

        bad_body = client.patch(
            "/admin/api/users/" + str(user_id),
            json={"is_active": "yes"}, headers=admin_headers,
        )
        assert bad_body.status_code == 400
    finally:
        _cleanup([user_id])


def test_admin_cannot_deactivate_self(client, admin_headers, cfg):
    login = client.post("/admin/api/auth/login", json={
        "email": "admin@medicalai.com",
        "password": cfg.get("admin_default_password", "changeme123"),
    })
    assert login.status_code == 200
    own_id = login.json()["user"]["user_id"]
    response = client.patch(
        "/admin/api/users/" + str(own_id),
        json={"is_active": False}, headers=admin_headers,
    )
    assert response.status_code == 400, response.text


def test_admin_user_create_requires_token(client):
    payload = {
        "email": _email("qa_admin_unauth"), "password": "AdminCreated123!",
        "full_name": "Yetkisiz", "role": "patient",
    }
    assert client.post("/admin/api/users", json=payload).status_code == 401
    assert client.patch(
        "/admin/api/users/1", json={"is_active": False}
    ).status_code == 401
