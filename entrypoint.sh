#!/bin/bash

# 1. Start the Watchdog in the background
echo "Starting Wi-Fi Watchdog..."
python3 wifi_watchdog.py &

# 2. Start the Main Web Server (This keeps the container running)
echo "Starting Manga Server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000