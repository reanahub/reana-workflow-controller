#!/bin/sh
set -e

echo "Starting Python S3 Data Manager..."
python3 /app/app.py
echo "Initialization complete."

exec tail -f /dev/null
