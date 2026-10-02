"""Mentat v2 MCP server. Mirrors brain_mcp.py's API:
`from mcp.server.mcpserver import MCPServer` + `@server.tool(...)` + `server.run(transport="stdio")`.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from mcp.server.mcpserver import MCPServer  # noqa: E402

from mentat2 import config, store, telemetry  # noqa: E402
from mentat2.pipeline import ask  # noqa: E402
from mentat2 import retrieve  # noqa: E402

server = MCPServer("mentat")


def _spiral(session):
    out = []
    for i, r in enumerate(session.rounds, 1):
        rd = r.return_delta or {}
        out.append({"rung": i,
                    "immediate": rd.get("position_text", "") or r.immediate,
                    "negation": rd.get("negation_text", "") or r.negation,
                    "cancelled": r.sublation.cancelled,
                    "preserved": r.sublation.preserved,
                    "product": rd.get("raised", "") or r.sublation.product,
                    "new_immediate": r.sublation.new_immediate,
                    "changed": rd.get("changed"),
                    "invariants_ok": r.invariants_ok,
                    "violations": r.violations})
    return out


@server.tool(
    name="ask_brain",
    title="Reason across the indexed library",
    description=(
        "Ask a grounded question answered from the indexed books. Returns the answer, "
        "the dialectical spiral the engine computed (position, negation, sublation, "
        "new contradiction), a verdict (grounding/citations), and timing."
    ),
)
def ask_brain(question: str) -> str:
    s = ask(question)
    return json.dumps({
        "ok": True, "answer": s.answer, "spiral": _spiral(s),
        "mode": s.route.mode, "profile": s.route.profile,
        "verdict": {"grounded": s.verdict.grounded, "citations": s.verdict.citations,
                    "ungrounded": s.verdict.ungrounded},
    }, indent=2, ensure_ascii=False)


@server.tool(
    name="find_quote",
    title="Find a half-remembered quote verbatim",
    description="Hunt the library for a phrase and return verbatim windows with locations.",
)
def find_quote(question: str, limit: int = 8) -> str:
    ps = retrieve.hunt(question, limit=limit)
    return json.dumps({"ok": True, "passages": [
        {"work": p.get("work"), "loc": p.get("loc"), "text": (p.get("text") or "")[:600]}
        for p in ps]}, indent=2, ensure_ascii=False)


@server.tool(name="count_phrase", title="Exact count of a word or phrase",
             description="Authoritative full-text count of a phrase across the library.")
def count_phrase(phrase: str) -> str:
    return json.dumps({"ok": True, **retrieve.census(phrase)}, indent=2, ensure_ascii=False)


@server.tool(name="brain_status", title="Engine status",
             description="Version, active profile, and model registry summary.")
def brain_status() -> str:
    settings = config.load_settings()
    return json.dumps({"ok": True, "version": __import__("mentat2").__version__,
                       "profile": settings.get("profile"),
                       "writer": settings.get("writer") or "(auto)"},
                      indent=2, ensure_ascii=False)


@server.tool(name="brain_stats", title="Telemetry and store stats",
             description="Per-stage timings and row counts (claims, attacks, events, memory).")
def brain_stats() -> str:
    v2 = store.v2()
    counts = {}
    for t in ("claims", "attacks", "events", "sessions", "memory"):
        try:
            counts[t] = v2.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        except Exception:
            counts[t] = None
    return json.dumps({"ok": True, "telemetry": telemetry.summary(), "counts": counts},
                      indent=2, ensure_ascii=False)


@server.tool(name="remember", title="Persist a fact forever",
             description="Append a dated fact to the vault memory; indexed for future answers.")
def remember(text: str, topic: str = "default") -> str:
    from mentat2 import memory as mem
    mem.remember_fact(topic, text)
    return json.dumps({"ok": True, "remembered": text[:120], "topic": topic},
                      ensure_ascii=False)


def main():
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
