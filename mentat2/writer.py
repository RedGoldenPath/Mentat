"""The writer — renders the computed movement. Modes are configuration, not pipelines."""
from __future__ import annotations
from . import gateway

_CITE = (
    "Quote the books verbatim inside blockquotes (lines starting with '>') and put the "
    "citation INLINE at the end of the quoted line as (Book · location) — never on its own "
    "line. Never invent a quote; if the evidence lacks it, say so once."
)
_NO_TRIAD = (
    "Do NOT use the words thesis, antithesis, or synthesis. Do not resolve by 'both sides'. "
    "Take a determinate position, negate it, and lift it."
)
_BUDGET = (
    " Keep it focused: about 500-650 words, at most 5 verbatim quotes. "
    "Precision over length."
)

# Stable, byte-identical system prefix for every writer call. Sits first so
# providers can prompt-cache it; all per-query content goes in the user turn.
_SYSTEM = (
    "You are a dialectical thinker working over the user's library. You are given the "
    "MOVEMENT the system computed (a position, the contradiction inside it, the sublation, "
    "and the new contradiction), and the EVIDENCE. Write the answer as continuous prose "
    "that PERFORMS this movement — do not list it. If the EVIDENCE does not actually address "
    "the question, say so plainly instead of forcing an answer. " + _NO_TRIAD + " " + _CITE + _BUDGET
)

# conversational mode (no forced movement, no mandatory citations)
_CHAT_SYSTEM = (
    "You are Mentat, a thoughtful assistant for the user's personal library. Continue the "
    "conversation naturally and helpfully, using the CONVERSATION SO FAR. If EVIDENCE is "
    "provided, ground the answer in it and quote verbatim with (Book · location); if it is "
    "not, just answer from your own knowledge, conversationally. Do NOT force a dialectical "
    "movement and do NOT force citations. Match the length and tone to the question."
)


def _evidence_block(passages, budget=9000):
    parts, used = [], 0
    for i, p in enumerate(passages, 1):
        loc = p.get("loc") or ""
        head = f"[{i}] {p.get('work','')}" + (f" · {loc}" if loc else "")
        txt = (p.get("text") or "")[:2600]
        entry = f"{head}\n{txt}"
        if used + len(entry) > budget and parts:
            break
        parts.append(entry)
        used += len(entry)
    return "\n\n".join(parts)


def _movement_lines(session):
    lines = []
    for i, r in enumerate(session.rounds, 1):
        s = r.sublation
        lines.append(
            f"Rung {i}: immediate={r.immediate}; immanent contradiction={r.negation}; "
            f"cancelled={s.cancelled}; preserved={len(s.preserved)} kept; product={s.product}; "
            f"new immediacy={s.new_immediate}; return={r.return_delta.get('changed')}"
        )
    return "\n".join(lines) or "(no contradiction found in the evidence)"


def _history_block(session):
    hist = getattr(session, "history", None) or []
    if not hist:
        return ""
    lines = ["CONVERSATION SO FAR (this is a continuing chat; the question may refer to it):"]
    for h in hist[-4:]:
        q = (h.get("question") or "").strip()
        a = (h.get("answer") or "").strip()
        if q:
            lines.append(f"User: {q[:300]}")
        if a:
            lines.append(f"Assistant: {a[:1000]}")   # keep more context for editorial threads
    return "\n".join(lines)


def _dialectical_prompt(session, passages):
    prior = (getattr(session, "prior", "") or "").strip()
    prior_block = (f"\n\nPRIOR POSITION (carried forward — the spiral continues from it):\n{prior[:600]}"
                   if prior else "")
    hist = _history_block(session)
    hist_block = (f"\n\n{hist}" if hist else "")
    return (
        hist_block +
        "\n\nQUESTION: " + session.query +
        prior_block +
        "\n\nCOMPUTED MOVEMENT:\n" + _movement_lines(session) +
        "\n\nEVIDENCE:\n" + _evidence_block(passages)
    )


def render_dialectical(session, passages, profile="online", model="", think=True):
    return gateway.chat(_dialectical_prompt(session, passages), system=_SYSTEM,
                        profile=profile, model=model, job="writer", temperature=0.6, think=think)


def render_dialectical_stream(session, passages, profile="online", model="", think=True):
    return gateway.chat_stream(_dialectical_prompt(session, passages), system=_SYSTEM,
                               profile=profile, model=model, job="writer",
                               temperature=0.6, think=think)


def render_interpretive(session, passages, profile="online", model="", think=True):
    return gateway.chat(_interpretive_prompt(session, passages), system=_SYSTEM,
                        profile=profile, model=model, job="writer", temperature=0.6, think=think)


def _interpretive_prompt(session, passages):
    hist = _history_block(session)
    hist_block = (f"{hist}\n\n" if hist else "")
    return (hist_block + "QUESTION: " + session.query +
            "\n\nEVIDENCE:\n" + _evidence_block(passages))


def render_interpretive_stream(session, passages, profile="online", model="", think=True):
    return gateway.chat_stream(_interpretive_prompt(session, passages), system=_SYSTEM,
                               profile=profile, model=model, job="writer",
                               temperature=0.6, think=think)


def _strict_prompt(session, passages, facts=""):
    hist = _history_block(session)
    return ((f"{hist}\n\n" if hist else "") +
            (facts + "\n" if facts else "") +
            "\nQUESTION: " + session.query + "\n\nEVIDENCE:\n" + _evidence_block(passages))


def render_strict(session, passages, profile="online", model="", facts="", think=False):
    system = ("Answer the question directly and factually from the EVIDENCE. "
              + _CITE + _NO_TRIAD)
    return gateway.chat(_strict_prompt(session, passages, facts), system=system,
                        profile=profile, model=model, job="writer", temperature=0.3, think=think)


def render_strict_stream(session, passages, profile="online", model="", facts="", think=False):
    system = ("Answer the question directly and factually from the EVIDENCE. "
              + _CITE + _NO_TRIAD)
    return gateway.chat_stream(_strict_prompt(session, passages, facts), system=system,
                               profile=profile, model=model, job="writer",
                               temperature=0.3, think=think)


# document/editing mode (the user dropped a file: essay, draft, notes)
_DOC_SYSTEM = (
    "You are a precise editor working over the user's DRAFT. The DRAFT is provided as "
    "DOCUMENT. Follow the user's instruction exactly: if they ask for an edit or rewrite, "
    "return the edited text; if they ask for critique, give specific, actionable notes and "
    "quote the draft. Stay faithful to the author's intent and voice; never invent facts. "
    "If library EVIDENCE is provided, you may use it. " + _NO_TRIAD
)


def _document_prompt(session, document, passages=None):
    hist = _history_block(session)
    ev = _evidence_block(passages) if passages else ""
    return ((f"{hist}\n\n" if hist else "") +
            "INSTRUCTION: " + session.query +
            "\n\nDOCUMENT:\n" + (document or "(no document)") +
            (f"\n\nEVIDENCE (library, optional):\n{ev}" if ev else ""))


def render_document(session, document, passages=None, profile="online", model="", think=True):
    return gateway.chat(_document_prompt(session, document, passages), system=_DOC_SYSTEM,
                        profile=profile, model=model, job="writer", temperature=0.5, think=think)


def render_document_stream(session, document, passages=None, profile="online", model="", think=True):
    return gateway.chat_stream(_document_prompt(session, document, passages), system=_DOC_SYSTEM,
                               profile=profile, model=model, job="writer",
                               temperature=0.5, think=think)


def _chat_prompt(session, passages=None):
    hist = _history_block(session)
    ev = _evidence_block(passages) if passages else ""
    return ((f"{hist}\n\n" if hist else "") +
            "USER: " + session.query +
            (f"\n\nEVIDENCE:\n{ev}" if ev else ""))


def render_chat(session, passages=None, profile="online", model="", think=True):
    return gateway.chat(_chat_prompt(session, passages), system=_CHAT_SYSTEM,
                        profile=profile, model=model, job="chat", temperature=0.7, think=think)


def render_chat_stream(session, passages=None, profile="online", model="", think=True):
    return gateway.chat_stream(_chat_prompt(session, passages), system=_CHAT_SYSTEM,
                               profile=profile, model=model, job="chat",
                               temperature=0.7, think=think)
