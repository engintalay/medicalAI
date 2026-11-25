#!/bin/bash
# restart.sh - Güvenli yeniden başlatma: önce durdur, PID doğrula, sonra başlat.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "--- 🔄 Medical AI Uygulaması Yeniden Başlatılıyor ---"

echo "[STEP 1/3] Mevcut işlem durduruluyor..."
bash stop.sh || exit 1

PID_FILE="$SCRIPT_DIR/venv/pidfile"
if [ -f "$PID_FILE" ]; then
    echo "⚠️ PID dosyası temizlenemedi; yeniden başlatma iptal edildi."
    exit 1
fi

echo "[STEP 2/3] Uygulama başlatılıyor..."
bash run.sh || exit 1

echo "[STEP 3/3] PID ve /health doğrulaması..."
PID=$(cat "$PID_FILE" 2>/dev/null)
if [ -z "$PID" ] || ! kill -0 "$PID" 2>/dev/null; then
    echo "❌ PID doğrulanamadı. Log: logs/app.log"
    exit 1
fi

PORT="${PORT:-8000}"
if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    echo "✅ Yeniden başlatma başarılı (PID $PID, /health 200)."
    exit 0
fi

echo "❌ /health 200 dönmedi. Log: logs/app.log"
exit 1
