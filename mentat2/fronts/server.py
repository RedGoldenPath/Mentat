"""Mentat v2 HTTP front-end — the app's engine.

Serves the Mentat app wire contract on 127.0.0.1:8765 (see
MentatApp/Sources/MentatApp/Engine/{MentatClient,Models,EngineProcess}.swift):

  GET  /status · /stats · /conversations · /conversation?id · /books · /book?id
       /passage?book&loc&hint · /settings
  POST /ask · /ask/stream (ndjson) · /command · /settings
       /conversation/open · /conversation/new · /conversation/delete

Stdlib only. No model call happens on any route except /ask and /ask/stream.
"""
from __future__ import annotations
import atexit
import glob
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from mentat2 import config, telemetry, store, retrieve, gateway  # noqa: E402
from mentat2.pipeline import ask, ask_stream, citations_of  # noqa: E402
import mentat2  # noqa: E402

PIDFILE = config.V2_DATA / "engine.pid"
_SERVER = None
# A stable id for the running engine *code* (git hash + newest mentat2/*.py mtime), so a
# client can tell a stale process from a current one (gunicorn/systemd-style handshake).
_CODE = None


def code_id():
    global _CODE
    if _CODE is None:
        repo = Path(__file__).resolve().parents[2]
        h = ""
        try:
            h = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
                               capture_output=True, text=True, timeout=5).stdout.strip()
        except Exception:
            h = ""
        mt = max((os.path.getmtime(p) for p in
                  glob.glob(str(repo / "mentat2" / "**" / "*.py"), recursive=True)), default=0)
        _CODE = f"{h or 'nogit'}-{int(mt)}"
    return _CODE


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def reap_stale():
    """Terminate the engine recorded in the pidfile, if any, so a fresh start always wins
    (a new launch must run the current code, never a reused stale process)."""
    try:
        pid = int(PIDFILE.read_text().strip())
    except Exception:
        return
    if pid and pid != os.getpid() and _pid_alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        for _ in range(24):            # wait up to ~6s for the port to free
            if not _pid_alive(pid):
                break
            time.sleep(0.25)
    try:
        PIDFILE.unlink()
    except Exception:
        pass


def _settings():
    return config.load_settings()


# ---- conversations (persisted sessions) -----------------------------------

def _iso(ts):
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(ts)))
    except Exception:
        return ""


def conversations():
    out = []
    for r in store.list_conversations(100):
        first = r.get("first_q") or ""
        title = (r.get("title") or "").strip()
        out.append({"conv": r["id"], "count": int(r.get("cnt") or 0),
                    "last_ts": _iso(r.get("updated")),
                    "summary": title or first[:80], "question": first})
    return out


def conversation_turns(cid):
    return store.conversation_turns(cid)


def rename_conversation(cid, title):
    return store.set_conversation_title(cid, title)


# ---- library ---------------------------------------------------------------

_book_of = retrieve.book_of


def books():
    try:
        rows = store.v1("library").execute(
            "SELECT DISTINCT book, file_path FROM chunks").fetchall()
    except Exception:
        return []
    seen, out = set(), []
    for r in rows:
        title = _book_of(r["book"] or r["file_path"])
        if not title or title.lower() in seen:
            continue
        seen.add(title.lower())
        out.append({"id": title, "title": title, "series": None,
                    "summary": None, "concepts": None})
    return sorted(out, key=lambda b: b["title"].lower())


def book_detail(bid):
    excerpts = []
    try:
        rows = store.v1("library").execute(
            "SELECT content FROM chunks WHERE book=? OR file_path LIKE ? LIMIT 3",
            (bid, f"%{bid}%")).fetchall()
        for r in rows:
            txt = re.sub(r"\s+", " ", r["content"] or "").strip()
            if txt:
                excerpts.append({"concept": "", "excerpt": txt[:400], "text": None})
    except Exception:
        pass
    return {"summary": None, "concepts": [], "excerpts": excerpts}


def passage(book, loc, hint):
    hint = (hint or "").strip()
    key = re.sub(r"\s+", " ", hint).strip().lower()[:160]
    try:
        con = store.v1("library")
        rows = con.execute(
            "SELECT content, chapter FROM chunks WHERE book=? OR file_path LIKE ?",
            (book, f"%{book}%")).fetchall()
    except Exception:
        return {"book": book, "loc": loc, "error": "library unavailable"}
    best = None
    for r in rows:
        hay = re.sub(r"\s+", " ", r["content"] or "")
        if key and key in hay.lower():
            best = (hay, r["chapter"] or loc)
            break
        if best is None:
            best = (hay, r["chapter"] or loc)
    if not best:
        return {"book": book, "loc": loc, "error": "passage not found"}
    hay, chapter = best
    i = hay.lower().find(key) if key else -1
    if i >= 0:
        start = max(0, hay.rfind(".", 0, i) + 1)
        end = hay.find(".", i + len(key))
        quote = hay[start:(end + 1 if end > 0 else i + 300)].strip()
        text = hay[max(0, i - 600): i + 900].strip()
    else:
        quote = hay[:240].strip()
        text = hay[:1200]
    return {"book": book, "loc": chapter, "quote": quote,
            "text": text, "error": None}


# ---- settings --------------------------------------------------------------

_MODEL_OPTIONS = ["deepseek-flash", "deepseek-v4-pro",
                  "qwen3.5:35b-a3b-nvfp4", "qwen3.8:27b-mlx", "qwen3.8:27b", "qwen2.5:7b"]


def settings_payload():
    s = _settings()
    spec = [
        {"key": "model", "section": "Everyday", "help": "Writer model (blank = profile default)."},
        {"key": "voice", "section": "Everyday", "help": "Answer voice (informational)."},
        {"key": "thinking", "section": "Everyday", "help": "Let the writer think before answering."},
        {"key": "profile", "section": "Advanced", "help": "online | local."},
        {"key": "max_rounds", "section": "Advanced", "help": "Spiral rungs (safety cap)."},
        {"key": "top_k", "section": "Advanced", "help": "Passages retrieved."},
    ]
    values = {
        "model": s.get("writer", ""),
        "voice": "default",
        "thinking": bool(s.get("writer_think", True)),
        "profile": s.get("profile", "online"),
        "max_rounds": s.get("max_rounds", 2),
        "top_k": s.get("top_k", 6),
    }
    options = {"model": _MODEL_OPTIONS, "profile": ["online", "local"], "voice": ["default"]}
    return {"spec": spec, "values": values, "options": options}


def apply_setting(key, value):
    s = _settings()
    if key == "model":
        s["writer"] = str(value)
    elif key == "thinking":
        s["writer_think"] = bool(value)
    elif key == "profile":
        s["profile"] = str(value) if str(value) in ("online", "local") else s.get("profile", "online")
    elif key == "max_rounds":
        try:
            s["max_rounds"] = max(1, min(4, int(value)))
        except Exception:
            pass
    elif key == "top_k":
        try:
            s["top_k"] = max(2, min(20, int(value)))
        except Exception:
            pass
    config.save_settings(s)
    return True


# ---- /command --------------------------------------------------------------

def run_command(cmd, arg):
    cmd = (cmd or "").strip().lower()
    if cmd in ("status", ""):
        s = _settings()
        w = s.get("writer") or (config.LOCAL_WRITER if s["profile"] == "local"
                                else config.DEEPSEEK_FLASH)
        v2 = store.v2()
        counts = {t: v2.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                  for t in ("claims", "attacks", "events", "sessions", "memory")}
        try:
            lib = store.v1("library")
            chunks = lib.execute("SELECT count(*) FROM chunks").fetchone()[0]
        except Exception:
            chunks = 0
        return True, (f"mentat v{mentat2.__version__} · profile={s['profile']} · writer={w}\n"
                      f"library chunks={chunks} · claims={counts['claims']} "
                      f"attacks={counts['attacks']} sessions={counts['sessions']}")
    if cmd in ("index", "index-status"):
        try:
            lib = store.v1("library")
            c = lib.execute("SELECT count(*) FROM chunks").fetchone()[0]
            sp = lib.execute("SELECT count(*) FROM spans").fetchone()[0]
            fts = store.v1("fts").execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
            return True, f"library: {c} chunks · {sp} spans · fts {fts}"
        except Exception as e:
            return False, f"index unavailable: {e}"
    if cmd in ("count", "census"):
        if not arg:
            return False, "usage: /count <phrase>"
        c = retrieve.census(arg)
        per = ", ".join(f"{k}: {v}" for k, v in list(c["per_work"].items())[:6])
        return True, f"{c['total']} occurrence(s) of '{arg}'.\n{per}"
    if cmd in ("find", "quote"):
        if not arg:
            return False, "usage: /find <phrase>"
        ps = retrieve.hunt(arg, limit=5)
        if not ps:
            return True, f"no passage found for '{arg}'"
        return True, "\n\n".join(f"{p['work']} · {p['loc']}\n{p['text'][:400]}" for p in ps)
    if cmd in ("help", "?"):
        return True, ("commands: /status · /index · /count <phrase> · /find <phrase> · "
                      "/clear · /help")
    return False, f"unknown command: /{cmd}"


# ---- HTTP ------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path == "/status":
                s = _settings()
                w = s.get("writer") or (config.LOCAL_WRITER if s["profile"] == "local"
                                        else config.DEEPSEEK_FLASH)
                return self._send({"ok": True, "model": w, "v": mentat2.__version__,
                                   "code": code_id(), "pid": os.getpid(),
                                   "profile": s["profile"],
                                   "models": {"writer": w, "embed": config.OLLAMA_EMBED_MODEL}})
            if u.path == "/stats":
                v2 = store.v2()
                counts = {t: v2.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                          for t in ("claims", "attacks", "events", "sessions", "memory")}
                return self._send({"telemetry": telemetry.summary(), "counts": counts})
            if u.path == "/conversations":
                return self._send({"conversations": conversations()})
            if u.path == "/conversation":
                return self._send({"turns": conversation_turns(q.get("id", [""])[0])})
            if u.path == "/books":
                return self._send({"books": books()})
            if u.path == "/book":
                return self._send(book_detail(q.get("id", [""])[0]))
            if u.path == "/passage":
                return self._send(passage(q.get("book", [""])[0], q.get("loc", [""])[0],
                                          q.get("hint", [""])[0]))
            if u.path == "/settings":
                return self._send(settings_payload())
        except Exception as e:
            return self._send({"ok": False, "error": str(e)[:300]}, 500)
        return self._send({"ok": False, "error": "not found"}, 404)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    def do_POST(self):
        u = urlparse(self.path)
        body = self._body()

        if u.path == "/shutdown":
            # graceful stop (so the app can retire a stale/orphan engine it didn't spawn)
            def _stop():
                time.sleep(0.1)
                if _SERVER is not None:
                    _SERVER.shutdown()
            threading.Thread(target=_stop, daemon=True).start()
            return self._send({"ok": True})

        if u.path == "/ask":
            q = (body.get("question") or "").strip()
            if not q:
                return self._send({"status": "error", "error": "no question"}, 400)
            conv = body.get("conversation") or body.get("conv") or ""
            atts = body.get("attachments") or []
            try:
                s = ask(q, conversation=conv or None, attachments=atts)
            except Exception as e:
                return self._send({"status": "error", "error": str(e)[:300]}, 500)
            v = s.verdict
            u = getattr(s, "usage", {}) or {}
            tin, tout = int(u.get("tokens_in", 0)), int(u.get("tokens_out", 0))
            cached = int(u.get("cached", 0))
            return self._send({
                "status": "ok", "answer": s.answer, "error": None,
                "conversation": s.conv,
                "citations": citations_of(s.answer), "ungrounded": (v.ungrounded if v else 0),
                "model": s.route.writer,
                "meta": {"kind": "quotes" if (v and v.counts.get("quotes")) else "prose",
                         "t_thinking": 0.0, "t_content": 0.0,
                         "tokens_in": tin, "tokens_out": tout, "cost_usd": 0.0,
                         "cache_hit_tokens": cached, "cache_miss_tokens": max(0, tin - cached),
                         "route_reason": f"{s.route.mode}:{s.route.profile}"}})

        if u.path == "/ask/stream":
            q = (body.get("question") or "").strip()
            if not q:
                return self._send({"status": "error", "error": "no question"}, 400)
            conv = body.get("conversation") or body.get("conv") or ""
            atts = body.get("attachments") or []
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            for ev in ask_stream(q, conversation=conv or None, attachments=atts):
                try:
                    self.wfile.write((json.dumps(ev, ensure_ascii=False, default=str) + "\n").encode())
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    break
            return

        if u.path == "/command":
            ok, text = run_command(body.get("cmd", ""), body.get("arg", ""))
            return self._send({"ok": ok, "text": text})

        if u.path == "/settings":
            apply_setting(body.get("key", ""), body.get("value"))
            return self._send(settings_payload())

        if u.path in ("/conversation/open", "/conversation/new"):
            # a fresh id, but do NOT create a row yet — the first turn creates it
            # (so an untouched "new chat" never shows up as an empty card)
            return self._send({"ok": True, "id": body.get("id") or store.new_conversation_id()})
        if u.path in ("/conversation/rename", "/conversation/edit"):
            cid = body.get("id", "")
            title = body.get("title", body.get("name", ""))
            ok = rename_conversation(cid, title)
            return self._send({"ok": ok, "id": cid, "title": title})
        if u.path == "/conversation/delete":
            cid = body.get("id", "")
            store.delete_conversation(cid)
            return self._send({"ok": True})

        # engine-owned thread edits (single source of truth for "forget from here")
        if u.path == "/conversation/truncate":
            cid = body.get("conversation") or body.get("id") or ""
            keep = int(body.get("keep", 0) or 0)
            ok = store.truncate_conversation(cid, keep)
            return self._send({"ok": ok, "id": cid, "keep": keep})
        if u.path in ("/conversation/delete_turn", "/conversation/deleteTurn"):
            cid = body.get("conversation") or body.get("id") or ""
            index = int(body.get("index", 0) or 0)
            ok = store.delete_turn(cid, index)
            return self._send({"ok": ok, "id": cid, "index": index})

        return self._send({"ok": False, "error": "not found"}, 404)


def main():
    import argparse
    global _SERVER
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()

    reap_stale()                       # a fresh launch must run current code, never reuse
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    _SERVER = srv
    try:
        PIDFILE.write_text(str(os.getpid()))
    except Exception:
        pass

    def _cleanup():
        try:
            if PIDFILE.exists() and PIDFILE.read_text().strip() == str(os.getpid()):
                PIDFILE.unlink()
        except Exception:
            pass

    atexit.register(_cleanup)
    print(f"Mentat v2 engine on http://{a.host}:{a.port} · code {code_id()} · pid {os.getpid()}",
          flush=True)
    if config.WARMUP and config.load_settings().get("profile") == "local":
        def _warm():
            try:
                r = gateway.warmup()
                print(f"warmup: {r}", flush=True)
            except Exception as e:
                print(f"warmup failed: {e}", flush=True)

        threading.Thread(target=_warm, daemon=True).start()
    try:
        srv.serve_forever()
    finally:
        _cleanup()


if __name__ == "__main__":
    main()
