#!/usr/bin/env python
"""One-off: rebuild storage/manifest.json from chunks already present in library.db.

Why: manifest.json got reset (to ~125 entries) during the bge-m3 re-embed work, but
the DB already holds chunks for ~12,256 files. Without this, a plain `brain index`
re-embeds every one of those before reaching the genuinely-new files.

How it maps DB rows back to files (two fingerprint shapes, verified):
  * plain file  -> chunks.file_path == rel.replace('/', ' \u203a ')          (exact)
  * epub/chapter-> chunks.file_path == "<rel> \u00b7 <chapter> (chN)"         (split on " \u00b7 ")

Safety: a file is only marked done if a fingerprint provably belongs to it
(exact match, or by_rel match) AND every doc's chunk indices are a gap-free
0..N run (contiguity gate). Anything ambiguous is left out -> it just re-indexes.
Never marks a partially-chunked file as done.

Usage:
    uv run python corpus/rebuild_manifest.py            # dry run (report only)
    uv run python corpus/rebuild_manifest.py --apply    # write manifest.json
"""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import brain_core as bc  # noqa: E402


def main() -> None:
    apply = "--apply" in sys.argv

    db = bc._library_db()
    rows = db.execute("SELECT file_path, chunk_id FROM chunks").fetchall()
    if not rows:
        print("no chunks in library.db — nothing to do")
        return

    fps = set()
    stems_by_fp = defaultdict(set)   # fp -> {doc-stem, ...}
    idx_by_fp = defaultdict(lambda: defaultdict(set))  # fp -> stem -> {chunk idx, ...}
    by_rel = defaultdict(list)       # rel (part before " \u00b7 ") -> [fp, ...]

    for fp, cid in rows:
        fps.add(fp)
        stem, _, tail = cid.rpartition("-chunk-")
        stems_by_fp[fp].add(stem)
        try:
            idx_by_fp[fp][stem].add(int(tail))
        except ValueError:
            pass
    for fp in fps:
        if " \u00b7 " in fp:
            by_rel[fp.split(" \u00b7 ", 1)[0]].append(fp)

    def contiguous(fps_list) -> bool:
        for fp in fps_list:
            for _stem, idxs in idx_by_fp.get(fp, {}).items():
                if not idxs:
                    return False
                hi = max(idxs)
                if min(idxs) != 0 or len(idxs) != hi + 1:
                    return False
        return True

    manifest = bc._load_manifest()
    before = len(manifest)
    marked = skipped = not_in_db = 0
    by_ext = defaultdict(lambda: [0, 0])  # ext -> [marked, total]

    for path in bc._iter_knowledge_files():
        rel = str(path.relative_to(bc.KNOWLEDGE_ROOT))
        ext = path.suffix.lower() or "(none)"
        arrow = rel.replace("/", " \u203a ")

        if arrow in fps:
            match_fps, docs = [arrow], [bc._doc_id(rel)]
        elif rel in by_rel:
            match_fps = by_rel[rel]
            docs = sorted({s for fp in match_fps for s in stems_by_fp.get(fp, ())})
        else:
            not_in_db += 1
            by_ext[ext][1] += 1
            continue

        by_ext[ext][1] += 1
        if not docs or not contiguous(match_fps):
            skipped += 1
            continue
        try:
            h = bc._file_hash(path)
        except OSError:
            skipped += 1
            continue
        manifest[rel] = {"hash": h, "docs": docs}
        marked += 1
        by_ext[ext][0] += 1

    print(f"scan: files marked done = {marked}")
    print(f"      skipped (ambiguous / gappy chunks) = {skipped}")
    print(f"      not in DB (will index normally)   = {not_in_db}")
    print(f"      manifest: {before} -> {len(manifest)} entries")
    print("by extension (marked/total):")
    for ext, (m, t) in sorted(by_ext.items(), key=lambda kv: -kv[1][1]):
        print(f"      {ext:>8}  {m}/{t}")

    if apply:
        bc._save_manifest(manifest)
        print(f"WROTE {bc.MANIFEST_PATH}")
    else:
        print("(dry run — pass --apply to write)")


if __name__ == "__main__":
    main()
