"""Session + persistent memory.

Session: the prior dialectical position carried across turns (the spiral).
Persistent: bi-temporal facts (Zep/Graphiti style — invalidate, never delete).
"""
from __future__ import annotations
from . import store


def remember_position(session_id, text, turn=0):
    if text:
        store.save_memory(session_id, "position", text[:400], turn=turn)


def remember_contradiction(session_id, text, turn=0):
    if text:
        store.save_memory(session_id, "contradiction", text[:400], turn=turn)


def remember_preserved(session_id, items, turn=0):
    """What was preserved is what carries forward — 'to preserve is to remember'
    (Kojève). Empty preservation means Nihilism; the invariant flags that."""
    for it in (items or [])[:5]:
        if it:
            store.save_memory(session_id, "preserved", str(it)[:400], turn=turn)


def prior(session_id):
    rows = store.memory_for(session_id)
    for r in rows:
        if r["kind"] == "position":
            return r["text"]
    return ""


def remember_fact(topic, text):
    """Persist a user fact (bi-temporal; valid from now)."""
    return store.save_fact(topic, text, source="user")


def invalidate(fact_id):
    return store.invalidate_fact(fact_id)


def facts(limit=50):
    return store.active_facts(limit)
