"""Pipeline as a DECLARED graph (see graph.py). Stages, not an if-stack.

route -> retrieve -> [dialectical: claims -> attacks -> loop] -> write -> verify/repair
 -> memory.  Telemetry per stage via the graph runner.
"""
from __future__ import annotations
import re
import time
import uuid
from . import (config, router, retrieve, claims as claims_mod, attacks as attacks_mod,
               loop, writer, verify, telemetry, memory, gateway, store, extract)
from .graph import Graph
from .contracts import Session


# Quote-hunt scaffolding: strip the request ("find me …", "show me …") and the noun
# ("quotes", "passages", …) so the subject alone is searched. Without this the hunt
# looks for the literal string "find me quotes on X", which never matches, and the
# writer is handed an empty EVIDENCE block.
_QUOTE_SCRUB = re.compile(
    r"^\s*(?:(?:can|could|would)\s+you\s+)?"
    r"(?:(?:find|show|give|get|pull|search|fetch|list)\s+(?:me|us)?\s*)?"
    r"(?:(?:any|some|all|the|a|an)\s+)?"
    r"(?:quotes?|quotations?|passages?|verbatim|exact\s+words?|exact\s+quotes?)\s*"
    r"(?:(?:on|about|regarding|re|for|mentioning|related\s+to|where)\s+)?"
    r"(?:from\s+)?",
    re.I,
)


def _quote_subject(query: str) -> str:
    """The subject of a "find me quotes on X" style request — `X`, not the whole ask."""
    s = _QUOTE_SCRUB.sub(" ", query or "", count=1)
    s = re.sub(r"\s+", " ", s).strip(" ?.,:;!\"'")
    return s


# ---- stages ---------------------------------------------------------------

_ANAPHORA = (" it", " this", " that", " these", " those", " them", " they", "the essay",
             "the draft", "the document", "back it", "continue", "again", " more", " expand",
             "shorten", "tighten", "the argument", "the piece")


def _condense(query, hist, profile):
    """LlamaIndex 'CondenseQuestionChatEngine': rewrite a short/anaphoric follow-up into a
    standalone question *using the history*, before routing/retrieval. Faithful, doesn't
    answer it. Only for substantive follow-ups (not greetings/lookups)."""
    if not hist:
        return query
    ql = query.lower()
    if len(ql.split()) > 12 and not any(a in " " + ql for a in _ANAPHORA):
        return query
    try:
        convo = "\n".join(f"User: {h['question'][:300]}\nAssistant: {h['answer'][:600]}"
                          for h in hist[-3:])
        prompt = ("Rewrite the user's latest message as a standalone question or instruction "
                  "that makes sense on its own. Keep it faithful; do NOT answer it. Output only "
                  f"the rewrite.\n\nCONVERSATION:\n{convo}\n\nLATEST: {query}\n\nSTANDALONE:")
        out = gateway.chat(prompt, profile=profile, model=gateway.default_fast(profile),
                           job="summary", temperature=0.0, think=False, max_tokens=160)
        out = (out or "").strip().split("\n")[0].strip()
        return out if 3 <= len(out) <= 500 else query
    except Exception:
        return query


def _compact(s, conv):
    """OpenAI-style compaction: summarize turns older than the last few into a running
    summary (stored per conversation); recent turns stay verbatim."""
    try:
        total = store.count_turns(conv)
        keep = 4
        if total <= keep:
            return
        summ, upto = store.conversation_summary(conv)
        if upto >= total - keep and summ:
            return
        older = store.older_turns(conv, total - keep)
        if not older:
            return
        text = "\n".join(f"Q: {t['question'][:300]}\nA: {t['answer'][:600]}" for t in older[-12:])
        out = gateway.chat(
            "Summarize this conversation so it can be carried forward as context. Keep the "
            "user's goals/instructions, decisions, and key facts. Be concise.\n\n" + text,
            profile=s["route"].profile, model=gateway.default_fast(s["route"].profile),
            job="summary", temperature=0.0, think=False, max_tokens=400)
        summ = (out or "").strip()[:1500]
        if summ:
            store.set_conversation_summary(conv, summ, total - keep)
    except Exception:
        pass


def _route(s):
    conv = s.get("conv") or ""
    atts = s.get("attachments") or []
    if atts:
        for a in atts:
            path = a.get("path") or a.get("name") or ""
            name = a.get("name") or path.rsplit("/", 1)[-1]
            try:
                text = extract.extract_text(path)
            except Exception:
                text = None            # unreadable/unsupported: don't persist junk
            if text is not None:
                store.save_document(conv, name, path, text)
    # history (needed for condense + compaction + writer)
    hist = []
    try:
        hist = store.recent_turns(conv, k=int(s["settings"].get("history_turns", 8)),
                                  char_budget=int(s["settings"].get("history_chars", 6000))) \
            if conv else []
    except Exception:
        hist = []
    # compaction: fold older turns into a running summary
    _compact(s, conv) if conv else None
    try:
        summ, upto = store.conversation_summary(conv) if conv else ("", 0)
        if summ:
            hist = [{"question": "(earlier conversation — summary)", "answer": summ}] + hist
    except Exception:
        pass

    doc = store.documents_for(conv) if conv else ""
    profile = s["settings"].get("profile", "online")
    # document precedence: once a thread has a document, EVERY follow-up is document mode
    # (the doc + history + library evidence) — never a context-free mode swap.
    has_doc = bool(doc)
    base_mode, _ = router.classify(s["query"])
    q_for_route = s["query"]
    if base_mode in ("search", "dialectic"):
        q_for_route = _condense(s["query"], hist, profile)
    if has_doc:
        s["document"] = doc
        s["route"] = router.route(q_for_route, s["settings"], has_document=True)
    else:
        s["route"] = router.route(q_for_route, s["settings"])
    s["retrieval_query"] = q_for_route

    prior = ""
    try:
        prior = memory.prior(conv) if conv else ""
    except Exception:
        prior = ""
    s["session"] = Session(query=s["query"], route=s["route"], prior=prior,
                           conv=conv, history=hist)


def _retrieve(s):
    route = s["route"]
    ql = s["query"].lower()
    rq = s.get("retrieval_query") or s["query"]
    quote_intent = any(w in ql for w in
                       ("find", "quote", "litany", "passage", "verbatim", "exact words"))
    if route.mode == "strict" and quote_intent:
        # span-anchored hunt → citations carry real page numbers (RAGFlow-style).
        # Hunt the *subject* ("X"), not the raw "find me quotes on X" — and if the
        # phrase isn't verbatim (typo, OCR drift, paraphrase) the lexical hunt finds
        # nothing, so fall back to semantic+BM25 retrieval rather than answering "the
        # EVIDENCE field is empty" when the library plainly has material.
        subj = _quote_subject(s["query"]) or s["query"]
        s["passages"] = retrieve.span_hunt(subj, limit=int(s["settings"].get("top_k", 6)))
        if not s["passages"]:
            s["passages"] = retrieve.retrieve(subj, k=int(s["settings"].get("top_k", 8)),
                                              budget_chars=route.context_budget)
    else:
        s["passages"] = retrieve.retrieve(rq, k=int(s["settings"].get("top_k", 8)),
                                          budget_chars=route.context_budget)
    s["session"].evidence = s["passages"]
    telemetry.record("retrieve", s["sid"], stage="retrieve", n=len(s["passages"]),
                     works=sorted({p.get("work", "") for p in s["passages"]})[:8])


def _census(s):
    if s["route"].mode == "strict" and any(w in s["query"].lower() for w in ("how many", "count")):
        try:
            c = retrieve.census(s["query"])
            s["facts"] = (f"A deterministic census found {c['total']} occurrence(s) across "
                          f"the library: {c['per_work']}. Treat this count as authoritative.")
        except Exception:
            s["facts"] = ""


def _claims(s):
    s["claims"] = claims_mod.claims_for_passages(
        s["passages"], s["route"].profile, gateway.default_fast(s["route"].profile))
    telemetry.record("claims", s["sid"], stage="claims", n=len(s["claims"]))


def _attacks(s):
    s["attacks"], _ = attacks_mod.find_attacks(s["claims"], s["route"].profile)
    telemetry.record("attacks", s["sid"], stage="attacks", n=len(s["attacks"]))


def _loop(s):
    # Adaptive-RAG: only pay for multi-step (a second rung/Return) when the evidence is
    # genuinely multi-source; single-source dialectic needs one turn.
    works = {p.get("work") for p in s["passages"] if p.get("work")}
    want = 2 if len(works) >= 2 else 1
    max_rounds = min(want, int(s["settings"].get("max_rounds", 2)))
    s["session"] = loop.run(s["session"], s["claims"], s["attacks"], s["route"],
                            max_rounds=max_rounds,
                            brief_model=gateway.default_fast(s["route"].profile))
    rounds = s["session"].rounds
    violations = [v for r in rounds for v in (r.violations or [])]
    telemetry.record("loop", s["sid"], stage="loop", rounds=len(rounds),
                     invariants_ok=all(r.invariants_ok for r in rounds) if rounds else None,
                     violations=violations)


def _write(s):
    route, settings = s["route"], s["settings"]
    think = bool(settings.get("writer_think", False))
    mode = route.mode
    if mode == "document":
        ans = writer.render_document(s["session"], s.get("document", ""),
                                     s.get("passages") or None, route.profile,
                                     route.writer, think=think)
    elif mode == "chat" or not s["passages"]:
        # conversational mode, or no evidence at all -> answer plainly, don't force a
        # cited/dialectical answer (CRAG/Self-RAG: a failed retrieval should not be
        # dressed up as grounded prose).
        ans = writer.render_chat(s["session"], s.get("passages") or None, route.profile,
                                 route.writer, think=think)
    elif mode == "strict":
        ans = writer.render_strict(s["session"], s["passages"], route.profile,
                                   route.writer, facts=s.get("facts", ""))
    elif mode == "search":
        ans = writer.render_interpretive(s["session"], s["passages"], route.profile,
                                         route.writer, think=think)
    else:  # dialectic
        ans = writer.render_dialectical(s["session"], s["passages"], route.profile,
                                        route.writer, think=think)
        if len((ans or "").strip()) < 200:
            telemetry.record("fallback", s["sid"], stage="write",
                             reason="dialectical answer empty/short -> interpretive")
            ans = writer.render_interpretive(s["session"], s["passages"], route.profile,
                                             route.writer, think=think)
    s["session"].answer = ans
    telemetry.record("write", s["sid"], stage="write", model=route.writer, chars=len(ans or ""))


def _verify_repair(s):
    session, passages = s["session"], s["passages"]
    session.verdict = verify.check(session.answer, passages)
    original = session.answer
    from . import repair as repair_mod
    if s["settings"].get("repair", True) and session.verdict.ungrounded and passages:
        try:
            fixed = repair_mod.repair(session.answer, passages, s["route"].profile,
                                      s["route"].writer,
                                      think=bool(s["settings"].get("repair_think", False)))
            if fixed and fixed != session.answer and len(fixed.strip()) > 200:
                session.answer = fixed
                session.verdict = verify.check(session.answer, passages)
                telemetry.record("repair", s["sid"], stage="repair",
                                 ungrounded_after=session.verdict.ungrounded)
        except Exception:
            pass
    if session.verdict and session.verdict.ungrounded and passages:
        try:
            stripped, dropped = repair_mod.strip_unbound(session.answer, passages)
            if dropped and len(stripped.strip()) > 200:
                session.answer = stripped
                session.verdict = verify.check(session.answer, passages)
                telemetry.record("strip", s["sid"], stage="repair", dropped=dropped)
        except Exception:
            pass
    if len(session.answer.strip()) < 200 and len(original.strip()) >= 200:
        session.answer = original
        session.verdict = verify.check(session.answer, passages)
    telemetry.record("verify", s["sid"], stage="verify",
                     grounded=session.verdict.grounded,
                     ungrounded=session.verdict.ungrounded,
                     citations=session.verdict.citations)


def _memory(s):
    session = s["session"]
    conv = s.get("conv") or s["sid"]
    try:
        turn = store.count_turns(conv)
        if session.rounds:
            last = session.rounds[-1]
            raised = last.return_delta.get("raised")
            if raised:
                memory.remember_position(conv, raised, turn)
            nc = last.sublation.new_immediate
            if nc:
                memory.remember_contradiction(conv, str(nc)[:300], turn)
            memory.remember_preserved(conv, last.sublation.preserved, turn)
        # the first user message titles the conversation (ChatGPT convention)
        store.save_session(s["sid"], session, conv=conv, title=(session.query or "")[:80])
    except Exception:
        pass


def _graph() -> Graph:
    g = Graph()
    g.add("route", _route)
    # chat does not retrieve (Self-RAG: decide whether to retrieve). search/strict/
    # dialectic all ground in the library.
    g.add("retrieve", _retrieve,
          when=lambda s: s["route"].mode in ("search", "strict", "dialectic", "document"))
    g.add("census", _census)
    g.add("claims", _claims, when=lambda s: s["route"].mode == "dialectic"
          and bool(s["passages"]))
    g.add("attacks", _attacks, when=lambda s: bool(s.get("claims")))
    g.add("loop", _loop, when=lambda s: bool(s.get("claims")))
    g.add("write", _write)
    g.add("verify", _verify_repair)
    g.add("memory", _memory)
    return g


_GRAPH = _graph()


def ask(query, session_id=None, conversation=None, attachments=None, settings=None):
    settings = settings or config.load_settings()
    conv = conversation or session_id or uuid.uuid4().hex[:12]
    state = {"query": query, "settings": settings, "sid": uuid.uuid4().hex[:12],
             "conv": conv, "attachments": attachments or [],
             "facts": "", "passages": [], "claims": [], "attacks": []}
    t0 = time.time()
    _GRAPH.run(state)
    state["session"].usage = state.get("usage", {})
    telemetry.record("total", state["sid"], stage="total", seconds=round(time.time() - t0, 1))
    return state["session"]


def citations_of(answer):
    """Distinct (book, loc) citations in the answer, in order."""
    out = []
    for m in verify.CITE.finditer(answer or ""):
        body = m.group(0)[1:-1]
        if "\u00b7" not in body:
            continue
        book, loc = body.split("\u00b7", 1)
        c = {"book": book.strip(), "loc": loc.strip()}
        if c not in out:
            out.append(c)
    return out[:12]


def ask_stream(query, session_id=None, conversation=None, attachments=None, settings=None):
    """Generator of the app's /ask/stream events. Streams the writer (the long pole)
    token by token; emits progress between stages. Yields dicts:
      {"t":"progress","v":...} · {"t":"chunk","v":...} · {"t":"done", ...} · {"t":"error","v":...}
    """
    settings = settings or config.load_settings()
    conv = conversation or session_id or uuid.uuid4().hex[:12]
    state = {"query": query, "settings": settings, "sid": uuid.uuid4().hex[:12],
             "conv": conv, "attachments": attachments or [],
             "facts": "", "passages": [], "claims": [], "attacks": []}
    t0 = time.time()
    try:
        _route(state)
        route = state["route"]
        yield {"t": "progress", "v": f"{route.mode} \u00b7 {route.profile} \u00b7 {route.reason}"}
        if route.mode in ("search", "strict", "dialectic", "document"):
            _retrieve(state)
            yield {"t": "progress", "v": f"{len(state['passages'])} passages"}
            _census(state)
        use_dial = route.mode == "dialectic" and bool(state["passages"])
        if use_dial:
            yield {"t": "progress", "v": "claims"}
            _claims(state)
            yield {"t": "progress", "v": f"{len(state['claims'])} claims"}
            _attacks(state)
            yield {"t": "progress", "v": f"{len(state['attacks'])} attacks"}
            _loop(state)
            yield {"t": "progress", "v": f"{len(state['session'].rounds)} rung(s) \u00b7 the spiral"}

        session = state["session"]
        think = bool(settings.get("writer_think", False))
        if route.mode == "document":
            gen = writer.render_document_stream(session, state.get("document", ""),
                                                state["passages"] or None, route.profile,
                                                route.writer, think=think)
        elif route.mode == "chat" or (not state["passages"] and route.mode in ("search", "dialectic")):
            gen = writer.render_chat_stream(session, state["passages"] or None,
                                            route.profile, route.writer, think=think)
        elif use_dial and session.rounds:
            gen = writer.render_dialectical_stream(session, state["passages"], route.profile,
                                                   route.writer, think=think)
        elif route.mode == "strict":
            gen = writer.render_strict_stream(session, state["passages"], route.profile,
                                              route.writer, facts=state.get("facts", ""))
        else:
            gen = writer.render_interpretive_stream(session, state["passages"], route.profile,
                                                    route.writer, think=think)
        yield {"t": "progress", "v": "writing"}
        ans = ""
        for tok in gen:
            ans += tok
            yield {"t": "chunk", "v": tok}

        used = gateway.take_usage()
        tin = sum(int(u.get("prompt_tokens", 0)) for u in used)
        tout = sum(int(u.get("completion_tokens", 0)) for u in used)
        cached = sum(int(u.get("cached_prompt_tokens", 0)) for u in used)

        if len(ans.strip()) < 80 and state["passages"]:
            yield {"t": "progress", "v": "retrying"}
            ans = writer.render_interpretive(session, state["passages"], route.profile,
                                             route.writer) or ans
            yield {"t": "chunk", "v": ans}
        session.answer = ans
        session.verdict = verify.check(ans, state["passages"]) if state["passages"] else None
        v = session.verdict
        meta = {"kind": "quotes" if (v and v.counts.get("quotes")) else "prose",
                "t_thinking": 0.0, "t_content": round(time.time() - t0, 2),
                "tokens_in": tin, "tokens_out": tout, "cost_usd": 0.0,
                "cache_hit_tokens": cached, "cache_miss_tokens": max(0, tin - cached),
                "route_reason": f"{route.mode}:{route.profile}"}
        yield {"t": "done", "answer": ans, "citations": citations_of(ans),
               "ungrounded": (v.ungrounded if v else 0), "model": route.writer,
               "status": "ok", "conversation": conv, "meta": meta}
        try:
            _memory(state)
        except Exception:
            pass
        telemetry.record("total", state["sid"], stage="total", seconds=round(time.time() - t0, 1))
    except Exception as e:
        yield {"t": "error", "v": str(e)[:300]}
