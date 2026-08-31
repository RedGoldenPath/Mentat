import json
import math
import os
import re
import sys
import time

from brain_core import Brain, KNOWLEDGE_ROOT, CHUNK_TOKEN_SIZE, extract_text
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STORAGE = ROOT / "storage"
LOG = ROOT / "index_run.log"
SPIN = "|/-\\"


def _count(name):
    try:
        return len(json.load(open(STORAGE / name, encoding="utf-8")))
    except Exception:
        return None


def _est_chunks(path):
    try:
        text = extract_text(path)
    except Exception:
        return 0
    tokens = max(len(text) // 4, 1)
    return max(math.ceil(tokens / CHUNK_TOKEN_SIZE), 1)


def main():
    brain = Brain()
    new_files, changed_files, removed, current = brain._scan_changes()
    work = sorted(new_files + changed_files, key=lambda p: str(p.relative_to(KNOWLEDGE_ROOT)))
    total = sum(_est_chunks(p) for p in work)
    rels = [str(p.relative_to(KNOWLEDGE_ROOT)) for p in work]
    print(f"estimating ~{total} chunks across {len(work)} file(s)", flush=True)

    last_docs = last_chunks = last_entities = None
    ticks = 0
    try:
        while True:
            docs = _count("kv_store_full_docs.json")
            chunks = _count("kv_store_text_chunks.json")
            entities = _count("kv_store_full_entities.json")
            relations = _count("kv_store_full_relations.json")

            procs = os.popen("pgrep -f 'brain.py index'").read().split()
            own = {str(os.getpid()), str(os.getppid())}
            running = any(p not in own for p in procs)

            pct = int(min(chunks, total) * 100 / max(total, 1)) if chunks is not None else 0
            pct = min(pct, 99) if running else min(pct, 100)

            if (docs, chunks, entities) != (last_docs, last_chunks, last_entities):
                last_docs, last_chunks, last_entities = docs, chunks, entities
            line = (
                f"\r[{SPIN[ticks % 4]}] {pct:>3}%"
                f" · chunks {chunks or 0}/{total}"
                f" · docs {docs or 0} · entities {entities or 0}"
                f" · relations {relations or 0}   "
            )
            sys.stdout.write(line)
            sys.stdout.flush()
            ticks += 1

            if not running:
                sys.stdout.write("\n")
                if chunks and chunks >= total:
                    print("index complete ✔")
                else:
                    print("index process finished (check log)")
                return
            time.sleep(1)
    except KeyboardInterrupt:
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()
