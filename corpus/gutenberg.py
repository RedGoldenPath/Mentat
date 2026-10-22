#!/usr/bin/env python
"""Project Gutenberg harvester — PD texts by search query into the vault taxonomy.

For each job (subject → dest + queries), searches Gutenberg and downloads the EPUB
of each hit into the destination, skipping ones already present. Politeness: 1 s
between downloads. English + original-language works both land.

    uv run python corpus/gutenberg.py [jobname ...]
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
BOOKS = Path.home() / "Everything" / "mentat" / "books"
LOGDIR = HERE / "logs"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def search(query: str, pages: int = 2):
    ids = []
    for page in range(1, pages + 1):
        url = ("https://www.gutenberg.org/ebooks/search/?query="
               + urllib.parse.quote(query) + f"&page={page}")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            html = urllib.request.urlopen(req, timeout=45).read().decode("utf-8", "ignore")
        except Exception as e:
            print(f"  ! search '{query}': {e}", flush=True)
            return ids
        found = re.findall(r"/ebooks/(\d+)", html)
        if not found:
            break
        ids += found
        time.sleep(1)
    return sorted(set(ids))


def download(eid: str, dest: Path) -> str:
    out = dest / f"gutenberg-{eid}.epub"
    if out.exists() and out.stat().st_size > 1000:
        return "skip"
    url = f"https://www.gutenberg.org/ebooks/{eid}.epub.noimages"
    subprocess.run(["curl", "-sL", "--fail", "-A", UA, "-o", str(out), url])
    if out.exists() and out.stat().st_size > 1000:
        return f"ok ({out.stat().st_size // 1024} KB)"
    if out.exists():
        out.unlink()
    return "fail"


def main():
    jobs = json.loads((HERE / "gutenberg.json").read_text())
    only = set(sys.argv[1:])
    if only:
        jobs = [j for j in jobs if j["name"] in only]
    LOGDIR.mkdir(exist_ok=True)
    per = int(os.environ.get("PER_QUERY", "15"))
    for job in jobs:
        dest = BOOKS / job["dest"]
        dest.mkdir(parents=True, exist_ok=True)
        log = LOGDIR / f"gutenberg-{job['name']}.log"
        with open(log, "a") as f:
            f.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} {job['name']} ===\n")
        print(f"[{job['name']}] -> {dest}", flush=True)
        for q in job["queries"]:
            ids = search(q)
            print(f"[{job['name']}] '{q}' -> {len(ids)} hits", flush=True)
            for eid in ids[:per]:
                r = download(eid, dest)
                print(f"   {eid}: {r}", flush=True)
                with open(log, "a") as f:
                    f.write(f"{q}\t{eid}\t{r}\n")
                time.sleep(1)


if __name__ == "__main__":
    main()
