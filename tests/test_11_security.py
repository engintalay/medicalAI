"""11 — Operasyon/güvenlik: secret maskeleme, izolasyon, deployment scriptleri."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_secret_endpoint_masked_and_admin_only(client, admin_headers, patient_headers, cfg):
    assert client.get("/admin/api/utils/secret/db_password").status_code == 401
    assert client.get("/admin/api/utils/secret/db_password", headers=patient_headers).status_code in (401, 403)
    response = client.get("/admin/api/utils/secret/db_password", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["is_secret"] is True
    raw = str(cfg.get("db_password") or "")
    assert data["value"] != raw
    assert raw not in response.text


def test_user_scoped_routes_have_user_id_filter():
    for filename in ("routes/uploads.py", "routes/user.py", "routes/notifications.py",
                     "routes/chat.py", "routes/rag.py"):
        source = (ROOT / filename).read_text(encoding="utf-8")
        assert "user_id" in source, f"{filename} user_id filtresi yok"


def test_logs_have_no_tokens_or_keys():
    log = ROOT / "logs" / "app.log"
    if not log.exists():
        return
    text = log.read_text(encoding="utf-8", errors="replace")
    assert "Bearer " not in text
    assert "api_key=" not in text


def test_json_backup_contains_config(tmp_path):
    import json
    from database.backup import dump

    path = tmp_path / "dump.json"
    rows = dump(str(path))
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["format"] == "medicalai-json-v1"
    assert "system_config" in payload["tables"]
    assert rows >= len(payload["tables"]["system_config"]["rows"])


def test_deployment_scripts_valid():
    import subprocess
    for name in ("install.sh", "run.sh", "restart.sh", "stop.sh", "backup.sh", "restore.sh"):
        script = ROOT / name
        assert script.exists() and script.stat().st_mode & 0o111, f"{name} executable değil"
        assert subprocess.run(["bash", "-n", str(script)]).returncode == 0
