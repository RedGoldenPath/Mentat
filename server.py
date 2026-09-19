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
import os
import queue
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import brain_core as bc

_CITE_RE = re.compile(r"\(([^()\n]{3,90}) · ([^()\n]{1,90})\)")

_loop = asyncio.new_event_loop()
_brain = None
_lock = threading.Lock()
_LAST_META = {}

HELP_TEXT = """Mentat commands

  /help                 this list
  /clear                start a new conversation
  /status               what is indexed / pending
  /health               run the subsystem health check
  /verify               run the verification suite (quick)
  /index                index new or changed files
  /search <phrase>      exact full-text search across the library
  /find <words>         fuzzy half-remembered quote hunt
  /graph <name>         entity co-occurrence
  /freq <word|phrase>   exact occurrence count (story vs apparatus)
  /inventory            per-work chunks/chapters/words
  /stats                research diary: questions, spend, kinds
  /served               which model served the last answer (+ cost)
  /history              recent questions
  /remember <fact>      save a fact to permanent memory
  /heal                 self-repair
  /offline [on|off]     local-only mode
  /model [name]         show/set the answer model
  /voice [name]         show/set the writing voice
  /lens [name|--clear]  show/set the persistent lens
  /settings             open settings

Just type a question normally, or a single word for an exact census."""


async def _command(cmd, arg):
    """Run one TUI-style command against the brain; returns {ok, text}."""
    cmd = (cmd or "").strip().lower()
    arg = (arg or "").strip()
    try:
        if cmd == "help":
            return {"ok": True, "text": HELP_TEXT}
        if cmd == "status":
            new, changed, removed, _current = (await _get_brain())._scan_changes()
            manifest = len(bc._load_manifest())
            pending = len(new) + len(changed)
            return {"ok": True, "text": f"indexed documents: {manifest} · pending: {pending}\nvault: {bc.KNOWLEDGE_ROOT}"}
        if cmd == "health":
            results = await (await _get_brain()).health()
            fails = [n for n, ok, _ in results if not ok]
            if fails:
                return {"ok": False, "text": "health failures: " + ", ".join(fails)}
            return {"ok": True, "text": f"health: all {len(results)} checks ok"}
        if cmd == "verify":
            from verify import run_suite
            results = await asyncio.to_thread(run_suite, True, False)
            passed = sum(1 for r in results if r["status"] == "PASS")
            lines = [f"verify (quick): {passed}/{len(results)} passed"]
            for r in results:
                lines.append(f"  [{r['status']}] {r['check']}: {str(r['detail'])[:80]}")
            return {"ok": passed == len(results), "text": "\n".join(lines)}
        if cmd == "graph":
            if not arg:
                return {"ok": False, "text": "usage: /graph <name>"}
            info = bc._graph_related(arg)
            if not info.get("count"):
                return {"ok": False, "text": f"'{arg}' is not in the entity graph"}
            lines = [f"{info['entity']} — {info['count']} chunks"]
            lines += [f"  ~ {name} ({cnt})" for name, cnt in info["related"]]
            lines += [f"  · {book} ({cnt})" for book, cnt in info["books"][:5]]
            return {"ok": True, "text": "\n".join(lines)}
        if cmd == "search":
            if not arg:
                return {"ok": False, "text": "usage: /search <phrase>"}
            results = await asyncio.to_thread((await _get_brain()).search, arg)
            if not results:
                return {"ok": True, "text": f"no exact matches for {arg!r}"}
            lines = [f"{len(results)} match(es) for {arg!r}:"]
            for r in results[:20]:
                lines.append(f"  · {r['source']}: {r['excerpt']}")
            return {"ok": True, "text": "\n".join(lines)}
        if cmd == "freq":
            if not arg:
                return {"ok": False, "text": "usage: /freq <word or phrase>"}
            rows = await asyncio.to_thread(bc._term_frequency, arg)
            hits = [r for r in rows if r["story"] or r["apparatus"]]
            if not hits:
                return {"ok": True, "text": f"no occurrences of {arg!r} in the library"}
            lines = [f"frequency: {arg}", ""]
            total = 0
            for r in hits[:18]:
                suffix = f"  (+{r['apparatus']:,} apparatus)" if r["apparatus"] else ""
                lines.append(f"  {r['work'][:56]:58} story {r['story']:>6,}{suffix}")
                total += r["story"]
            lines += ["", f"{total:,} occurrences in story text"]
            return {"ok": True, "text": "\n".join(lines)}
        if cmd == "inventory":
            data = await asyncio.to_thread(bc._library_profiles)
            rows = data.get("works") or []
            if not rows:
                return {"ok": True, "text": "nothing indexed yet — run /index"}
            t = data.get("totals") or {}
            lines = ["library inventory", ""]
            for w in rows[:22]:
                lines.append(f"  {w['work'][:58]:60} chunks {w['chunks']:>6,} · chapters {w['chapters']:>4,} · words {w['words']:>9,}")
            if len(rows) > 22:
                lines.append(f"  … and {len(rows) - 22} more works")
            lines.append("")
            lines.append(f"totals: {len(rows)} works · {t.get('chunks', 0):,} chunks · {t.get('chapters', 0):,} story chapters · {t.get('apparatus', 0):,} apparatus · {t.get('words', 0):,} words")
            return {"ok": True, "text": "\n".join(lines)}
        if cmd == "stats":
            bc._telemetry_init()
            conn = bc._telemetry_conn()
            import time as _t
            n_asks = conn.execute("SELECT count(*) FROM asks").fetchone()[0]
            day = _t.strftime("%Y-%m-%d")
            today = conn.execute("SELECT coalesce(round(sum(cost_usd), 4), 0) FROM asks WHERE substr(ts, 1, 10) = ?", (day,)).fetchone()[0]
            total = conn.execute("SELECT coalesce(round(sum(cost_usd), 4), 0) FROM asks").fetchone()[0]
            kinds = conn.execute("SELECT kind, count(*) FROM asks WHERE kind IS NOT NULL AND kind != '' GROUP BY kind ORDER BY 2 DESC LIMIT 6").fetchall()
            statuses = conn.execute("SELECT status, count(*) FROM asks GROUP BY status").fetchall()
            signals = conn.execute("SELECT kind, count(*) FROM feedback GROUP BY kind ORDER BY 2 DESC LIMIT 10").fetchall()
            conn.close()
            lines = [
                f"diary — {n_asks} questions · spend today ${today:.4f} · all-time ${total:.4f}",
                "kinds: " + (", ".join(f"{k}:{c}" for k, c in kinds) or "—"),
                "statuses: " + ", ".join(f"{s}:{c}" for s, c in statuses),
                "signals: " + ", ".join(f"{k}:{c}" for k, c in signals),
            ]
            return {"ok": True, "text": "\n".join(lines)}
        if cmd == "history":
            entries = (await _get_brain()).history(limit=10)
            if not entries:
                return {"ok": True, "text": "no history yet."}
            lines = [(e.get("timestamp", "") + "  " + (e.get("question") or "…").replace("\n", " ")[:70]) for e in reversed(entries)]
            return {"ok": True, "text": "recent:\n" + "\n".join(lines)}
        if cmd == "served":
            info = _LAST_META or {}
            if not info.get("model"):
                return {"ok": True, "text": "no answer yet — ask something first"}
            line = (
                f"last answer served by {info.get('model')} — thinking {info.get('t_thinking', 0):.1f}s · "
                f"writing {info.get('t_content', 0):.1f}s · {info.get('tokens_in', 0):,} in / {info.get('tokens_out', 0):,} out"
            )
            if info.get("cost_usd"):
                line += f" · ~${info['cost_usd']:.4f}"
            return {"ok": True, "text": line}
        if cmd == "remember":
            if not arg:
                return {"ok": False, "text": "usage: /remember <fact>"}
            topic = "default"
            if "--topic" in arg:
                arg, _, topic = arg.partition("--topic")
                topic = topic.strip() or "default"
            await (await _get_brain()).remember(arg.strip(), topic=topic)
            return {"ok": True, "text": f"remembered → {topic}"}
        if cmd == "heal":
            result = await bc.self_heal_run(allow_major=False)
            parts = list(result.get("quips") or [])
            for f in result.get("fixed") or []:
                parts.append(f"fixed: {f['issue']} — {f['detail']}")
            for f in result.get("failed") or []:
                parts.append(f"could not fix: {f['issue']} — {f['detail']}")
            for n in result.get("notes") or []:
                parts.append(f"note: {n['issue']} — {n['detail']}")
            for p in result.get("pending") or []:
                parts.append(f"needs your call: {p['issue']} — {p['detail']}")
            if not parts:
                parts = ["all systems whole — nothing to heal"]
            return {"ok": True, "text": "\n".join(parts)}
        if cmd == "offline":
            brain = await _get_brain()
            if arg:
                new = arg.lower() in ("on", "true", "1", "yes")
            else:
                new = not bool(brain.get_settings().get("offline"))
            brain.set_setting("offline", new)
            return {"ok": True, "text": f"offline mode {'on' if new else 'off'}"}
        if cmd == "model":
            brain = await _get_brain()
            if not arg:
                return {"ok": True, "text": "model: " + bc.model_label(brain.get_settings().get("model") or "") + "\noptions: deepseek-flash · deepseek-think · qwen · qwen-deep"}
            res = brain.set_setting("model", arg)
            return {"ok": bool(res.get("ok")), "text": f"answer model → {bc.model_label(arg)}" if res.get("ok") else res.get("reason", "error")}
        if cmd == "voice":
            brain = await _get_brain()
            if not arg:
                return {"ok": True, "text": "voice: " + str(brain.get_settings().get("voice", "default")) + "\noptions: " + " · ".join(bc.VOICE_PRESETS)}
            res = brain.set_setting("voice", arg.lower())
            return {"ok": bool(res.get("ok")), "text": f"voice set to {arg.lower()}" if res.get("ok") else res.get("reason", "error")}
        if cmd == "lens":
            brain = await _get_brain()
            if arg in ("", "--clear", "clear", "off"):
                brain.set_setting("lens", "")
                return {"ok": True, "text": "lens cleared."}
            lens_file = bc.KNOWLEDGE_ROOT / "lenses" / f"{arg}.md"
            content = lens_file.read_text() if lens_file.exists() else arg
            brain.set_setting("lens", content)
            return {"ok": True, "text": f"lens set: {arg}"}
        if cmd == "index":
            stats = await (await _get_brain()).index(verbose=False)
            if stats.get("already_running"):
                return {"ok": True, "text": stats.get("message", "index already running")}
            return {"ok": True, "text": f"index: +{stats.get('indexed', 0)} new, ~{stats.get('updated', 0)} changed, -{stats.get('deleted', 0)} removed ({len(stats.get('errors', []))} errors)"}
        if cmd == "settings":
            return {"ok": True, "text": "\n".join(f"  {k}: {v}" for k, v in (await _get_brain()).get_settings().items())}
        return {"ok": False, "text": f"unknown command: /{cmd} (try /help)"}
    except Exception as exc:
        return {"ok": False, "text": f"/{cmd} failed: {exc}"}


def _settings_payload():
    values = bc._load_settings()
    options = {
        "model": ["deepseek-flash", "deepseek-think", "qwen", "qwen-deep"],
        "voice": list(getattr(bc, "VOICE_PRESETS", {}).keys()),
        "thinking": ["false", "true", "low", "medium", "high"],
        "mode": list(getattr(bc, "VALID_MODES", ("naive", "local", "global", "hybrid", "mix"))),
        "routing": list(getattr(bc, "VALID_ROUTING", ("off", "heuristic", "hybrid"))),
        "search_depth": ["auto", "always", "off"],
        "self_heal": ["off", "detect", "remediate", "full"],
    }
    try:
        options["lens"] = ["- none -"] + sorted(p.stem for p in (bc.KNOWLEDGE_ROOT / "lenses").glob("*.md"))
    except Exception:
        options["lens"] = ["- none -"]
    return {"spec": getattr(bc, "SETTINGS_SPEC", []), "values": values, "options": options}


async def _conversation_turns(conv_id=None):
    brain = await _get_brain()
    if conv_id:
        brain.open_conversation(conv_id)
    rows = brain.history(limit=500)
    out = []
    for e in rows:
        out.append({
            "question": e.get("question") or "",
            "answer": e.get("answer") or "",
            "timestamp": e.get("timestamp") or "",
            "model": e.get("model") or "",
        })
    return out


def _start_loop():
    asyncio.set_event_loop(_loop)
    _loop.run_forever()


threading.Thread(target=_start_loop, daemon=True).start()


def _run(coro):
    return asyncio.run_coroutine_threadsafe(coro, _loop).result()


def _warm_models():
    try:
        bc.warm_models()
    except Exception:
        pass


# Warm the local reranker + index caches off the boot path, so the first
# question is fast without delaying server startup.
threading.Thread(target=_warm_models, daemon=True).start()


async def _get_brain():
    global _brain
    if _brain is None:
        _brain = bc.Brain()
    return _brain


def _citations(answer):
    cites = [
        {"book": m.group(1).strip(), "loc": m.group(2).strip()}
        for m in _CITE_RE.finditer(answer or "")
    ]
    # de-dupe, keep order
    seen, uniq = set(), []
    for c in cites:
        key = (c["book"].lower(), c["loc"].lower())
        if key not in seen:
            seen.add(key)
            uniq.append(c)
    return uniq


async def _ask(question, mode=None):
    brain = await _get_brain()
    res = await brain.ask(question, mode=(mode or None), lazy=True)
    answer = res.get("answer") or ""
    return {
        "status": res.get("status"),
        "answer": answer,
        "question": question,
        "citations": _citations(answer),
        "ungrounded": answer.count("⟪"),
        "model": bc.model_label(bc.effective_synth_model()),
    }


def _stream_ask(question, mode=None):
    """Yield ndjson-serializable dicts from the brain's streaming answer.

    Runs the async generator on the shared event loop and bridges each event
    back to the calling (request) thread through a queue, so tokens reach the
    client as they are produced.
    """
    events = queue.Queue()

    def _progress(msg):
        if isinstance(msg, tuple) and len(msg) == 2 and msg[0] == "think":
            events.put({"t": "think", "v": msg[1]})
        elif isinstance(msg, str) and msg:
            events.put({"t": "progress", "v": msg})

    async def _pump():
        brain = await _get_brain()
        brain._progress = _progress
        sent = 0
        try:
            async for text in brain.ask_stream(question, mode=(mode or None)):
                text = text or ""
                delta = text[sent:]
                sent = len(text)
                if delta:
                    events.put({"t": "chunk", "v": delta})
            res = brain._last_stream_result or {}
            answer = res.get("answer") or ""
            global _LAST_META
            _LAST_META = {
                "model": res.get("served_model") or "",
                "kind": res.get("kind") or "",
                "t_thinking": res.get("t_thinking") or 0.0,
                "t_content": res.get("t_content") or 0.0,
                "tokens_in": res.get("tokens_in") or 0,
                "tokens_out": res.get("tokens_out") or 0,
                "cost_usd": res.get("cost_usd") or 0.0,
                "route_reason": res.get("route_reason") or "",
            }
            events.put({
                "t": "done",
                "answer": answer,
                "citations": _citations(answer),
                "ungrounded": answer.count("⟪"),
                "model": res.get("served_model") or bc.OLLAMA_LLM_MODEL,
                "status": "answered" if answer.strip() else "no_answer",
                "meta": {
                    "kind": res.get("kind") or "",
                    "t_thinking": res.get("t_thinking") or 0.0,
                    "t_content": res.get("t_content") or 0.0,
                    "tokens_in": res.get("tokens_in") or 0,
                    "tokens_out": res.get("tokens_out") or 0,
                    "cost_usd": res.get("cost_usd") or 0.0,
                    "route_reason": res.get("route_reason") or "",
                    "cache_hit_tokens": res.get("cache_hit_tokens") or 0,
                    "cache_miss_tokens": res.get("cache_miss_tokens") or 0,
                },
            })
        except Exception as exc:
            events.put({"t": "error", "v": str(exc)})
        finally:
            brain._progress = None
            events.put(None)

    asyncio.run_coroutine_threadsafe(_pump(), _loop)
    while True:
        item = events.get()
        if item is None:
            return
        yield item


async def _status():
    try:
        model = bc.model_label(bc.effective_synth_model())
        offline = bool(bc._offline())
    except Exception:
        model = bc.OLLAMA_LLM_MODEL
        offline = False
    return {
        "ok": True,
        "model": model,
        "offline": offline,
        "offline_default": offline,
        "kinds": list(getattr(bc, "VALID_MODES", ())),
    }


def _clean_book_title(path):
    """Turn a manifest path into a readable book title."""
    name = os.path.basename(path or "")
    if name.lower().endswith(".epub"):
        name = name[:-5]
    name = re.sub(r"\s*\((?:z-library|1lib|z-lib)[^)]*\)\s*", "", name, flags=re.I)
    return name.strip() or (path or "")


def _load_library_map():
    try:
        with open(bc.STORAGE_DIR / "library_map.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"books": {}}


def _books_list():
    """The indexed books, as cards for the Library shelf."""
    books = (_load_library_map().get("books") or {})
    out = []
    for path, b in books.items():
        parts = path.split("/")
        series = parts[-2] if len(parts) >= 3 else ""
        out.append({
            "id": b.get("digest") or path,
            "title": _clean_book_title(path),
            "series": series,
            "summary": b.get("summary") or "",
            "concepts": b.get("concepts") or [],
        })
    out.sort(key=lambda x: (x.get("series") or "", x.get("title") or ""))
    return {"books": out}


def _book_detail(bid):
    books = (_load_library_map().get("books") or {})
    for path, b in books.items():
        if (b.get("digest") or path) == bid:
            return {
                "id": bid,
                "title": _clean_book_title(path),
                "summary": b.get("summary") or "",
                "concepts": b.get("concepts") or [],
                "excerpts": b.get("concept_excerpts") or [],
            }
    return {"id": bid, "title": "", "summary": "", "concepts": [], "excerpts": []}


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _chunk(self, data):
        self.wfile.write(f"{len(data):X}\r\n".encode("ascii"))
        self.wfile.write(data)
        self.wfile.write(b"\r\n")
        self.wfile.flush()

    def _stream(self, question, mode):
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            for event in _stream_ask(str(question), mode):
                line = json.dumps(event, ensure_ascii=False).encode("utf-8") + b"\n"
                self._chunk(line)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:
            try:
                self._chunk(
                    json.dumps({"t": "error", "v": str(exc)}, ensure_ascii=False).encode("utf-8") + b"\n"
                )
            except Exception:
                return
        try:
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except Exception:
            pass

    def _query(self):
        q = {}
        if "?" in self.path:
            from urllib.parse import parse_qs
            q = {k: v[0] for k, v in parse_qs(self.path.split("?", 1)[1]).items()}
        return q

    def do_GET(self):
        try:
            if self.path.startswith("/status"):
                self._json(_run(_status()))
            elif self.path.startswith("/settings"):
                self._json(_settings_payload())
            elif self.path.startswith("/conversations"):
                brain = _run(_get_brain())
                self._json({"conversations": brain.conversations()})
            elif self.path.startswith("/books"):
                self._json(_books_list())
            elif self.path.startswith("/book"):
                q = self._query()
                self._json(_book_detail(q.get("id") or ""))
            elif self.path.startswith("/conversation"):
                q = self._query()
                self._json({"turns": _run(_conversation_turns(q.get("id") or None))})
            elif self.path.startswith("/passage"):
                q = self._query()
                source = bc._passage_source(
                    q.get("book") or "", q.get("loc") or "", q.get("hint") or ""
                )
                self._json(source or {"error": "passage not found"})
            else:
                self._json({"error": "not found"}, 404)
        except Exception as exc:
            self._json({"error": str(exc)}, 500)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0") or 0)
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            data = {}
        try:
            if self.path.startswith("/ask/stream"):
                self._stream(data.get("question", ""), data.get("mode"))
            elif self.path.startswith("/command"):
                self._json(_run(_command(data.get("cmd", ""), data.get("arg", ""))))
            elif self.path.startswith("/settings"):
                brain = _run(_get_brain())
                self._json(brain.set_setting(data.get("key", ""), data.get("value", "")))
            elif self.path.startswith("/conversation/open"):
                brain = _run(_get_brain())
                brain.open_conversation(data.get("id", ""))
                self._json({"ok": True})
            elif self.path.startswith("/conversation/new"):
                brain = _run(_get_brain())
                brain.new_conversation()
                self._json({"ok": True})
            elif self.path.startswith("/conversation/delete"):
                brain = _run(_get_brain())
                removed = brain.delete_conversation(data.get("id", ""))
                self._json({"ok": True, "removed": removed})
            elif self.path.startswith("/ask"):
                self._json(_run(_ask(str(data.get("question", "")), data.get("mode"))))
            else:
                self._json({"error": "not found"}, 404)
        except Exception as exc:
            self._json({"error": str(exc)}, 500)

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
