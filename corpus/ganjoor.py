#!/usr/bin/env python
"""Fetch a complete Persian text from ganjoor.net (clean, keyless).

Walks a category tree via the public API and writes every poem's `plainText` to a
single file. Great for the Persian originals (Rumi, Attar, Shabistari, Hafiz…).

    uv run python corpus/ganjoor.py <rootCatId> <outfile>
    # Rumi Masnavi = cat 103, Divan-e Shams = 98, Fihi ma Fihi = 1873
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import requests

API = "https://api.ganjoor.net/api/ganjoor"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def get(s, path):
    return s.get(f"{API}/{path}", timeout=45).json()


def walk(s, cat, out_parts, depth=0):
    title = cat.get("title", "")
    out_parts.append(f"\n\n{'#' * min(depth+1,4)} {title}\n")
    for p in cat.get("poems") or []:
        pid = p.get("id")
        if not pid:
            continue
        try:
            full = get(s, f"poem/{pid}")
            txt = (full.get("plainText") or "").strip()
        except Exception:
            txt = ""
        if txt:
            out_parts.append(f"\n[{p.get('title','')}]\n{txt}")
        time.sleep(0.25)
    for ch in cat.get("children") or []:
        sub = get(s, f"cat/{ch['id']}?poems=true").get("cat", {})
        walk(s, sub, out_parts, depth + 1)


def main(argv):
    if len(argv) < 2:
        print(__doc__); return 1
    root = argv[0]; out = Path(argv[1])
    s = requests.Session(); s.headers.update({"User-Agent": UA})
    cat = get(s, f"cat/{root}?poems=true").get("cat", {})
    parts = [f"# {cat.get('title','')} — ganjoor.net"]
    walk(s, cat, parts)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(parts))
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
