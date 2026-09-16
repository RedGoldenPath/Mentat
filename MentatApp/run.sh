#!/bin/bash
# Launch the Mentat menu-bar app, starting the local engine first if needed.
DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$DIR/.."
if ! curl -s http://127.0.0.1:8765/status >/dev/null 2>&1; then
  (cd "$APP_DIR" && nohup .venv/bin/python server.py --port 8765 > /tmp/mentat_server.log 2>&1 &)
  sleep 4
fi
open "$DIR/Mentat.app"
