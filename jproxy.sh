#!/bin/bash
# jproxy startup script - auto cleanup port 8000
PORT=8000

if command -v lsof >/dev/null 2>&1; then
    PIDS=$(lsof -i :$PORT -t 2>/dev/null)
    if [ -n "$PIDS" ]; then
        echo "  Port $PORT is occupied, cleaning up..."
        kill -9 $PIDS 2>/dev/null
        sleep 1
        echo "  Cleaned"
    fi
fi

cd "$(dirname "$0")" && exec python3 jproxy_cli.py "$@"
