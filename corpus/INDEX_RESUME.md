# INDEX RESUME — handoff runbook

**Goal:** finish the Mentat corpus index efficiently. The DB already holds ~10,967
files' chunks (bge-m3, 1024-dim); a plain `brain index` would re-embed every one of
them before reaching the ~22,273 genuinely-new files. Rebuild the manifest from the DB
first so the run only embeds what's new.

State at handoff: index run **stopped**. `brain_core.py` already contains the vec0
insert fix (see below). DB = 102,460 chunks / 10,967 files; `manifest.json` ~173 entries.

---

## Step 1 — Rebuild the manifest from the DB (one-off, ~1–2 min)

```sh
cd /Users/raphael/Everything/mentat/app
uv run python corpus/rebuild_manifest.py            # dry run: report only
uv run python corpus/rebuild_manifest.py --apply    # write storage/manifest.json
```

Expected (dry run): `files marked done ≈ 10967`, `skipped ≈ 1`, `not in DB ≈ 22273`,
`manifest: ~173 -> ~10975`. The script is exact-match only + a chunk-contiguity gate,
so it never marks a partially-chunked file as done (worst case a file just re-indexes).

## Step 2 — Run the index (alphabetical, resumable)

```sh
cd /Users/raphael/Everything/mentat/app
nohup env MENTAT_OCR=off MENTAT_INDEX_DEFER_FTS=1 MENTAT_INDEX_BATCH=16 \
  MENTAT_EMBED_BATCH=64 MENTAT_EMBED_CONCURRENCY=4 \
  uv run python brain.py index > corpus/logs/index_fast9.log 2>&1 &
```

- `_scan_changes()` now sees the ~10,967 as unchanged → only ~22k new files embed.
- Commits every 16-file group; `manifest.json` is checkpointed after each group
  (a kill loses at most one group).
- Friendly live view (optional, opens a Terminal): `corpus/index_live.sh`.
- Watch progress: `grep -c '^indexed:' corpus/logs/index_fast9.log`.

## Step 3 — Verify (nothing lost)

```sh
cd /Users/raphael/Everything/mentat/app
uv run python - <<'PY'
import brain_core as bc
db = bc._library_db()
n_chunks = db.execute("SELECT count(*) FROM chunks").fetchone()[0]
n_files  = db.execute("SELECT count(distinct file_path) FROM chunks").fetchone()[0]
print("chunks:", n_chunks, "vec:", bc._vec_db().execute("SELECT count(*) FROM chunks_vec").fetchone()[0])
print("fts:", db.execute("SELECT count(*) FROM chunks_fts").fetchone()[0] if False else "—")
print("files:", n_files, "manifest:", len(bc._load_manifest()))
new, ch, rm, cur = bc._scan_changes()
print("pending:", len(new) + len(ch))
PY
# search works end to end:
uv run python brain.py find "the state is a special organisation of armed men"
```

Pass criteria: `chunks == vec`; pending → ~0 at the end; a `find`/`probe` returns hits;
`storage/deferred_ocr.json` lists the scan-only PDFs.

## Step 4 (later) — OCR pass for deferred scans

`storage/deferred_ocr.json` holds PDFs skipped because they have no text layer
(mostly scanned). Run them once with `MENTAT_OCR=on` (or a dedicated OCR pass) when
convenient. Nothing is lost in the meantime — they're tracked, not dropped.

---

## The bug that was fixed (context)

`_vec_insert_many` used `INSERT OR REPLACE` into the sqlite-vec `vec0` table
`chunks_vec`. **vec0 ignores `OR REPLACE`**, so re-committing an existing chunk_id
raised `UNIQUE constraint failed on chunks_vec primary key` and left the write txn
half-open → later commits wedged on a DB lock (the "0% CPU, no progress, silent"
symptom). Fixed to: dedupe within the batch → `DELETE ... WHERE chunk_id IN (...)` →
plain `INSERT`, with `rollback()` on error. Same pattern to remember for any future
vec0 writes (e.g. the atomic-swap rebuild path).

## Config / preconditions

- Engine dir: `/Users/raphael/Everything/mentat/app`; run via `uv run python …`.
- `.env` carries `OLLAMA_EMBED_MODEL=bge-m3`, `EMBED_DIM=1024`,
  `MENTAT_EMBED_BATCH=64`, `MENTAT_EMBED_CONCURRENCY=4`, `MENTAT_INDEX_DEFER_FTS=1`,
  `MENTAT_INDEX_BATCH=16`.
- Ollama must be up (bge-m3 loaded): `curl -s 127.0.0.1:11434/api/tags | head -c 80`.
- `MENTAT_OCR=off` is why scan-only PDFs are deferred (not errors).

## Gotchas

- Don't run two `brain index` at once (a run-guard exists; the second returns
  `already_running`).
- Output only prints per-file `indexed:` lines once a 16-file group finishes
  embedding, so expect a short silent stretch at the very start.
- Storage: `app/storage/{library.db,fts.db,vec.db,manifest.json,deferred_ocr.json}`.
  Backup of the pre-bge-m3 index: `app/storage.bak.768dim.20261013`.
- Canonical project notes live in `/Users/raphael/Everything/mentat/CORPUS.md`.
