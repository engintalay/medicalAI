"""database/backup.py — pg_dump bulunmayan ortamlar için JSON mantıksal yedek/geri yükleme.

Kural: gizli değerler (system_config) yedekte tutulur, ancak asla loglara
veya ekrana yazılmaz. Yedek dosyası 0600 olarak oluşturulur.

Kullanım:
    python database/backup.py dump backups/.yedek.json
    python database/backup.py restore backups/.yedek.json
"""

import base64
import json
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from config.loader import get_config_loader

FORMAT = "medicalai-json-v1"


def _default(value: Any):
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"__bytes__": base64.b64encode(bytes(value)).decode("ascii")}
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, default=_default)
    return str(value)


def dump(path: str) -> int:
    """Tüm public tabloları (şema+veri) JSON olarak yazar; satır sayısını döner."""
    cfg = get_config_loader()
    conn = cfg.connect_db()
    count = 0
    payload = {"format": FORMAT, "created_at": datetime.now().isoformat(), "tables": {}}
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY table_name"
            )
            tables = [row[0] for row in cur.fetchall()]
        for table in tables:
            with conn.cursor() as cur:
                cur.execute(f'SELECT * FROM "{table}"')
                columns = [desc[0] for desc in cur.description]
                rows = cur.fetchall()
            payload["tables"][table] = {
                "columns": columns,
                "rows": [[_default(value) for value in row] for row in rows],
            }
            count += len(rows)
    finally:
        conn.close()

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, default=_default)
    return count


def _table_order(conn) -> list:
    """FK bağımlılığına göre güvenli ekleme sırası (referans edilen önce)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT tc.table_name, ccu.table_name "
            "FROM information_schema.table_constraints tc "
            "JOIN information_schema.constraint_column_usage ccu "
            "ON ccu.constraint_name = tc.constraint_name "
            "WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'public'"
        )
        edges = [(child, parent) for child, parent in cur.fetchall() if child != parent]

    tables = set()
    for child, parent in edges:
        tables.add(child)
        tables.add(parent)

    ordered = []
    remaining = set(tables)
    while remaining:
        ready = sorted(
            table for table in remaining
            if not any(child == table and parent in remaining for child, parent in edges)
        )
        if not ready:
            ordered.extend(sorted(remaining))  # döngüsel FK: rastgele ama tutarlı
            break
        ordered.extend(ready)
        remaining.difference_update(ready)
    return ordered


def restore(path: str) -> int:
    """JSON yedeği geri yükler; eklenen satır sayısını döner (yıkıcı işlem)."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("format") != FORMAT or not isinstance(payload.get("tables"), dict):
        raise ValueError("Geçersiz Medical AI yedek biçimi.")

    cfg = get_config_loader()
    conn = cfg.connect_db()
    total = 0
    try:
        from psycopg2.extras import execute_values

        tables = payload["tables"]
        with conn.cursor() as cur:
            # Tüm veriyi tek seferde temizle (FK'lar CASCADE ile korunur).
            names = ", ".join(f'"{name}"' for name in tables)
            cur.execute(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE")
        conn.commit()

        # FK sırasına göre ekle; yedekte olmayan tablolar en sona.
        order = [name for name in _table_order(conn) if name in tables]
        order += [name for name in tables if name not in order]

        for table in order:
            entry = tables[table]
            columns = entry["columns"]
            rows = entry["rows"]
            if not rows:
                continue
            column_sql = ", ".join(f'"{column}"' for column in columns)
            with conn.cursor() as cur:
                execute_values(
                    cur,
                    f'INSERT INTO "{table}" ({column_sql}) VALUES %s',
                    [tuple(row) for row in rows],
                    page_size=500,
                )
                cur.execute(
                    "SELECT a.attname FROM pg_index i "
                    "JOIN pg_attribute a ON a.attrelid = i.indrelid "
                    "AND a.attnum = ANY(i.indkey) "
                    "WHERE i.indrelid = %s::regclass AND i.indisprimary LIMIT 1",
                    (table,),
                )
                pk_row = cur.fetchone()
                if pk_row:
                    primary_key = pk_row[0]
                    cur.execute(
                        "SELECT pg_get_serial_sequence(%s, %s)", (table, primary_key)
                    )
                    sequence_row = cur.fetchone()
                    if sequence_row and sequence_row[0]:
                        cur.execute(
                            "SELECT setval(%s, COALESCE("
                            "(SELECT MAX(\"" + primary_key + "\") FROM \"" + table + "\"), 1))",
                            (sequence_row[0],),
                        )
            total += len(rows)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return total


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("dump", "restore"):
        print("Kullanım: python database/backup.py dump|restore <dosya>")
        sys.exit(1)
    action, filename = sys.argv[1], sys.argv[2]
    if action == "dump":
        print(f"Yedeklendi: {dump(filename)} satır")
    else:
        print(f"Geri yüklendi: {restore(filename)} satır")
