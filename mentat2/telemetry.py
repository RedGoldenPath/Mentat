"""Telemetry: spans into v2.db + a small metrics summary for the debug view."""
from __future__ import annotations
from . import store
from .contracts import Span

_LAST: list = []


def record(name, session="", stage="", model="", seconds=0.0, tokens_in=0,
           tokens_out=0, parent="", **payload):
    sp = Span(name=name, session=session, parent=parent, stage=stage, model=model,
              seconds=seconds, tokens_in=tokens_in, tokens_out=tokens_out, payload=payload)
    store.record_event(sp)
    _LAST.append(sp)
    return sp


def summary(limit=500):
    try:
        rows = store.v2().execute(
            "SELECT stage, count(*) n, sum(seconds) sec, sum(tokens_in) tin, sum(tokens_out) tout "
            "FROM (SELECT * FROM events ORDER BY id DESC LIMIT ?) GROUP BY stage",
            (limit,)).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
