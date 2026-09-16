#!/usr/bin/env python
"""Local HTTP service for the Mentat engine (front-end for the menu-bar app).

Stdlib only — no new deps. Runs a single asyncio loop in a background thread so
the Brain's cached state/connections persist across requests.

Endpoints:
  GET  /status            -> {"ok": true, "model": "...", "library": {...}}
  POST /ask   {"question": "...", "mode": ""}  -> {"status","answer",...}
  POST /index                            -> {"status","stats"}

Usage:  uv run --project . python server.py [--port 8765]
"""
import argparse
import asyncio
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import brain_core as bc

_CITE_RE = re.compile(r"\(([^()\n]{3,90}) · ([^()\n]{1,90})\)")

_loop = asyncio.new_event_loop()
_brain = None
_lock = threading.Lock()


def _start_loop():
    asyncio.set_event_loop(_loop)
    _loop.run_forever()


threading.Thread(target=_start_loop, daemon=True).start()


def _run(coro):
    return asyncio.run_coroutine_threadsafe(coro, _loop).result()


async def _get_brain():
    global _brain
    if _brain is None:
        _brain = bc.Brain()
    return _brain


async def _ask(question, mode=None):
    brain = await _get_brain()
    res = await brain.ask(question, mode=(mode or None), lazy=True)
    answer = res.get("answer") or ""
    cites = [
        {"book": m.group(1).strip(), "loc": m.group(2).strip()}
        for m in _CITE_RE.finditer(answer)
    ]
    # de-dupe, keep order
    seen, uniq = set(), []
    for c in cites:
        key = (c["book"].lower(), c["loc"].lower())
        if key not in seen:
            seen.add(key)
            uniq.append(c)
    return {
        "status": res.get("status"),
        "answer": answer,
        "question": question,
        "citations": uniq,
        "ungrounded": answer.count("⟪"),
        "model": bc.OLLAMA_LLM_MODEL,
    }


async def _status():
    return {
        "ok": True,
        "model": bc.OLLAMA_LLM_MODEL,
        "offline_default": True,
        "kinds": list(getattr(bc, "VALID_MODES", ())),
    }


class _Handler(BaseHTTPRequestHandler):
    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/status"):
            try:
                self._json(_run(_status()))
            except Exception as exc:
                self._json({"error": str(exc)}, 500)
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0") or 0)
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            data = {}
        if self.path.startswith("/ask"):
            try:
                self._json(_run(_ask(str(data.get("question", "")), data.get("mode"))))
            except Exception as exc:
                self._json({"error": str(exc)}, 500)
        else:
            self._json({"error": "not found"}, 404)

    def log_message(self, *args):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), _Handler)
    print(f"Mentat engine listening on http://127.0.0.1:{args.port}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
