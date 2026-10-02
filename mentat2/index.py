"""Contextual Retrieval index (Anthropic, "Introducing Contextual Retrieval").

For each chunk we prepend a short piece of document context before embedding it and
before indexing it for BM25 — so a chunk that says "revenue grew 3%" carries *which
document/part it came from* into retrieval. Anthropic's default contextualizer is a
Claude prompt; the post explicitly allows a **custom contextualizer**, which is what we
use here: the chunk's own bibliographic context (book · chapter) — deterministic, free,
and no re-embedding of anything but the contextualized text.

Built into its own db (`mentat2_data/ctx.db`) so it can be rebuilt/backed up alone.
Resumable: re-running skips chunks already embedded.

Usage: python -m mentat2.index [--limit N] [--batch 32]
"""
from __future__ import annotations
import argparse
import time

from . import config, store, gateway


def context_prefix(book, chapter, file_path):
    parts = [p for p in (book, chapter) if p]
    if not parts:
        parts = [str(file_path or "").split("/")[-1] or "the library"]
    return "From " + " — ".join(parts) + ":"


def ctx_text(book, chapter, file_path, content):
    return context_prefix(book, chapter, file_path) + "\n" + (content or "")


def indexed_ids():
    try:
        return {r[0] for r in store.ctx().execute("SELECT id FROM ctx_vec_rowids")}
    except Exception:
        return set()


def status():
    try:
        n = store.ctx().execute("SELECT count(*) FROM ctx_meta").fetchone()[0]
    except Exception:
        n = 0
    try:
        total = store.v1("library").execute("SELECT count(*) FROM chunks").fetchone()[0]
    except Exception:
        total = 0
    return {"indexed": n, "total": total, "ready": total > 0 and n >= total}


def build(limit=None, batch=32, verbose=True):
    con = store.ctx()
    lib = store.v1("library")
    done = indexed_ids()
    rows = lib.execute(
        "SELECT chunk_id,file_path,book,chapter,seq,content FROM chunks ORDER BY rowid").fetchall()
    todo = [r for r in rows if r["chunk_id"] not in done]
    if limit:
        todo = todo[:limit]
    if verbose:
        print(f"index: {len(done)} done · {len(todo)} to do", flush=True)
    t0, n = time.time(), 0
    for i in range(0, len(todo), batch):
        part = todo[i:i + batch]
        texts = [ctx_text(r["book"], r["chapter"], r["file_path"], r["content"]) for r in part]
        embs = gateway.embed(texts)
        for r, txt, e in zip(part, texts, embs):
            cid = r["chunk_id"]
            con.execute("INSERT OR REPLACE INTO ctx_meta(chunk_id,file_path,book,chapter,seq)"
                        " VALUES(?,?,?,?,?)", (cid, r["file_path"], r["book"], r["chapter"], r["seq"]))
            con.execute("DELETE FROM ctx_fts WHERE chunk_id=?", (cid,))
            con.execute("INSERT INTO ctx_fts(chunk_id,content) VALUES(?,?)", (cid, txt))
            con.execute("INSERT OR REPLACE INTO ctx_vec(chunk_id,embedding) VALUES(?,?)",
                        (cid, e.astype("float32").tobytes()))
            n += 1
        con.commit()
        if verbose and (i // batch) % 20 == 0:
            print(f"  {n}/{len(todo)} · {time.time()-t0:.0f}s", flush=True)
    if verbose:
        print(f"index: built {n} chunks in {time.time()-t0:.0f}s", flush=True)
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--batch", type=int, default=32)
    a = ap.parse_args()
    build(limit=a.limit or None, batch=a.batch)
    print(status())


if __name__ == "__main__":
    main()
