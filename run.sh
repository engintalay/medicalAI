#!/bin/bash
# run.sh - Medical AI uygulamasını arka planda başlatır (http://localhost:8000)
# PID: venv/pidfile · Log: logs/app.log (gizli değer yazılmaz)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "--- 🚀 Medical AI Uygulaması Başlatılıyor ---"

PID_FILE="$SCRIPT_DIR/venv/pidfile"
PORT="${PORT:-8000}"

if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "✅ Uygulama zaten çalışıyor (PID $OLD_PID): http://localhost:$PORT"
        exit 0
    fi
    rm -f "$PID_FILE"
fi

if [ ! -d "venv" ]; then
    echo "[STEP 1/3] Sanal ortam oluşturuluyor..."
    python3 -m venv venv || exit 1
fi

mkdir -p logs

if [ -x "venv/bin/uvicorn" ]; then
    SERVER=(venv/bin/uvicorn app:app --host 0.0.0.0 --port "$PORT")
else
    # venv bağımlılıkları kurulmamışsa sistem Python'unu kullan (install.sh önerilir).
    SERVER=(python3 -m uvicorn app:app --host 0.0.0.0 --port "$PORT")
fi

nohup "${SERVER[@]}" >> logs/app.log 2>&1 &
PID=$!
echo "$PID" > "$PID_FILE"

echo "[STEP 2/3] PID dosyası yazıldı: $PID"
echo "[STEP 3/3] /health kontrol ediliyor..."

OK=0
for _ in $(seq 1 20); do
    if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
        OK=1
        break
    fi
    if ! kill -0 "$PID" 2>/dev/null; then
        break
    fi
    sleep 1
done

echo "========================================"
echo "  API: http://localhost:$PORT"
echo "  Admin Panel: http://localhost:$PORT/admin"
echo "  Health: http://localhost:$PORT/health"
echo "========================================"

if [ "$OK" -eq 1 ]; then
    echo "✅ Uygulama hazır (PID $PID)."
    exit 0
fi

echo "⚠️ Uygulama başladı ancak /health yanıt vermedi. Log: logs/app.log"
exit 1
