#!/bin/bash
# ============================================================
# Roblox Bot – VPS Kurulum Scripti (Ubuntu 22.04+)
# Nasıl çalıştırılır:
#   chmod +x setup_server.sh
#   ./setup_server.sh
# ============================================================

set -e

echo "=== Sistem güncelleniyor... ==="
apt update && apt upgrade -y

echo "=== Python 3.11 ve pip kuruluyor... ==="
apt install -y python3 python3-pip python3-venv git

echo "=== Proje dizini oluşturuluyor... ==="
mkdir -p /opt/robloxking
cd /opt/robloxking

echo "=== Sanal ortam oluşturuluyor... ==="
python3 -m venv venv
source venv/bin/activate

echo "=== Bağımlılıklar kuruluyor... ==="
pip install --upgrade pip
pip install -r requirements.txt

echo "=== output/ klasörü oluşturuluyor... ==="
mkdir -p output

echo ""
echo "✅ Python kurulumu tamamlandı."
echo ""
echo "SONRAKİ ADIMLAR:"
echo "  1. Dosyaları bu sunucuya yükle (SFTP veya scp komutuyla)"
echo "  2. sudo systemctl enable robloxbot"
echo "  3. sudo systemctl start robloxbot"
echo "  4. sudo systemctl status robloxbot"
