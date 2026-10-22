#!/usr/bin/env python
"""Acquire the WANTED reading-list titles into the vault (Internet Archive first).

For each entry in books/_catalog/wanted.json:
  1. Search archive.org (title + author aliases), collect candidate items.
  2. For each candidate, read metadata; keep only UNRESTRICTED items that carry a
     full text file (_djvu.txt preferred, then .pdf, then .epub).
  3. Pick the largest acceptable one (size gate drops partial/scan-only uploads).
  4. Download to a temp dir, then ATOMICALLY move into the taxonomy destination
     (so the vault watcher never indexes a half-written file).
  5. Skip anything already in the library; log every decision.

Safe to run WHILE `brain index` runs: this only writes files under books/; the
running indexer enumerated its file list already, and the watcher defers to the
index run-guard and re-queues for a follow-up pass.

    uv run python corpus/acquire_wanted.py [--only id,id] [--limit N] [--dry]
                                           [--min-text N] [--sleep S]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
APP = HERE.parent
MENTAT = APP.parent
BOOKS = MENTAT / "books"
TMP = HERE / "tmp"
LOGDIR = HERE / "logs"
WANTED = BOOKS / "_catalog" / "wanted.json"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

TEXT_EXT = (".txt",)
BOOK_EXT = (".pdf", ".epub")
MIN_TEXT = 30_000      # bytes; drops partial pamphlet-like uploads
MIN_BOOK = 150_000     # bytes; for pdf/epub

STOP = {"the", "of", "and", "in", "his", "her", "a", "an", "on", "to", "for",
        "with", "its", "is", "ii", "iii", "vol", "volume"}

# Cross-cutting words that show up in almost every title in this corner of the
# corpus — useless for telling two books apart, so excluded from "distinctive".
COMMON = {
    "islam", "islamic", "arabi", "arab", "arabic", "sufi", "sufism", "god", "divine",
    "wisdom", "book", "books", "world", "worlds", "modern", "tradition", "traditional",
    "studies", "study", "religion", "religions", "religious", "spiritual", "spirituality",
    "sacred", "mystery", "garden", "philosophy", "history", "thought", "life", "nature",
    "man", "art", "science", "essays", "introduction", "essential", "letters", "works",
    "selected", "light", "heart", "soul", "self", "law", "path", "way", "time", "crisis",
    "problem", "message", "meaning", "truth",
}


def sig_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower())
            if len(w) >= 4 and w not in STOP}


def distinctive_words(title: str) -> set[str]:
    return {w for w in sig_words(title) if w not in COMMON}


def author_key(author: str) -> str:
    """Last alphabetic token of the author's name, lowercased (e.g. 'al-Kashani' -> 'kashani')."""
    toks = re.findall(r"[A-Za-z]+", author.lower())
    return toks[-1] if toks else author.lower()


def slugify(text: str) -> str:
    text = re.sub(r"[^\w\s.-]", "", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


_AR_DIAC = re.compile(r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed\u0640]")


def is_arabic(s: str) -> bool:
    return bool(re.search(r"[\u0600-\u06ff]", s))


def ar_words(s: str) -> set[str]:
    """Arabic tokens (>=2 letters), diacritics/tatweel stripped."""
    s = _AR_DIAC.sub("", s)
    return set(re.findall(r"[\u0600-\u06ff]{2,}", s))


def log(fh, msg: str) -> None:
    print(msg, flush=True)
    if fh:
        fh.write(msg + "\n")
        fh.flush()


_LIBRARY_CACHE: list[tuple[str, str]] | None = None


def _library_files() -> list[tuple[str, str]]:
    global _LIBRARY_CACHE
    if _LIBRARY_CACHE is None:
        _LIBRARY_CACHE = [
            (p.name.lower(), str(p.relative_to(BOOKS)))
            for p in BOOKS.rglob("*") if p.is_file()
        ]
    return _LIBRARY_CACHE


def already_present(entry: dict) -> str | None:
    """Return the matching existing path if this title looks already in the library."""
    akey = author_key(entry["author"])
    dist = distinctive_words(entry["title"])
    base = sig_words(entry["title"])
    atoks = set(re.findall(r"[a-z]+", entry["author"].lower()))
    target = base - atoks  # ignore the author's own name when matching titles
    for name, rel in _library_files():
        if akey not in name:
            continue
        nw = sig_words(name)
        if dist:
            if dist & nw:
                return rel
        elif len(target & nw) >= 2:
            return rel
    return None


def ia_search(sess, query: str, rows: int = 10) -> list[dict]:
    url = "https://archive.org/advancedsearch.php"
    params = {
        "q": query,
        "fl[]": ["identifier", "title", "creator", "access-restricted-item", "collection"],
        "rows": rows,
        "page": 1,
        "output": "json",
    }
    try:
        r = sess.get(url, params=params, timeout=30)
        r.raise_for_status()
        return r.json()["response"]["docs"]
    except Exception as e:
        return [{"_err": str(e)[:80]}]


def ia_meta(sess, ident: str) -> dict | None:
    try:
        r = sess.get(f"https://archive.org/metadata/{ident}", timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def best_file(meta: dict):
    """Return (fname, size_bytes, rank) for the best full-text file, else None."""
    if not meta:
        return None
    md = meta.get("metadata", {})
    if str(md.get("access-restricted-item", "")).lower() == "true":
        return None
    if md.get("is_dark") is True:
        return None
    best = None
    for f in meta.get("files", []):
        name = f.get("name", "")
        low = name.lower()
        try:
            size = int(f.get("size", 0) or 0)
        except ValueError:
            size = 0
        rank = None
        if low.endswith("_djvu.txt"):
            rank = 0
        elif low.endswith(".pdf"):
            rank = 1
        elif low.endswith(".epub"):
            rank = 2
        elif low.endswith(".txt"):
            rank = 3
        if rank is None:
            continue
        if best is None or (rank, -size) < (best[2], -best[1]):
            best = (name, size, rank)
    return best


def download(sess, ident: str, fname: str, out: Path) -> bool:
    from urllib.parse import quote
    url = f"https://archive.org/download/{ident}/{quote(fname)}"
    try:
        with sess.get(url, timeout=120, stream=True) as r:
            r.raise_for_status()
            with open(out, "wb") as f:
                for chunk in r.iter_content(65536):
                    f.write(chunk)
        return out.exists() and out.stat().st_size > 0
    except Exception:
        if out.exists():
            out.unlink()
        return False


def acquire_ia(sess, entry: dict, fh, min_text: int, sleep: float, dry: bool = False) -> dict:
    title_words = sig_words(entry["title"])
    dist = distinctive_words(entry["title"])
    akey = author_key(entry["author"])
    ar_strs = [a for a in (entry.get("aliases", []) + [entry["title"]]) if is_arabic(a)]
    ar_aw = [ar_words(a) for a in ar_strs]
    is_ar = bool(ar_aw)
    cands: dict[str, dict] = {}
    for q in entry.get("aliases", []) + [f'{entry["author"]} {entry["title"]}']:
        for d in ia_search(sess, q):
            ident = d.get("identifier")
            if ident:
                cands[ident] = d
        time.sleep(sleep)
    if not cands:
        return {"status": "not-found", "detail": "no IA candidates"}

    def ar_hit(text: str) -> bool:
        hw = ar_words(text.lower())
        return any(len(aw & hw) >= max(2, len(aw) // 2) for aw in ar_aw)

    scored = []
    for ident, d in cands.items():
        blob = (str(d.get("title", "")) + " " + ident + " " + str(d.get("creator", ""))).lower()
        bw = sig_words(blob)
        if is_ar:
            if ar_hit(blob):
                scored.append((ident, d))
        elif (akey in blob) or (dist and (dist & bw)):
            scored.append((ident, d))
    if not scored:
        return {"status": "not-found", "detail": "candidates didn't match author/title"}

    pick = None  # (size, ident, fname, rank, d)
    for ident, d in scored:
        meta = ia_meta(sess, ident)
        bf = best_file(meta)
        time.sleep(sleep)
        if not bf:
            continue
        fname, size, rank = bf
        low = fname.lower()
        gate = min_text if low.endswith((".txt",)) else MIN_BOOK
        if size < gate:
            continue
        if pick is None or (rank, -size) < (pick[3], -pick[0]):
            pick = (size, ident, fname, rank, d)
    if pick is None:
        return {"status": "not-found", "detail": "no unrestricted full-text >= size gate"}

    size, ident, fname, rank, d = pick
    ext = Path(fname).suffix.lower()
    friendly = f"{slugify(entry['author'])} - {slugify(entry['title'])}{ext}"
    out = BOOKS / entry["dest"] / friendly
    if dry:
        return {"status": "acquired", "path": str(out.relative_to(BOOKS)),
                "size": size, "source": f"ia:{ident}", "ia_title": d.get("title", ""),
                "dry": True}

    TMP.mkdir(parents=True, exist_ok=True)
    tmpfile = TMP / f"{entry['id']}{ext}"
    if not download(sess, ident, fname, tmpfile):
        return {"status": "error", "detail": f"download failed {ident}/{fname}"}

    # Guard against mislabeled IA uploads (Latin titles only; Arabic OCR is too
    # unreliable to check, so we trust the search-title match there).
    if ext in (".txt",) and not is_ar:
        try:
            head = tmpfile.read_text(errors="ignore")[:4000].lower()
        except Exception:
            head = ""
        check = dist or title_words
        if check and not (check & set(re.findall(r"[a-z0-9]+", head))):
            tmpfile.unlink()
            return {"status": "not-found", "detail": "content mismatch (title words not on title page)"}

    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(tmpfile), str(out))
    return {"status": "acquired", "path": str(out.relative_to(BOOKS)),
            "size": size, "source": f"ia:{ident}", "ia_title": d.get("title", "")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry", action="store_true", help="search only, do not download")
    ap.add_argument("--min-text", type=int, default=MIN_TEXT)
    ap.add_argument("--sleep", type=float, default=0.8)
    args = ap.parse_args()

    entries = json.loads(WANTED.read_text())
    if args.only:
        want = {s.strip() for s in args.only.split(",")}
        entries = [e for e in entries if e["id"] in want]
    if args.limit:
        entries = entries[: args.limit]

    LOGDIR.mkdir(exist_ok=True)
    logpath = LOGDIR / "acquire_wanted.log"
    sess = requests.Session()
    sess.headers.update({"User-Agent": UA})

    results = []
    with open(logpath, "a") as fh:
        log(fh, f"\n=== acquire_wanted {time.strftime('%Y-%m-%d %H:%M:%S')} "
                f"({len(entries)} entries{' DRY' if args.dry else ''}) ===")
        for i, e in enumerate(entries, 1):
            found = already_present(e)
            if found:
                log(fh, f"[{i}/{len(entries)}] {e['id']}: already have -> {found}")
                results.append((e["id"], "have", found))
                continue
            if args.dry:
                res = acquire_ia(sess, e, fh, args.min_text, args.sleep, dry=True)
                log(fh, f"[{i}/{len(entries)}] {e['id']}: DRY {res}")
                results.append((e["id"], res["status"], res.get("source", "")))
                continue
            res = acquire_ia(sess, e, fh, args.min_text, args.sleep)
            tag = res["status"]
            detail = res.get("path") or res.get("detail") or res.get("source", "")
            log(fh, f"[{i}/{len(entries)}] {e['id']}: {tag.upper()} ({detail})"
                   + (f" src={res.get('source','')}" if tag == "acquired" else ""))
            results.append((e["id"], tag, detail))

    acq = [r for r in results if r[1] == "acquired"]
    have = [r for r in results if r[1] == "have"]
    miss = [r for r in results if r[1] in ("not-found", "error")]
    print(f"\n== summary: {len(acq)} acquired, {len(have)} already present, "
          f"{len(miss)} missing ==")
    if miss:
        print("missing ids:", ", ".join(r[0] for r in miss))
    return 0


if __name__ == "__main__":
    sys.exit(main())
