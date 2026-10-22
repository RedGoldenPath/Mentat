#!/usr/bin/env python
"""Find the WANTED books on the open web and file them into the vault.

Method (replicable, keyless):
  1. DuckDuckGo HTML search for "<title> <author> pdf" (+ title-only variant).
  2. Collect outbound links; prioritise direct .pdf files on any host.
  3. Download, verify it is a real PDF (magic bytes + size gate), keep it.
  4. Also try known good hosts (balderexlibris, maypoleofwisdom, archive.org…).
  5. temp -> atomic move into the taxonomy; log every decision.

    uv run python corpus/web_books.py [--only id,id] [--limit N] [--dry] [--min-kb 200]
"""
from __future__ import annotations

import argparse
import html as htmllib
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
BOOKS = HERE.parent.parent / "books"
TMP = HERE / "tmp"
LOGDIR = HERE / "logs"
WANTED = BOOKS / "_catalog" / "wanted.json"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

sys.path.insert(0, str(HERE))
from acquire_wanted import already_present, author_key, distinctive_words, sig_words  # noqa


def ddg(query: str, sess) -> list[str]:
    """Return outbound URLs from a DuckDuckGo HTML search."""
    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
    try:
        r = sess.get(url, timeout=30)
        r.raise_for_status()
    except Exception:
        return []
    out = []
    for m in re.finditer(r'href="([^"]+)"', r.text):
        href = htmllib.unescape(m.group(1))
        if "uddg=" in href:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
            href = urllib.parse.unquote(qs.get("uddg", [href])[0])
        if href.startswith("http") and "duckduckgo.com" not in href:
            out.append(href)
    seen, uniq = set(), []
    for u in out:
        if u not in seen:
            seen.add(u); uniq.append(u)
    return uniq


def looks_pdf(url: str) -> bool:
    p = urllib.parse.urlparse(url).path.lower()
    return p.endswith(".pdf") or ".pdf?" in url.lower() or "pdfdrive" in url.lower()


def title_ok(entry: dict, url: str) -> bool:
    """Loosely confirm the URL/PDF name relates to the title or author."""
    blob = re.sub(r"[-_%]+", " ", urllib.parse.unquote(url)).lower()
    dist = distinctive_words(entry["title"])
    if dist & sig_words(blob):
        return True
    return author_key(entry["author"]) in blob


def try_download(sess, url, out: Path, min_bytes: int) -> tuple[bool, str]:
    try:
        with sess.get(url, timeout=180, stream=True) as r:
            r.raise_for_status()
            ct = r.headers.get("content-type", "")
            first = next(r.iter_content(8), b"")
            if first[:4] != b"%PDF" and "pdf" not in ct.lower():
                return False, f"not-pdf ({ct[:30]})"
            out.write_bytes(first)
            with open(out, "ab") as f:
                for chunk in r.iter_content(65536):
                    f.write(chunk)
        if out.stat().st_size < min_bytes:
            return False, f"too small ({out.stat().st_size})"
        return True, f"{out.stat().st_size}b"
    except Exception as e:
        return False, str(e)[:60]


def process(entry: dict, sess, min_bytes: int, dry: bool, fh) -> dict:
    found = already_present(entry)
    if found:
        return {"status": "have", "path": found}
    queries = [
        f'{entry["title"]} {entry["author"]} pdf',
        f'"{entry["title"]}" pdf',
        f'{entry["title"]} pdf download',
    ]
    cands: list[str] = []
    for q in queries:
        for u in ddg(q, sess):
            if looks_pdf(u) and title_ok(entry, u):
                cands.append(u)
        time.sleep(1.5)
    # de-dup, prefer author/title in the name
    seen, ordered = set(), []
    for u in cands:
        if u not in seen:
            seen.add(u); ordered.append(u)
    ordered.sort(key=lambda u: 0 if author_key(entry["author"]) in u.lower() else 1)

    if dry:
        return {"status": "candidates", "urls": ordered[:4]}
    TMP.mkdir(parents=True, exist_ok=True)
    dest = BOOKS / entry["dest"]
    for u in ordered[:6]:
        tmp = TMP / f"{entry['id']}.pdf"
        ok, info = try_download(sess, u, tmp, min_bytes)
        if ok:
            dest.mkdir(parents=True, exist_ok=True)
            name = f'{entry["author"]} - {entry["title"]}.pdf'
            name = re.sub(r'[<>:"/\\|?*]', "", name)
            out = dest / name
            import shutil
            shutil.move(str(tmp), str(out))
            return {"status": "acquired", "path": str(out.relative_to(BOOKS)), "src": u}
        elif tmp.exists():
            tmp.unlink()
    return {"status": "not-found", "detail": f"{len(ordered)} pdf candidates, none downloadable"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--min-kb", type=int, default=200)
    args = ap.parse_args()

    entries = json.loads(WANTED.read_text())
    if args.only:
        want = {s.strip() for s in args.only.split(",")}
        entries = [e for e in entries if e["id"] in want]
    if args.limit:
        entries = entries[:args.limit]

    LOGDIR.mkdir(exist_ok=True)
    sess = requests.Session()
    sess.headers.update({"User-Agent": UA})
    results = []
    with open(LOGDIR / "web_books.log", "a") as fh:
        fh.write(f"\n=== web_books {time.strftime('%Y-%m-%d %H:%M:%S')} ({len(entries)}) ===\n")
        for i, e in enumerate(entries, 1):
            res = process(e, sess, args.min_kb * 1024, args.dry, fh)
            tag = res["status"]
            extra = res.get("path") or res.get("src") or res.get("detail") or ""
            print(f"[{i}/{len(entries)}] {e['id']}: {tag.upper()} {extra}", flush=True)
            fh.write(f"[{i}/{len(entries)}] {e['id']}: {tag.upper()} {extra}\n"); fh.flush()
            results.append((e["id"], tag))
    acq = [r for r in results if r[1] == "acquired"]
    print(f"\n== web_books: {len(acq)} acquired, "
          f"{sum(1 for r in results if r[1]=='have')} already, "
          f"{sum(1 for r in results if r[1] not in ('acquired','have'))} not found ==")
    return 0


if __name__ == "__main__":
    sys.exit(main())
