#!/usr/bin/env bash
# Bothost.ru Auto-startup Script
echo "[*] Checking Python dependencies for Bothost.ru..."
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt

echo "[*] Starting Telegram Userbot..."
exec python3 main.py
