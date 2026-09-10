#!/usr/bin/env bash
# Auto-startup Script (любой хостинг или локальный ПК)
echo "[*] Checking Python dependencies..."
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt

echo "[*] Starting Telegram Userbot..."
exec python3 main.py
