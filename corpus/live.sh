#!/bin/zsh
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
cd /Users/raphael/Everything/mentat/app || exit 1
while true; do
  clear
  uv run python corpus/status.py
  echo
  echo "  ── refreshes every 30 s · press Ctrl-C to stop ──"
  sleep 30
done
