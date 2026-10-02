"""Retrieval: exact words (FTS5/BM25) + meaning (vectors) + spans + census, fused."""
from __future__ import annotations
import os
import re
import numpy as np
from . import gateway, store, config

_CTX_STATE = {"sig": None, "ready": False}

_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]{1,}")
_STOP = set("the a an is are was were to of in for on and or but not this that these those "
            "with from at by as it its be been being do does did you your me my i we our us "
            "can could should would will shall what which who whom whose why how when where "
            "if then than there here also just very about into over under".split())


def terms(text, cap=12):
    return [w.lower() for w in _WORD.findall(text or "") if w.lower() not in _STOP][:cap]


def _fts_query(ts):
    return " OR ".join(f'"{t}"' for t in ts if t)


def _ctx_ready():
    """True once the contextual index fully covers the library (else use v1). Memoized
    against ctx.db's mtime/size so we don't run COUNT(*) four times per retrieve."""
    try:
        st = os.stat(config.CTX_DB)
        sig = (st.st_mtime_ns, st.st_size)
        if _CTX_STATE["sig"] == sig:
            return _CTX_STATE["ready"]
        n = store.ctx().execute("SELECT count(*) FROM ctx_vec_rowids").fetchone()[0]
        total = store.v1("library").execute("SELECT count(*) FROM chunks").fetchone()[0]
        ready = total > 0 and n >= total
        _CTX_STATE["sig"], _CTX_STATE["ready"] = sig, ready
        return ready
    except Exception:
        return False


def _bm25_ctx(query, k, scope):
    ts = terms(query)
    if not ts:
        return []
    try:
        rows = store.ctx().execute(
            "SELECT chunk_id FROM ctx_fts WHERE ctx_fts MATCH ? ORDER BY bm25(ctx_fts) LIMIT ?",
            (_fts_query(ts), k * 4)).fetchall()
    except Exception:
        return []
    out = []
    for r in rows:
        ch = store.get_chunk(r["chunk_id"])
        if not ch or (scope and not _in_scope(ch.get("file_path", ""), scope)):
            continue
        out.append(ch)
        if len(out) >= k:
            break
    return out


def _vector_ctx(query, k, scope):
    try:
        emb = gateway.embed(query)[0].astype(np.float32).tobytes()
        rows = store.ctx().execute(
            "SELECT chunk_id FROM ctx_vec WHERE embedding MATCH ? AND k = ? ORDER BY distance",
            (emb, k * 4)).fetchall()
    except Exception:
        return []
    out = []
    for r in rows:
        ch = store.get_chunk(r["chunk_id"])
        if not ch or (scope and not _in_scope(ch.get("file_path", ""), scope)):
            continue
        out.append(ch)
        if len(out) >= k:
            break
    return out


def bm25(query, k=20, scope=None):
    ts = terms(query)
    if not ts:
        return []
    if _ctx_ready():
        return _bm25_ctx(query, k, scope)
    con = store.v1("fts")
    try:
        rows = con.execute(
            "SELECT chunk_id, file_path, content, bm25(chunks_fts) AS s FROM chunks_fts "
            "WHERE chunks_fts MATCH ? ORDER BY s LIMIT ?",
            (_fts_query(ts), k * 4)).fetchall()
    except Exception:
        return []
    out = []
    for r in rows:
        d = dict(r)
        if scope and not _in_scope(d.get("file_path", ""), scope):
            continue
        out.append(d)
        if len(out) >= k:
            break
    return out


def _in_scope(file_path, scope):
    low = str(file_path).lower()
    return any(s.lower() in low for s in scope)


def vector(query, k=20, scope=None):
    if _ctx_ready():
        return _vector_ctx(query, k, scope)
    con = store.v1("vec")
    try:
        emb = gateway.embed(query)[0].astype(np.float32).tobytes()
        rows = con.execute(
            "SELECT chunk_id, distance FROM chunks_vec WHERE embedding MATCH ? AND k = ? "
            "ORDER BY distance", (emb, k * 4)).fetchall()
    except Exception:
        return []
    out = []
    for r in rows:
        ch = store.get_chunk(r[0])
        if not ch:
            continue
        if scope and not _in_scope(ch.get("file_path", ""), scope):
            continue
        out.append(ch)
        if len(out) >= k:
            break
    return out


def book_of(file_path):
    """Clean book title from a manifest path or a 'file · chapter' locator."""
    fp = str(file_path or "")
    book = fp.split(" \u00b7 ")[0]
    book = book.split("\u203a")[-1]          # 'books › philosophy › Kojeve › X.pdf'
    return book.rstrip("/").split("/")[-1].strip()


_book_of = book_of


def rrf(lists, k=60):
    scores, first = {}, {}
    for lst in lists:
        for rank, c in enumerate(lst or []):
            cid = c.get("chunk_id")
            if not cid:
                continue
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
            first.setdefault(cid, c)
    return [first[c] for c in sorted(scores, key=lambda c: -scores[c])]


def retrieve(query, k=8, scope=None, budget_chars=14000):
    b = bm25(query, k=k * 3, scope=scope)
    v = vector(query, k=k * 3, scope=scope)
    fused = rrf([b, v])
    if not fused:
        return []
    cand = fused[: max(k * 4, 24)]
    texts = [c.get("content", "")[:1200] for c in cand]
    try:
        scores = gateway.rerank(query, texts)
    except Exception:
        scores = [1.0] * len(cand)
    order = sorted(range(len(cand)), key=lambda i: -scores[i])
    out, used = [], 0
    for i in order:
        c = cand[i]
        txt = c.get("content", "")
        cost = min(len(txt), 2600)   # budget counts the excerpt the writer receives
        if used + cost > budget_chars and out:
            break
        out.append(c)
        used += cost
        if len(out) >= k:
            break
    return to_passages(out, scores_by_cid={c.get("chunk_id"): scores[j] for j, c in enumerate(cand)})


def to_passages(chunks, scores_by_cid=None):
    scores_by_cid = scores_by_cid or {}
    out = []
    for c in chunks:
        cid = c.get("chunk_id")
        out.append({
            "chunk_id": cid,
            "work": _book_of(c.get("file_path")),
            "loc": c.get("chapter") or (c.get("file_path", "").split(" · ")[-1] if " · " in c.get("file_path", "") else ""),
            "text": c.get("content", ""),
            "score": c.get("score", scores_by_cid.get(cid, 0.0)),
        })
    return out


def hunt(query, limit=8, scan_terms=None):
    """Quote hunt: scan for the rarest terms, score chunks by coverage of all terms."""
    ts = terms(query, cap=8)
    if not ts:
        return []
    con = store.v1("library")
    rare = (scan_terms or ts)[:4]
    scored = {}
    for t in rare:
        try:
            rows = con.execute(
                "SELECT chunk_id, file_path, book, chapter, content FROM chunks "
                "WHERE content LIKE ? LIMIT 4000", (f"%{t}%",)).fetchall()
        except Exception:
            rows = []
        for r in rows:
            d = dict(r)
            hay = (d.get("content") or "").lower()
            hits = sum(1 for x in ts if x in hay)
            bonus = 2 if t in rare[:2] else 1
            scored[d["chunk_id"]] = (scored.get(d["chunk_id"], (0, d))[0] + hits + bonus, d)
    ranked = sorted(scored.values(), key=lambda x: -x[0])[: max(limit * 3, 12)]
    out = []
    for sc, d in ranked:
        out.append(d)
        if len(out) >= limit:
            break
    return to_passages(out, scores_by_cid={d["chunk_id"]: float(sc) for sc, d in ranked})


def span_hunt(query, limit=10):
    """Span-anchored quote hunt: find the exact sentence/paragraph and its page.

    Reference: RAGFlow's `insert_citations` — bind a quote to a precise source span.
    """
    ts = terms(query, cap=6)
    if not ts:
        return []
    con = store.v1("library")
    best, bestn = ts[0], None
    for t in ts:
        try:
            n = con.execute("SELECT count(*) FROM spans WHERE text LIKE ?",
                            (f"%{t}%",)).fetchone()[0]
        except Exception:
            n = 10 ** 9
        if bestn is None or n < bestn:
            bestn, best = n, t
    try:
        rows = con.execute(
            "SELECT span_id, chunk_id, file_path, text, start FROM spans "
            "WHERE text LIKE ? LIMIT ?", (f"%{best}%", limit * 12)).fetchall()
    except Exception:
        return []
    scored = []
    for r in rows:
        hay = (r["text"] or "").lower()
        hits = sum(1 for t in ts if t in hay)
        scored.append((hits, dict(r)))
    scored.sort(key=lambda x: -x[0])
    out = []
    for sc, d in scored[:limit]:
        page = None
        ch = store.get_chunk(d["chunk_id"])
        if ch and d.get("start"):
            pages = re.findall(r"##\s*Page\s+(\d+)", ch["content"][: d["start"]])
            page = pages[-1] if pages else None
        loc = f"p. {page}" if page else (d["file_path"].split(" · ")[-1] if " · " in d["file_path"] else "")
        out.append({"chunk_id": d["chunk_id"], "span_id": d["span_id"], "work": _book_of(d["file_path"]),
                    "loc": loc, "text": d["text"], "score": float(sc)})
    return out


def census(phrase, scope=None):
    """Deterministic count of a phrase across chunk text (case/diacritic tolerant)."""
    norm = re.sub(r"\s+", " ", (phrase or "").lower()).strip()
    if not norm:
        return {"total": 0, "per_work": {}}
    con = store.v1("library")
    total = 0
    per = {}
    for r in con.execute("SELECT file_path, content FROM chunks"):
        if scope and not _in_scope(r["file_path"], scope):
            continue
        hay = re.sub(r"\s+", " ", (r["content"] or "").lower())
        n = hay.count(norm)
        if n:
            book = _book_of(r["file_path"])
            per[book] = per.get(book, 0) + n
            total += n
    return {"total": total, "per_work": per}
