#!/bin/bash
# restart.sh - Medical AI Uygulamasını Yeniden Başlatır
# Önce durdurur, sonra başlatır

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "--- 🔄 Medical AI Uygulamasını Yeniden Başlatıyor ---"

# 1. Önce durdur
echo "[STEP 1/2] Önce mevcut işlemi durduruyor..."
bash stop.sh

# 2. Sonra başlat
echo "[STEP 2/2] Uygulamayı yeniden başlatıyor..."
bash run.sh
