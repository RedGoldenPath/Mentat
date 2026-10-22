#!/usr/bin/env python
"""Books inbox — auto-file downloaded books into the Mentat library.

Watches ~/Downloads and ~/Books-inbox/ for new book files and moves them into the
right taxonomy folder (heuristic by filename); unmatched ones go to books/_incoming/.
The vault watcher then indexes anything landing under books/.

    uv run python corpus/books_inbox.py            # run in foreground
    uv run python corpus/books_inbox.py --once      # one scan, then exit
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

WATCH = [Path.home() / "Downloads", Path.home() / "Books-inbox"]
BOOKS = Path.home() / "Everything" / "mentat" / "books"
INCOMING = BOOKS / "_incoming"
LOG = Path(__file__).resolve().parent / "logs" / "books_inbox.log"

EBOOK_EXTS = {".epub", ".mobi", ".azw3", ".djvu", ".fb2", ".cbz", ".azw"}
PDF = ".pdf"
ALL_EXTS = EBOOK_EXTS | {PDF}

# filename keyword -> destination (relative to books/); first match wins
ROUTES = [
    (["ibn arabi", "ibn 'arabi", "ibn al-arabi", "akbarian", "chodkiewicz", "chittick",
      "addas", "hirtenstein", "knysh", "shah-kazemi", "liton", "murata", "izutsu"],
     "islam/sufism/ibn-arabi"),
    (["rumi", "masnavi", "mathnawi", "ghazali", "ghazzali", "attar", "shabistari", "sufi",
      "sufism", "tasawwuf", "hallaj", "qushayri", "hujwiri", "jami", "maarif"],
     "islam/sufism"),
    (["quran", "koran", "qur'an", "tafsir", "hadith", "bukhari", "sahih", "muslim hadith"],
     "islam/quran-hadith"),
    (["shia", "shi'i", "shiite", "nahj", "al-kafi", "mulla sadra", "tabataba", "motahhari",
      "baqir al-sadr", "khomeni", "khomeini"], "islam/shia"),
    (["nasr", "schuon", "burckhardt", "martin lings", "perennial", "guenon", "guénon",
      "coomaraswamy", "traditionalis", "evola"], "contemplative/perennialism"),
    (["marx", "engels", "lenin", "stalin", "mao", "gramsci", "luxemburg", "bukharin",
      "kollontai", "dimitrov", "togliatti", "foster", "ho chi minh", "guevara", "castro",
      "hoxha", "kim il", "zhdanov"], "marxism-leninism"),
    (["aquinas", "augustine", "patristic", "catholic", "vatican", "balthasar", "congar",
      "de lubac", "gilson", "maritain", "dante", "trent", "thomis"], "christianity"),
    (["kojeve", "hegel", "kant", "nietzsche"], "philosophy"),
]


def route(name: str) -> str | None:
    low = name.lower()
    for keys, dest in ROUTES:
        if any(k in low for k in keys):
            return dest
    return None


def log(msg: str):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def place(path: Path, src: str):
    dest_rel = route(path.name)
    ext = path.suffix.lower()
    if dest_rel:
        dest = BOOKS / dest_rel / path.name
    elif ext in EBOOK_EXTS:
        dest = INCOMING / path.name
    elif src == "Books-inbox":
        dest = INCOMING / path.name  # dedicated inbox: keep everything
    else:
        return  # unmatched PDF in Downloads: leave it alone
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest = dest.with_name(f"{dest.stem} ({int(time.time())}){dest.suffix}")
    shutil.move(str(path), str(dest))
    log(f"{src}: {path.name} -> {dest.relative_to(BOOKS)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--min-age", type=float, default=20)
    ap.add_argument("--debounce", type=float, default=10)
    args = ap.parse_args()
    INCOMING.mkdir(parents=True, exist_ok=True)
    (Path.home() / "Books-inbox").mkdir(exist_ok=True)
    snap: dict[str, tuple[int, int]] = {}
    log(f"books inbox watching: {', '.join(str(w) for w in WATCH)}")
    while True:
        for watch in WATCH:
            if not watch.exists():
                continue
            for p in watch.iterdir():
                if not p.is_file() or p.suffix.lower() not in ALL_EXTS or p.name.startswith("."):
                    continue
                try:
                    st = p.stat()
                except OSError:
                    continue
                if time.time() - st.st_mtime < args.min_age:
                    continue
                key = str(p)
                cur = (st.st_size, st.st_mtime_ns)
                if snap.get(key) == cur:  # stable across two scans -> done copying
                    src = watch.name
                    try:
                        place(p, src)
                    except Exception as e:
                        log(f"error moving {p.name}: {e}")
                    snap.pop(key, None)
                else:
                    snap[key] = cur
        if args.once:
            break
        time.sleep(args.debounce)


if __name__ == "__main__":
    main()
