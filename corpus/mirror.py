#!/usr/bin/env python
"""Polite but PARALLEL MIA/text mirrorer — crawl a section, save CLEAN text.

Fetches WORKERS pages at once (default 3) with a short delay, extracts the article
body with trafilatura into Markdown, and downloads PDF/EPUB/DOCX as-is. Writes a
`.done` marker on completion so the driver can skip finished sections. Resumable:
existing files are skipped.

Env: MIRROR_WORKERS (default 3), MIRROR_DELAY (default 0.4)

    uv run python mirror.py --root URL --dest DIR --name NAME [--max N]
"""
from __future__ import annotations

import argparse
import os
import re
import time
import urllib.parse
import urllib.request
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import trafilatura
from lxml import html as lxml_html

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
SKIP = ("/admin/", "/cgi-bin/", "/errors/", "/webstats/")
BINARY = (".pdf", ".epub", ".docx", ".doc", ".mobi")
WORKERS = int(os.environ.get("MIRROR_WORKERS", "3"))
DELAY = float(os.environ.get("MIRROR_DELAY", "0.4"))


def fetch(url: str):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
        with urllib.request.urlopen(req, timeout=45) as r:
            return r.headers.get("Content-Type", ""), r.read(), None
    except Exception as e:
        return "", b"", str(e)


def slug(url: str) -> str:
    p = re.sub(r"\.(html?|xhtml)$", "", urllib.parse.urlparse(url).path, flags=re.I).strip("/")
    return re.sub(r"[^A-Za-z0-9._/-]+", "_", p).replace("/", "__") or "index"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--dest", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--max", type=int, default=9000)
    ap.add_argument("--depth", type=int, default=8)
    args = ap.parse_args()

    dest = Path(args.dest).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    host = urllib.parse.urlparse(args.root).netloc
    prefix = urllib.parse.urlparse(args.root).path.rsplit("/", 1)[0] + "/"

    frontier = deque([(args.root, 0)])
    seen = set()
    n_pages = n_saved = n_bin = n_err = 0
    t0 = time.time()

    def work(items):
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            return list(ex.map(lambda ud: (ud[0], ud[1], *fetch(ud[0])), items))

    while frontier and n_pages < args.max:
        batch = []
        while frontier and len(batch) < WORKERS and n_pages + len(batch) < args.max:
            url, depth = frontier.popleft()
            if url in seen:
                continue
            seen.add(url)
            if any(s in urllib.parse.urlparse(url).path for s in SKIP):
                continue
            batch.append((url, depth))
        if not batch:
            continue
        for url, depth, ctype, body, err in work(batch):
            n_pages += 1
            if err:
                n_err += 1
                continue
            low = url.lower()
            if any(low.endswith(x) for x in BINARY):
                out = dest / slug(url).split("__")[-1]
                if not out.exists():
                    out.write_bytes(body)
                    n_bin += 1
            elif "html" in ctype or low.endswith((".htm", ".html")):
                text = trafilatura.extract(body.decode("utf-8", "ignore"),
                                           output_format="markdown", include_comments=False)
                if text and len(text) >= 500:
                    out = dest / (slug(url) + ".md")
                    if not out.exists():
                        out.write_text(text)
                        n_saved += 1
                        if n_saved % 100 == 0:
                            print(f"  · {n_saved} works · {n_pages} fetched · {time.time()-t0:.0f}s",
                                  flush=True)
                if depth < args.depth:
                    try:
                        doc = lxml_html.document_fromstring(body)
                        for raw in doc.xpath("//@href"):
                            href = urllib.parse.urljoin(url, raw)
                            h = urllib.parse.urlparse(href)
                            if h.netloc == host and h.path.startswith(prefix):
                                frontier.append((href.split("#")[0], depth + 1))
                    except Exception:
                        pass
        time.sleep(DELAY)

    if n_saved > 0:
        (dest / ".done").write_text(time.strftime("%Y-%m-%d %H:%M:%S"))
    print(f"[{args.name}] done: {n_saved} works, {n_bin} binaries, {n_pages} pages, "
          f"{n_err} errors, {time.time()-t0:.0f}s -> {dest}", flush=True)


if __name__ == "__main__":
    main()
