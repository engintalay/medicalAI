#!/bin/bash
# stop.sh - Medical AI Uygulamasını Durdurur

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "--- 🛑 Medical AI Uygulamasını Durduruyor ---"

# PID dosyasını kontrol et
PID_FILE="$SCRIPT_DIR/venv/pidfile"

if [ -f "$PID_FILE" ]; then
    # PID dosyasını oku ve process'i durdur
    PID=$(cat "$PID_FILE")
    echo "[STEP 1/2] PID dosyası bulundu: $PID"
    
    # Process'i durdur
    if kill -0 "$PID" 2>/dev/null; then
        echo "[STEP 2/2] Process'i durduruyor..."
        kill "$PID" 2>/dev/null
        sleep 2
    else
        echo "[STEP 2/2] Process zaten durdu. PID dosyasını temizliyorum..."
    fi
    
    # PID dosyasını temizle
    rm -f "$PID_FILE"
    echo "✅ PID dosyası temizlendi."
    
    # Belki pkill ile de kontrol et (garanti için)
    pkill -f "uvicorn.*app:app" 2>/dev/null
    echo "✅ Uvicorn process'leri temizlendi."
    
else
    # PID dosyası yoksa, process'i bul ve durdur
    echo "[STEP 1/2] PID dosyası bulunamadı. Process'leri arıyoruz..."
    
    # uvicorn process'lerini bul
    UVICORN_PIDS=$(pgrep -f "uvicorn.*app:app" 2>/dev/null)
    
    if [ -n "$UVICORN_PIDS" ]; then
        echo "[STEP 2/2] Process'leri durduruyor..."
        echo "$UVICORN_PIDS" | while read PID; do
            kill "$PID" 2>/dev/null
            echo "  - Durduruldu: PID $PID"
        done
        
        echo "✅ Tüm uvicorn process'leri durduruldu."
    else
        echo "✅ Uvicorn process'leri bulunamadı. Uygulama zaten kapalı olabilir."
    fi
fi

echo ""
echo "========================================"
echo "  Durdurma işlemi tamamlandı!"
echo "========================================"
