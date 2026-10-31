#!/bin/bash
# install.sh - Medical AI Projesi Kurulum Scripti

echo "--- 🚀 Medical AI Projesi Kurulum Başlıyor ---"

# 1. Sanal Ortam Kontrolü ve Oluşturma
if [ ! -d "venv" ]; then
    echo "[STEP 1/4] Sanal ortam (venv) oluşturuluyor..."
    python3 -m venv venv
    if [ $? -eq 0 ]; then
        echo "✅ venv başarıyla oluşturuldu."
    else
        echo "❌ HATA: venv oluşturulamadı. Python 3 kurulu olduğundan emin olun."
        exit 1
    fi
else
    echo "[STEP 1/4] Sanal ortam (venv) zaten mevcut."
fi

# Ortamı aktive etme
source venv/bin/activate

# 2. Bağımlılıkların Kurulumu
echo "[STEP 2/4] Gereksinimler (requirements.txt) kuruluyor..."
pip install --upgrade pip
if pip install -r requirements.txt; then
    echo "✅ Tüm bağımlılıklar başarıyla kuruldu."
else
    echo "❌ HATA: Bağımlılıklar kurulurken bir sorun oluştu. Lütfen çıktıyı kontrol edin."
    exit 1
fi

# 3. Script'leri Çalıştırılabilir Yapma
echo "[STEP 3/4] Script dosyaları çalıştırılabilir hale getiriliyor..."
chmod +x run.sh restart.sh stop.sh

echo "✅ Tüm script'ler çalıştırılabilir olarak ayarlandı."

# 4. Doğrulama Testi
echo "[STEP 4/4] Temel bağımlılık doğrulama testleri çalıştırılıyor..."
# FastAPI'yi basit bir şekilde import edip kontrol ediyoruz
python -c "import fastapi; print('✅ FastAPI başarıyla import edildi.')"
# Redis'i basitçe kontrol ediyoruz (genellikle Redis'in localde/config'de olması gerekir)
python -c "import redis; try: r = redis.Redis(decode_responses=True); r.ping(); print('✅ Redis başarıyla ping atıldı (Bağlantı kontrolü OK).') except Exception as e: print(f'⚠️ Redis ping atıldı ancak bir hata oluştu: {e}')"

echo "==============================================="
echo "🎉 KURULUM TAMAMLANDI! 🎉"
echo "Ortamınız hazır. Şimdi kullanabilirsiniz:"
echo "  - `./run.sh` (Uygulamayı başlatmak için)"
echo "  - `./install.sh` (Tekrar kurmak için)"
echo "  - `./stop.sh` (Uygulamayı durdurmak için)"
echo "==============================================="