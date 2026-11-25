#!/bin/bash
# stop.sh - Uygulamayı PID dosyasıyla durdurur; artık process/port varsa temizler.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "--- 🛑 Medical AI Uygulaması Durduruluyor ---"

PID_FILE="$SCRIPT_DIR/venv/pidfile"
PORT="${PORT:-8000}"

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE" 2>/dev/null)
    if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
        echo "[STEP 1/3] PID $PID durduruluyor..."
        kill "$PID" 2>/dev/null
        for _ in $(seq 1 10); do
            kill -0 "$PID" 2>/dev/null || break
            sleep 0.5
        done
        kill -9 "$PID" 2>/dev/null || true
    fi
    rm -f "$PID_FILE"
fi

# PID dosyası yoksa/bozuksa uvicorn process'lerini bul.
LEFT=$(pgrep -f "uvicorn.*app:app" 2>/dev/null || true)
if [ -n "$LEFT" ]; then
    echo "[STEP 2/3] Kalan uvicorn process'leri temizleniyor..."
    echo "$LEFT" | while read -r PID; do
        [ "$PID" = "$$" ] && continue
        kill "$PID" 2>/dev/null || true
    done
fi

# Port hâlâ doluysa serbest bırak (fuser varsa).
if command -v fuser >/dev/null 2>&1; then
    fuser -k "${PORT}/tcp" >/dev/null 2>&1 || true
fi

echo "[STEP 3/3] Doğrulama..."
if command -v fuser >/dev/null 2>&1 && fuser "${PORT}/tcp" >/dev/null 2>&1; then
    echo "⚠️ Port $PORT hâlâ kullanımda."
    exit 1
fi

echo "✅ Durdurma işlemi tamamlandı."
exit 0
