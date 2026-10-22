#!/bin/bash
# Waits for ALL corpus builds (MIA mirror + Gutenberg) to finish, then indexes
# everything once and re-enables the vault watcher.
cd /Users/raphael/Everything/mentat/app || exit 1
L=corpus/logs/index_after_build.log
echo "waiting for builds $(date)" >> "$L"
while pgrep -f "run_build.py|gutenberg.py" >/dev/null; do sleep 120; done
echo "builds done, indexing $(date)" >> "$L"
uv run python brain.py index >> "$L" 2>&1
echo "indexing done, re-enabling watcher $(date)" >> "$L"
uv run python brain.py watch on >> "$L" 2>&1
echo "ALL DONE $(date)" >> "$L"
