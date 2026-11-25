#!/bin/bash
# restore.sh - backup.sh çıktısından geri yükleme + idempotent init_db + /health doğrulaması
# Kullanım: ./restore.sh backups/medicalai-20261125-120000.tar.gz

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ARCHIVE="${1:-}"
if [ -z "$ARCHIVE" ] || [ ! -f "$ARCHIVE" ]; then
    echo "Kullanım: ./restore.sh backups/medicalai-<timestamp>.tar.gz"
    exit 1
fi
case "$ARCHIVE" in
    *.tar.gz) ;;
    *) echo "❌ Yalnızca .tar.gz yedekleri desteklenir."; exit 1 ;;
esac

if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-medical_ai}"
DB_USER="${DB_USER:-medical_user}"
DB_PASSWORD="${DB_PASSWORD:-}"

command -v pg_restore >/dev/null 2>&1 || { echo "❌ pg_restore bulunamadı."; exit 1; }

TMP_DIR=$(mktemp -d "$SCRIPT_DIR/backups/.restore.XXXXXX")
trap 'rm -rf "$TMP_DIR"' EXIT
chmod 700 "$TMP_DIR"

echo "--- ♻️ Geri yükleme: $ARCHIVE ---"
tar -xzf "$ARCHIVE" -C "$TMP_DIR"
DUMP=$(find "$TMP_DIR" -name '*.dump' -print -quit)
if [ -z "$DUMP" ]; then
    echo "❌ Yedekte .dump dosyası yok."
    exit 1
fi

PGPASSWORD="$DB_PASSWORD" pg_restore \
    --host "$DB_HOST" --port "$DB_PORT" --username "$DB_USER" --dbname "$DB_NAME" \
    --clean --if-exists --no-owner --no-acl --exit-on-error "$DUMP"

echo "✅ Veritabanı geri yüklendi. Şema doğrulanıyor..."
python3 database/init_db.py

PORT="${PORT:-8000}"
bash run.sh
if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    echo "✅ Geri yükleme sonrası /health 200."
else
    echo "❌ /health doğrulanamadı. Log: logs/app.log"
    exit 1
fi
