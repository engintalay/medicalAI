#!/bin/bash
# run.sh - Medical AI Projesini Başlatır
# http://localhost:8000 adresinde çalışır
# Admin panel: http://localhost:8000/admin

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "--- 🚀 Medical AI Uygulaması Başlatılıyor ---"

# 1. Sanal ortamı kontrol et ve gerekirse aktifleştir
if [ ! -d "venv" ]; then
    echo "[STEP 1/3] Sanal ortam (venv) kontrol ediliyor..."
    python3 -m venv venv
    echo "✅ venv oluşturuldu."
fi

# 2. Ortamı aktifleştir
echo "[STEP 2/3] Ortam aktifleştiriliyor..."
source venv/bin/activate

# 3. Uygulamayı başlat
echo "[STEP 3/3] Uygulama başlatılıyor..."
echo ""
echo "========================================"
echo "  Medical AI Uygulaması çalışıyor!"
echo "  API: http://localhost:8000"
echo "  Admin Panel: http://localhost:8000/admin"
echo "  Default Admin: admin@medicalai.com / changeme123"
echo "========================================"
echo ""

# 4. Uygulamayı başlat (background'da veya foreground'da)
# Foreground: Direkt bu scriptin içinde çalışır
uvicorn app:app --host 0.0.0.0 --port 8000

# Uygulama bittiğinde pidfile'i temizle
rm -f venv/pidfile 2>/dev/null

echo ""
echo "========================================"
echo "  Uygulama durdu. Durdurma işlemi tamamlandı."
echo "========================================"
