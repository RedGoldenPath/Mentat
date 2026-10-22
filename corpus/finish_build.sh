#!/bin/bash
# Waits for the canon build to finish, then indexes everything and re-enables the watcher.
cd /Users/raphael/Everything/mentat/app || exit 1
echo "waiting for build to finish $(date)" >> corpus/logs/index_after_build.log
while pgrep -f run_build.py >/dev/null; do sleep 120; done
echo "build done, indexing $(date)" >> corpus/logs/index_after_build.log
uv run python brain.py index >> corpus/logs/index_after_build.log 2>&1
echo "indexing done, re-enabling watcher $(date)" >> corpus/logs/index_after_build.log
uv run python brain.py watch on >> corpus/logs/index_after_build.log 2>&1
