"""Storage: read v1 indexes (library/fts/vec/graph) + own v2.db.

v2 NEVER writes to v1 storage. v2.db holds the new dialectic tables.
"""
from __future__ import annotations
import contextlib
import json
import shutil
import sqlite3
import tempfile
import threading
from pathlib import Path
import numpy as np
from . import config

# One connection per thread: the HTTP server is ThreadingHTTPServer, and a single
# shared sqlite connection is not safe to use across threads (writes were silently
# failing under concurrent requests).
_local = threading.local()

# A small, observable error sink: previously-swallowed write failures are recorded
# here (PEP 20: errors should never pass silently) and surfaced in doctor/stats.
_ERRORS: list = []
_ERRORS_MAX = 200


def note_error(where, exc):
    _ERRORS.append({"where": where, "error": f"{type(exc).__name__}: {exc}"[:200]})
    if len(_ERRORS) > _ERRORS_MAX:
        del _ERRORS[0]


def errors():
    return list(_ERRORS)


@contextlib.contextmanager
def ephemeral():
    """Run against a throwaway v2.db — so tests/diagnostics never touch the user's
    real brain (pytest tmp_path pattern). Restores and deletes on exit."""
    old = config.V2_DB
    tmpdir = tempfile.mkdtemp(prefix="mentat-test-")
    config.V2_DB = Path(tmpdir) / "test.db"
    try:
        del _local.v2
    except Exception as e:
        note_error("ephemeral", e)
    try:
        yield config.V2_DB
    finally:
        try:
            con = getattr(_local, "v2", None)
            if con is not None:
                con.close()
            del _local.v2
        except Exception as e:
            note_error("ephemeral", e)
        config.V2_DB = old
        shutil.rmtree(tmpdir, ignore_errors=True)

SCHEMA = """
CREATE TABLE IF NOT EXISTS claims(
  id TEXT PRIMARY KEY, chunk_id TEXT, work TEXT, loc TEXT, text TEXT,
  entrenchment REAL DEFAULT 0.5, created REAL
);
CREATE TABLE IF NOT EXISTS attacks(
  id TEXT PRIMARY KEY, src TEXT, dst TEXT, kind TEXT, scope TEXT,
  confidence REAL, created REAL, immanent INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, session TEXT, parent TEXT,
  name TEXT, stage TEXT, model TEXT, seconds REAL,
  tokens_in INTEGER, tokens_out INTEGER, payload TEXT
);
CREATE TABLE IF NOT EXISTS sessions(
  id TEXT PRIMARY KEY, query TEXT, answer TEXT, verdict TEXT,
  route TEXT, created REAL, title TEXT, conv TEXT, turn INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS conversations(
  id TEXT PRIMARY KEY, title TEXT, created REAL, updated REAL,
  summary TEXT, summary_upto INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS documents(
  id INTEGER PRIMARY KEY AUTOINCREMENT, conv TEXT, name TEXT, path TEXT,
  chars INTEGER, text TEXT, created REAL
);
CREATE INDEX IF NOT EXISTS idx_documents_conv ON documents(conv);
CREATE TABLE IF NOT EXISTS memory(
  id INTEGER PRIMARY KEY AUTOINCREMENT, session TEXT, kind TEXT,
  text TEXT, claim_id TEXT, ts REAL,
  topic TEXT, valid_at REAL, invalid_at REAL, source TEXT, turn INTEGER DEFAULT 0
);
"""

CTX_SCHEMA = """
CREATE TABLE IF NOT EXISTS ctx_meta(
  chunk_id TEXT PRIMARY KEY, file_path TEXT, book TEXT, chapter TEXT, seq INTEGER
);
CREATE VIRTUAL TABLE IF NOT EXISTS ctx_fts USING fts5(chunk_id UNINDEXED, content);
CREATE VIRTUAL TABLE IF NOT EXISTS ctx_vec USING vec0(
  chunk_id TEXT PRIMARY KEY, embedding float[768] distance_metric=cosine
);
"""

# columns that may be missing on an older v2.db — added in place (idempotent)
_MEM_MIGRATIONS = (
    "ALTER TABLE memory ADD COLUMN topic TEXT",
    "ALTER TABLE memory ADD COLUMN valid_at REAL",
    "ALTER TABLE memory ADD COLUMN invalid_at REAL",
    "ALTER TABLE memory ADD COLUMN source TEXT",
    "ALTER TABLE attacks ADD COLUMN immanent INTEGER DEFAULT 0",
    "ALTER TABLE sessions ADD COLUMN title TEXT",
    "ALTER TABLE sessions ADD COLUMN conv TEXT",
    "ALTER TABLE sessions ADD COLUMN turn INTEGER DEFAULT 0",
    "ALTER TABLE memory ADD COLUMN turn INTEGER DEFAULT 0",
    "ALTER TABLE conversations ADD COLUMN summary TEXT",
    "ALTER TABLE conversations ADD COLUMN summary_upto INTEGER DEFAULT 0",
)


def v1(name: str) -> sqlite3.Connection:
    conns = getattr(_local, "v1", None)
    if conns is None:
        conns = {}
        _local.v1 = conns
    if name not in conns:
        path = config.V1_STORAGE / f"{name}.db"
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        if name == "vec":
            import sqlite_vec
            con.enable_load_extension(True)
            sqlite_vec.load(con)
            con.enable_load_extension(False)
        conns[name] = con
    return conns[name]


def v2() -> sqlite3.Connection:
    con = getattr(_local, "v2", None)
    if con is None:
        con = sqlite3.connect(str(config.V2_DB), check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.executescript(SCHEMA)
        for stmt in _MEM_MIGRATIONS:
            try:
                con.execute(stmt)
            except Exception:
                pass
        # migrate pre-conversation sessions: each old lone session becomes its own
        # conversation (idempotent), so existing history is preserved.
        try:
            con.execute("UPDATE sessions SET conv=id WHERE conv IS NULL OR conv=''")
            con.execute("INSERT OR IGNORE INTO conversations(id,title,created,updated) "
                        "SELECT id, substr(query,1,80), created, created FROM sessions")
        except Exception as e:
            note_error("v2", e)
        con.commit()
        _local.v2 = con
    return con


def ctx() -> sqlite3.Connection:
    """The contextual retrieval index (Anthropic Contextual Retrieval): chunk text
    with its document context, in its own db so it can be rebuilt independently."""
    con = getattr(_local, "ctx", None)
    if con is None:
        import sqlite_vec
        con = sqlite3.connect(str(config.CTX_DB), check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.enable_load_extension(True)
        sqlite_vec.load(con)
        con.enable_load_extension(False)
        con.executescript(CTX_SCHEMA)
        con.commit()
        _local.ctx = con
    return con


def save_fact(topic, text, source="user"):
    import time
    now = time.time()
    try:
        v2().execute(
            "INSERT INTO memory(session,kind,text,topic,valid_at,ts,source)"
            " VALUES('','fact',?,?,?,?,?)", (str(text), str(topic), now, now, source))
        v2().commit()
        return True
    except Exception:
        return False


def invalidate_fact(fact_id):
    import time
    try:
        v2().execute("UPDATE memory SET invalid_at=? WHERE id=?", (time.time(), int(fact_id)))
        v2().commit()
        return True
    except Exception:
        return False


def active_facts(limit=50):
    try:
        return [dict(r) for r in v2().execute(
            "SELECT id,topic,text,valid_at FROM memory"
            " WHERE kind='fact' AND invalid_at IS NULL ORDER BY valid_at DESC LIMIT ?",
            (limit,))]
    except Exception:
        return []


def get_chunk(chunk_id: str):
    r = v1("library").execute(
        "SELECT chunk_id,file_path,book,chapter,content FROM chunks WHERE chunk_id=?",
        (chunk_id,)).fetchone()
    return dict(r) if r else None


def record_event(span):
    try:
        v2().execute(
            "INSERT INTO events(ts,session,parent,name,stage,model,seconds,tokens_in,tokens_out,payload)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)", span.as_row())
        v2().commit()
    except Exception as e:
        note_error("record_event", e)


def save_claim(c):
    try:
        v2().execute("INSERT OR REPLACE INTO claims(id,chunk_id,work,loc,text,entrenchment,created)"
                     " VALUES(?,?,?,?,?,?,strftime('%s','now'))",
                     (c.id, c.chunk_id, c.work, c.loc, c.text, c.entrenchment))
        v2().commit()
    except Exception as e:
        note_error("save_claim", e)


def load_claims_for_chunks(chunk_ids):
    if not chunk_ids:
        return []
    q = ",".join("?" * len(chunk_ids))
    return [dict(r) for r in v2().execute(
        f"SELECT * FROM claims WHERE chunk_id IN ({q})", tuple(chunk_ids))]


def save_attack(a):
    try:
        v2().execute("INSERT OR REPLACE INTO attacks(id,src,dst,kind,scope,confidence,created,immanent)"
                     " VALUES(?,?,?,?,?,?,strftime('%s','now'),?)",
                     (a.id, a.src, a.dst, a.kind, a.scope, a.confidence, int(bool(a.immanent))))
        v2().commit()
    except Exception as e:
        note_error("save_attack", e)


def save_session(sid, session, conv="", title=""):
    import json
    cid = conv or sid
    try:
        from .contracts import to_dict
        turn = v2().execute("SELECT count(*) FROM sessions WHERE conv=?", (cid,)).fetchone()[0]
        v2().execute("INSERT OR REPLACE INTO sessions(id,query,answer,verdict,route,created,conv,turn)"
                     " VALUES(?,?,?,?,?,strftime('%s','now'),?,?)",
                     (sid, getattr(session, "query", "") or "",
                      getattr(session, "answer", "") or "",
                      json.dumps(to_dict(getattr(session, "verdict", None)), ensure_ascii=False),
                      json.dumps(to_dict(getattr(session, "route", None)), ensure_ascii=False),
                      cid, int(turn)))
        v2().commit()
        ensure_conversation(cid, title)
        return int(turn)
    except Exception:
        return 0


def count_turns(conv):
    try:
        return v2().execute("SELECT count(*) FROM sessions WHERE conv=?", (conv,)).fetchone()[0]
    except Exception:
        return 0


def truncate_conversation(conv, keep):
    """Forget every turn from `keep` on (edit / regenerate). 0-based."""
    try:
        v2().execute("DELETE FROM sessions WHERE conv=? AND turn>=?", (conv, int(keep)))
        v2().execute("DELETE FROM memory WHERE session=? AND turn>=?", (conv, int(keep)))
        v2().commit()
        return True
    except Exception:
        return False


def delete_turn(conv, index):
    """Remove one turn (question+answer) and close the gap in the thread."""
    try:
        v2().execute("DELETE FROM sessions WHERE conv=? AND turn=?", (conv, int(index)))
        v2().execute("UPDATE sessions SET turn=turn-1 WHERE conv=? AND turn>?", (conv, int(index)))
        v2().execute("DELETE FROM memory WHERE session=? AND turn=?", (conv, int(index)))
        v2().execute("UPDATE memory SET turn=turn-1 WHERE session=? AND turn>?", (conv, int(index)))
        v2().commit()
        return True
    except Exception:
        return False


# ---- conversations ---------------------------------------------------------

def ensure_conversation(conv, title=""):
    import time as _t
    now = _t.time()
    try:
        v2().execute(
            "INSERT INTO conversations(id,title,created,updated) VALUES(?,?,?,?)"
            " ON CONFLICT(id) DO UPDATE SET updated=excluded.updated,"
            " title=CASE WHEN conversations.title IS NULL OR conversations.title=''"
            "            THEN excluded.title ELSE conversations.title END",
            (conv, str(title or "")[:200], now, now))
        v2().commit()
    except Exception as e:
        note_error("ensure_conversation", e)


def set_conversation_title(conv, title):
    try:
        v2().execute("UPDATE conversations SET title=?, updated=? WHERE id=?",
                     (str(title or "")[:200], __import__("time").time(), conv))
        v2().commit()
        return True
    except Exception:
        return False


def new_conversation_id():
    import uuid
    return uuid.uuid4().hex[:12]


def list_conversations(limit=100):
    try:
        rows = v2().execute(
            "SELECT c.id, c.title, c.updated,"
            " (SELECT count(*) FROM sessions s WHERE s.conv=c.id) AS cnt,"
            " (SELECT query FROM sessions s WHERE s.conv=c.id ORDER BY rowid ASC LIMIT 1) AS first_q"
            " FROM conversations c ORDER BY c.updated DESC LIMIT ?", (limit,)).fetchall()
    except Exception:
        return []
    return [dict(r) for r in rows]


def conversation_turns(conv, limit=200):
    try:
        rows = v2().execute(
            "SELECT query, answer, route, created FROM sessions WHERE conv=? "
            "ORDER BY rowid ASC LIMIT ?", (conv, limit)).fetchall()
    except Exception:
        return []
    out = []
    for r in rows:
        model = ""
        try:
            model = (json.loads(r["route"] or "{}") or {}).get("writer", "")
        except Exception as e:
            note_error("conversation_turns", e)
        out.append({"question": r["query"] or "", "answer": r["answer"] or "", "model": model})
    return out


def recent_turns(conv, k=8, char_budget=6000):
    try:
        rows = v2().execute(
            "SELECT query, answer FROM sessions WHERE conv=? AND answer!='' "
            "ORDER BY rowid DESC LIMIT 50", (conv,)).fetchall()
    except Exception:
        return []
    picked, used = [], 0
    for r in rows:
        q = r["query"] or ""
        a = r["answer"] or ""
        cost = len(q) + len(a)
        if picked and used + cost > char_budget:
            break
        picked.append({"question": q, "answer": a})
        used += cost
        if len(picked) >= k:
            break
    return list(reversed(picked))


def conversation_summary(conv):
    """(summary_text, turns_covered) for the running compaction summary."""
    try:
        r = v2().execute("SELECT summary, summary_upto FROM conversations WHERE id=?",
                         (conv,)).fetchone()
        return ((r["summary"] or "", int(r["summary_upto"] or 0)) if r else ("", 0))
    except Exception:
        return ("", 0)


def set_conversation_summary(conv, text, upto):
    try:
        v2().execute("UPDATE conversations SET summary=?, summary_upto=? WHERE id=?",
                     (str(text or ""), int(upto), conv))
        v2().commit()
    except Exception as e:
        note_error("set_conversation_summary", e)


def older_turns(conv, upto):
    """Turns [0, upto) oldest-first, for compaction."""
    try:
        rows = v2().execute(
            "SELECT query, answer FROM sessions WHERE conv=? ORDER BY rowid ASC LIMIT ?",
            (conv, int(upto))).fetchall()
    except Exception:
        return []
    return [{"question": r["query"] or "", "answer": r["answer"] or ""} for r in rows]


def delete_conversation(conv):
    try:
        v2().execute("DELETE FROM sessions WHERE conv=?", (conv,))
        v2().execute("DELETE FROM documents WHERE conv=?", (conv,))
        v2().execute("DELETE FROM conversations WHERE id=?", (conv,))
        v2().commit()
        return True
    except Exception:
        return False


# ---- documents (drag-and-drop attachments, kept per conversation) ----------

def save_document(conv, name, path, text):
    try:
        # re-attaching the same file replaces it (no duplicates)
        v2().execute("DELETE FROM documents WHERE conv=? AND path=?", (conv, str(path or "")))
        v2().execute("INSERT INTO documents(conv,name,path,chars,text,created)"
                     " VALUES(?,?,?,?,?,strftime('%s','now'))",
                     (conv, str(name or ""), str(path or ""), len(text or ""), text or ""))
        v2().commit()
        return True
    except Exception as e:
        note_error("save_document", e)
        return False


def documents_for(conv, max_chars=400_000):
    """Concatenated text of this conversation's documents (newest-first budget)."""
    try:
        rows = v2().execute(
            "SELECT name, text FROM documents WHERE conv=? ORDER BY id ASC", (conv,)).fetchall()
    except Exception:
        return ""
    out, used = [], 0
    for r in rows:
        hdr = f"## FILE: {r['name']}\n"
        body = r["text"] or ""
        if used + len(body) > max_chars:
            body = body[:max(0, max_chars - used)]
        out.append(hdr + body)
        used += len(hdr) + len(body)
        if used >= max_chars:
            break
    return "\n\n".join(out)


def save_memory(session, kind, text, claim_id="", turn=0):
    try:
        v2().execute("INSERT INTO memory(session,kind,text,claim_id,ts,turn)"
                     " VALUES(?,?,?,?,strftime('%s','now'),?)",
                     (session, kind, text, claim_id, int(turn)))
        v2().commit()
    except Exception as e:
        note_error("save_memory", e)


def memory_for(session, limit=20):
    return [dict(r) for r in v2().execute(
        "SELECT kind,text,claim_id FROM memory WHERE session=? ORDER BY id DESC LIMIT ?",
        (session, limit))]
