#!/usr/bin/env python
"""One-shot live status for the corpus build + index. `uv run python corpus/status.py`."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import time
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
MENTAT = APP.parent
BOOKS = MENTAT / "books"
LOGS = APP / "corpus" / "logs"
LIB = APP / "storage" / "library.db"


def sh(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
    except Exception:
        return ""


def main():
    print("=" * 64)
    print(" MENTAT CORPUS BUILD —", time.strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 64)

    # running jobs
    procs = sh(["pgrep", "-fl", "run_build.py|brain.py index|gutenberg.py"])
    jobs = []
    if "run_build.py" in procs or "run_build" in procs:
        jobs.append("crawl")
    if "brain.py index" in procs:
        jobs.append("index")
    print(" jobs running :", ", ".join(jobs) or "none")

    # crawl driver line
    bl = LOGS / "build.log"
    if bl.exists():
        lines = [l for l in bl.read_text().splitlines() if l.strip()]
        print(" crawl        :", lines[-1][:60] if lines else "—")

    # sections done
    done = [p.parent for p in BOOKS.rglob(".done")]
    print(f" sections done: {len(done)}")

    # totals
    n_files = int(sh(["bash", "-c", f"find '{BOOKS}' -type f | wc -l"]) or 0)
    size = sh(["du", "-sh", str(BOOKS)]).split("\t")[0]
    print(f" files        : {n_files:,}   size: {size}")

    # index
    chunks = 0
    try:
        chunks = sqlite3.connect(f"file:{LIB}?mode=ro", uri=True).execute(
            "SELECT count(*) FROM chunks").fetchone()[0]
    except Exception:
        pass
    idx = 0
    il = LOGS / "index_now.log"
    if il.exists():
        idx = il.read_text().count("\nindexed:")
    print(f" indexed      : {chunks:,} chunks   ({idx} files this run)")

    # per-subject files
    print(" by subject   :")
    for d in sorted(BOOKS.iterdir()):
        if d.is_dir():
            n = int(sh(["bash", "-c", f"find '{d}' -type f | wc -l"]) or 0)
            if n:
                print(f"    {d.name:<20} {n:>7,}")

    # torrent box + VPN
    ip = sh(["bash", "-lc",
             "docker exec mentat-gluetun wget -qO- https://api.ipify.org 2>/dev/null"])
    names = sh(["bash", "-lc", "docker ps --format '{{.Names}}'"])
    qb = "up" if "mentat-qbittorrent" in names else "down"
    ob = "up" if "mentat-openbooks" in names else "down"
    print(f" torrent box  : qbittorrent {qb} · openbooks {ob} · vpn exit {ip or '—'}")

    # book acquisition
    tsv = LOGS / "ebooks_downloads.tsv"
    nd = len([l for l in tsv.read_text().splitlines() if l.strip()]) if tsv.exists() else 0
    rl = int(sh(["bash", "-c",
                 f"find '{BOOKS}/islam/sufism' '{BOOKS}/contemplative' -type f 2>/dev/null | wc -l"]) or 0)
    print(f" ebooks (IRC) : {nd} downloaded · reading-list files: {rl}")


if __name__ == "__main__":
    main()
