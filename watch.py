#!/usr/bin/env python
"""Vault watcher — index documents the moment they land.

Event-driven only: watches KNOWLEDGE_ROOT with macOS FSEvents (via `watchdog`) and,
when a supported document is created, changed or removed, waits for the copy to
settle, then runs the same indexer the CLI uses (`brain.py index`). No timers, no
periodic sweeps — when nothing is happening it does nothing.

    uv run python watch.py            # foreground (for testing)
    brain watch on                    # background launchd agent  ·  brain watch off

Mirrors the reconcile model used by DEVONthink / Dropbox / Spotlight: an OS file
event triggers a scan, and the manifest ledger (`brain_core._scan_changes`) dedupes
new vs changed vs removed — so an event only ever needs to say "something landed".
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

APP = Path(__file__).resolve().parent
sys.path.insert(0, str(APP))

from brain_core import (  # noqa: E402
    APP_DIR_NAME,
    KNOWLEDGE_ROOT,
    SKIP_SUFFIXES,
    _index_is_running,
)

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
except Exception as exc:  # pragma: no cover
    print(f"watchdog is not installed ({exc}). Run: uv add watchdog", flush=True)
    raise SystemExit(3)

UV_BIN = "/Users/raphael/.local/bin/uv"

# Extensions the indexer can actually extract text from (`brain_core.extract_text`).
INDEXABLE = {".txt", ".md", ".markdown", ".rst", ".html", ".htm", ".pdf", ".epub", ".docx"}
IGNORE_DIRS = {APP_DIR_NAME, "__pycache__", "_catalog"}
# Mentat's own generated artifacts — indexing output must never re-trigger a run.
IGNORE_FILES = {"CORPUS.md", "SOURCES.md", "WANTED.md"}
IGNORE_SUFFIXES = set(SKIP_SUFFIXES) | {".log"}

# Background indexing is throttled so a bulk backlog stays quiet (no fan spin).
# A foreground `brain index` ignores these and stays full speed.
_TASKPOLICY = shutil.which("taskpolicy")
_THROTTLE_ENV = {
    "MENTAT_EMBED_CONCURRENCY": os.getenv("MENTAT_WATCH_EMBED_CONCURRENCY", "1"),
    "MENTAT_EMBED_BATCH": os.getenv("MENTAT_WATCH_EMBED_BATCH", "8"),
    "MENTAT_INDEX_BATCH": os.getenv("MENTAT_WATCH_INDEX_BATCH", "4"),
    "MENTAT_INDEX_SLEEP": os.getenv("MENTAT_WATCH_INDEX_SLEEP", "2.0"),
    "MENTAT_INDEX_MAX_FILES": os.getenv("MENTAT_WATCH_INDEX_MAX_FILES", "25"),
}

DEBOUNCE_DEFAULT = 3.0
_MISSING = object()


def _log(message: str) -> None:
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)


def _indexable(path: Path, root: Path) -> bool:
    """True for a document under the vault that the indexer can parse."""
    try:
        rel = Path(path).resolve().relative_to(Path(root).resolve())
    except (ValueError, OSError):
        return False
    parts = rel.parts
    if not parts:
        return False
    if path.name in IGNORE_FILES:
        return False
    for part in parts:
        if part.startswith(".") or part in IGNORE_DIRS:
            return False
    suffix = path.suffix.lower()
    if suffix in IGNORE_SUFFIXES or suffix not in INDEXABLE:
        return False
    return True


class _Handler(FileSystemEventHandler):
    def __init__(self, watcher: "Watcher") -> None:
        self.watcher = watcher

    def on_created(self, event) -> None:
        if not event.is_directory:
            self.watcher.consider(event.src_path)

    def on_modified(self, event) -> None:
        if not event.is_directory:
            self.watcher.consider(event.src_path)

    def on_moved(self, event) -> None:
        if not event.is_directory:
            self.watcher.consider(event.dest_path)

    def on_deleted(self, event) -> None:
        if not event.is_directory:
            self.watcher.consider(event.src_path)


class Watcher:
    def __init__(self, root: Path, debounce: float = DEBOUNCE_DEFAULT, once: bool = False) -> None:
        self.root = Path(root)
        self.debounce = max(0.5, float(debounce))
        self.once = once
        self._lock = threading.Lock()
        self._pending: set[str] = set()
        self._snap: dict[str, object] = {}
        self._wake = threading.Event()
        self._waiting_logged = False

    def consider(self, raw_path: str) -> None:
        path = Path(raw_path)
        if not _indexable(path, self.root):
            return
        key = str(path)
        with self._lock:
            first = key not in self._pending
            self._pending.add(key)
            if first:
                try:
                    st = path.stat()
                    self._snap[key] = (st.st_size, st.st_mtime_ns)
                except OSError:
                    self._snap[key] = None
        self._wake.set()

    def _stable(self) -> bool:
        with self._lock:
            keys = list(self._pending)
        changed = False
        for key in keys:
            try:
                st = Path(key).stat()
                current: object = (st.st_size, st.st_mtime_ns)
            except OSError:
                current = None
            with self._lock:
                if self._snap.get(key, _MISSING) != current:
                    self._snap[key] = current
                    changed = True
        return not changed

    def _settle(self) -> None:
        """Wait until the burst stops: no new events for `debounce` and files stable."""
        while True:
            time.sleep(self.debounce)
            with self._lock:
                new_events = self._wake.is_set()
                self._wake.clear()
            if new_events:
                continue
            if not self._stable():
                continue
            return

    def _take(self) -> list[str]:
        with self._lock:
            paths = sorted(self._pending)
            self._pending.clear()
            self._snap.clear()
            self._wake.clear()
        return paths

    def _run_indexer(self) -> None:
        _log("indexing… (background, throttled)")
        env = {**os.environ, **_THROTTLE_ENV}
        cmd = [UV_BIN, "run", "python", "brain.py", "index"]
        if _TASKPOLICY:
            # Run on efficiency cores so a bulk index never spins up the fans.
            cmd = [_TASKPOLICY, "-b", *cmd]
        try:
            proc = subprocess.run(cmd, cwd=str(APP), env=env)
            _log(f"indexer finished (exit {proc.returncode})")
        except Exception as exc:
            _log(f"indexer failed to start: {exc}")

    def run(self) -> None:
        observer = Observer()
        observer.schedule(_Handler(self), str(self.root), recursive=True)
        observer.start()
        _log(f"watching {self.root} · debounce {self.debounce:g}s · event-driven (no sweeps)")
        try:
            while True:
                self._wake.wait()
                self._settle()
                paths = self._take()
                if not paths:
                    continue
                names = ", ".join(Path(p).name for p in paths[:4])
                extra = "" if len(paths) <= 4 else f" (+{len(paths) - 4} more)"
                _log(f"{len(paths)} change(s): {names}{extra}")
                if _index_is_running():
                    if not self._waiting_logged:
                        _log("an index run is active — will re-run once it finishes")
                        self._waiting_logged = True
                    for path in paths:
                        self.consider(path)
                    time.sleep(5)
                    continue
                self._waiting_logged = False
                self._run_indexer()
                if self.once:
                    break
        except KeyboardInterrupt:
            _log("stopping")
        finally:
            observer.stop()
            observer.join()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="watch", description="Index vault files as they land (event-driven)."
    )
    parser.add_argument("--debounce", type=float, default=DEBOUNCE_DEFAULT,
                        help="quiet seconds after a copy before indexing (default 3)")
    parser.add_argument("--once", action="store_true", help="index once, then exit")
    args = parser.parse_args(argv)

    if not KNOWLEDGE_ROOT.exists():
        _log(f"vault not found: {KNOWLEDGE_ROOT}")
        return 1
    Watcher(KNOWLEDGE_ROOT, args.debounce, once=args.once).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
