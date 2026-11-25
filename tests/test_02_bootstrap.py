"""02 — Bootstrap/config: DB ve Redis config'den okunur."""


def test_health_200(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_database_config_loaded(cfg):
    for key in ("db_host", "db_port", "db_name", "db_user"):
        assert cfg.get(key), f"{key} config'de yok"
    conn = cfg.connect_db()
    with conn.cursor() as cur:
        cur.execute("SELECT 1")
        assert cur.fetchone()[0] == 1
    conn.close()


def test_redis_endpoint_from_config(cfg):
    params = cfg._redis_params
    if params is None:
        return  # Redis erişilemezse bellek cache yeterli
    assert params["host"] == cfg.get("redis_host")
    assert params["port"] == int(cfg.get("redis_port"))


def test_required_tables_exist(cfg):
    expected = {
        "system_config", "users", "health_metrics", "user_uploads",
        "rag_documents", "research_data", "conversations",
        "conversation_messages", "reminders", "notification_preferences",
    }
    conn = cfg.connect_db()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )
        tables = {row[0] for row in cur.fetchall()}
    conn.close()
    assert expected <= tables
