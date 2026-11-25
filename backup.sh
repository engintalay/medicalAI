#!/bin/bash
# backup.sh - PostgreSQL yedeği + system_config dump (gizli değerler asla ekrana yazılmaz)
# Çıktı: backups/medicalai-<timestamp>.tar.gz (0600)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

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

command -v pg_dump >/dev/null 2>&1 || { echo "❌ pg_dump bulunamadı."; exit 1; }

STAMP=$(date +%Y%m%d-%H%M%S)
mkdir -p backups
DUMP="backups/.medicalai-${STAMP}.dump"
CONFIG_SQL="backups/.medicalai-config-${STAMP}.sql"
ARCHIVE="backups/medicalai-${STAMP}.tar.gz"
umask 077

cleanup() { rm -f "$DUMP" "$CONFIG_SQL"; }
trap cleanup EXIT

echo "--- 💾 Yedekleme başlatılıyor: $STAMP ---"
PGPASSWORD="$DB_PASSWORD" pg_dump \
    --host "$DB_HOST" --port "$DB_PORT" --username "$DB_USER" --dbname "$DB_NAME" \
    --format=custom --no-owner --no-acl --file "$DUMP"

PGPASSWORD="$DB_PASSWORD" pg_dump \
    --host "$DB_HOST" --port "$DB_PORT" --username "$DB_USER" --dbname "$DB_NAME" \
    --data-only --table=system_config --no-owner --no-acl --file "$CONFIG_SQL"

tar -czf "$ARCHIVE" -C backups \
    ".medicalai-${STAMP}.dump" ".medicalai-config-${STAMP}.sql"
chmod 600 "$ARCHIVE"

echo "✅ Yedek oluşturuldu: $ARCHIVE"
echo "ℹ️  system_config dump gizli değerler içerir; dosya 0600 olarak yazıldı."

# Son 10 yedeği koru
ls -1t backups/medicalai-*.tar.gz 2>/dev/null | tail -n +11 | while read -r old; do
    rm -f "$old"
done
