"""10 — Admin panel sözleşmesi (MEVCUT davranış regresyonu)."""

from pathlib import Path


def test_admin_login_and_config_access(client, admin_headers):
    assert client.get("/admin/api/config", headers=admin_headers).status_code == 200
    assert client.get("/admin/api/config").status_code == 401


def test_secrets_masked_in_config_list(client, admin_headers, cfg):
    response = client.get("/admin/api/config?limit=200", headers=admin_headers)
    assert response.status_code == 200
    raw = response.text
    password = str(cfg.get("db_password") or "")
    if password:
        assert password not in raw
    secrets = [row for row in response.json()["data"] if row.get("is_secret")]
    assert secrets
    assert all(row["value"] != password for row in secrets)


def test_admin_spa_has_health_link_and_cache_busting(client):
    html = client.get("/admin").text
    assert "/admin/health" in html
    assert "/static/admin.js?v=" in html
    assert "/static/admin.css?v=" in html


def test_admin_js_syntax():
    import subprocess
    result = subprocess.run(
        ["node", "--check", str(Path(__file__).resolve().parent.parent / "static" / "admin.js")],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()[:200]
