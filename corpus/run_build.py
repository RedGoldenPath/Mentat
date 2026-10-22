#!/usr/bin/env python
"""Sequential driver for the MIA canon build. Runs each root in roots.json one at
a time (so MIA sees ~1 req/s globally), logging per-section. Resumable: mirror.py
skips files already written, so re-running continues where it left off.

    uv run python corpus/run_build.py [name ...]    # all, or just these names
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BOOKS = Path.home() / "Everything" / "mentat" / "books"
LOGDIR = HERE / "logs"


def main():
    roots_file = HERE / os.environ.get("ROOTS", "roots.json")
    rows = json.loads(roots_file.read_text())
    only = set(sys.argv[1:])
    if only:
        rows = [r for r in rows if r["name"] in only]
    LOGDIR.mkdir(exist_ok=True)
    t0 = time.time()
    for i, r in enumerate(rows, 1):
        dest = BOOKS / r["dest"]
        if (dest / ".done").exists():
            print(f"[{i}/{len(rows)}] {r['name']} — SKIP (done)", flush=True)
            continue
        log = LOGDIR / f"{r['name']}.log"
        print(f"[{i}/{len(rows)}] {r['name']} -> {dest}", flush=True)
        cmd = [sys.executable, str(HERE / "mirror.py"),
               "--root", r["root"], "--dest", str(dest), "--name", r["name"],
               "--max", str(r["max"])]
        with open(log, "a") as f:
            f.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
            subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT)
    print(f"ALL DONE in {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
