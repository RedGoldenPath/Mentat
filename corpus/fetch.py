#!/usr/bin/env python
"""Polite corpus fetcher — reads manifest.jsonl and downloads works into the vault.

Destinations are relative to ~/Everything/mentat/books. Resumable (.part + rename),
1 request/sec (MIA asks Crawl-delay: 1), skips files already present.

    uv run python fetch.py            # everything
    uv run python fetch.py lenin-cw-01 mao-sw-01   # only these ids
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

BOOKS = Path.home() / "Everything" / "mentat" / "books"
HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "manifest.jsonl"
UA = "Mozilla/5.0 (compatible; MentatCorpus/1.0; personal library)"


def load():
    rows = []
    for line in MANIFEST.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(json.loads(line))
    return rows


def fetch(row) -> str:
    dest = BOOKS / row["dest"]
    if dest.exists() and dest.stat().st_size > 0:
        return f"skip (exists): {dest}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    cmd = ["curl", "-sSL", "--fail", "--retry", "3", "--retry-delay", "2",
           "-C", "-", "-A", UA, "-o", str(part), row["url"]]
    proc = subprocess.run(cmd)
    if proc.returncode != 0:
        return f"FAIL ({proc.returncode}): {row['url']}"
    part.rename(dest)
    return f"saved: {dest}  ({dest.stat().st_size/1e6:.1f} MB)"


def main():
    only = set(sys.argv[1:])
    rows = load()
    todo = [r for r in rows if not only or r["id"] in only]
    print(f"{len(todo)} to consider of {len(rows)} in manifest")
    for row in todo:
        print(f"[{row['id']}] {row.get('author','')} — {row.get('work','')}")
        print("   " + fetch(row))
        time.sleep(1.0)


if __name__ == "__main__":
    main()
