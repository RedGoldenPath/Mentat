#!/bin/zsh
# Waits for the running `brain.py index` to finish, then runs the INDEX_RESUME.md §3
# verification and writes the result to corpus/logs/index_verify.log.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
cd /Users/raphael/Everything/mentat/app || exit 1
LOG=corpus/logs/index_verify.log
{
  echo "=== verify watcher started $(date) ==="
  while pgrep -f "brain.py index" >/dev/null; do sleep 30; done
  echo "index process gone at $(date)"
  sleep 5
  echo "--- counts ---"
  uv run python - <<'PY'
import brain_core as bc
db = bc._library_db()
n_chunks = db.execute("SELECT count(*) FROM chunks").fetchone()[0]
n_files  = db.execute("SELECT count(distinct file_path) FROM chunks").fetchone()[0]
vec = bc._vec_db().execute("SELECT count(*) FROM chunks_vec").fetchone()[0]
print("chunks:", n_chunks, "vec:", vec, "match:", n_chunks == vec)
print("files:", n_files, "manifest:", len(bc._load_manifest()))
new, ch, rm, cur = bc._scan_changes()
print("pending:", len(new) + len(ch))
PY
  echo "--- find probe ---"
  uv run python brain.py find "the state is a special organisation of armed men"
  echo "=== verify done $(date) ==="
} >> "$LOG" 2>&1
