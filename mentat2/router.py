"""The one decider. Produces a single Route for the whole pipeline.

Modes (auto-detected): ``chat`` · ``strict`` · ``search`` · ``dialectic``.

Architecture (cross-checked):
  · Adaptive-RAG (Jeong et al.) — route by query complexity: no-retrieval / single-step /
    multi-step.  Here: chat / search / dialectic.
  · Self-RAG (Asai et al.) — retrieve on demand; don't retrieve when unnecessary.
  · Semantic Router (Aurelio) — embedding-similarity intent, no LLM call, local.
  · LlamaIndex RouterQueryEngine — a selector over named engines.

Matching is **word-boundary / whole-token** (never bare substring): 'hi' must not fire on
'this', 'hey' not on 'they', 'no' not on 'knowledge'. Deterministic signals run first so the
dialectic eval set can't silently drift; a local embedding vote is the tie-break.
"""
from __future__ import annotations
import re
import numpy as np
from . import gateway, config
from .contracts import Route

# --- signals (matched as whole tokens / explicit phrases, not substrings) ---
_STRICT_PHRASES = ("how many", "number of", "find the", "word for word", "exact words")
_STRICT_WORDS = ("quote", "quotes", "passage", "passages", "litany", "verbatim")

_DIALECTIC_WORDS = ("why", "contradiction", "contradictions", "dialectic", "dialectical",
                    "aufhebung", "immanent", "thesis", "antithesis")
_DIALECTIC_PREFIX = ("negat", "sublat", "contradict")     # negation/negate/sublation/…

_CHAT_WORDS = ("hi", "hello", "hey", "thanks", "yo", "bye", "lol", "haha", "cheers",
               "sup", "howdy", "gm")
_CHAT_PHRASES = ("thank you", "who are you", "what can you do", "how are you",
                 "can you help", "help me", "tell me a joke", "good morning",
                 "good night", "good evening", "what's up", "whats up", "what is up",
                 "how's it going", "hows it going", "what's good", "whats good",
                 "nice to meet")
_POLITE = ("can you", "could you", "would you", "will you", "can i", "may i", "please ")

_QUESTION_START = ("who", "what", "when", "where", "which", "how", "define", "summar",
                   "list", "explain", "tell me about")

_EXEMPLARS = {
    "chat": ["hi there", "how are you doing", "thanks, that's helpful", "what can you do",
             "who are you", "can you help me with this", "tell me a joke",
             "ok cool, sounds good", "good morning"],
    "search": ["who is Leto II's father", "what does the Quran say about usury",
               "summarize the Muqaddimah", "list the books about debt",
               "where is the litany against fear", "define asabiyya",
               "how many times is mercy mentioned", "which book discusses the golden path"],
    "dialectic": ["why does the master lose by winning", "does the tyrant produce the freedom he sought",
                  "is recognition possible without equality",
                  "what contradiction destroys the dynasty", "does debt both preserve and destroy",
                  "can a prohibition of usury contradict the logic of debt"],
}
_EMB = None
_WORD = re.compile(r"[a-z']+")


def _tokens(q):
    return set(_WORD.findall(q))


def _embed_intent(q):
    global _EMB
    try:
        if _EMB is None:
            _EMB = {m: np.asarray(gateway.embed(us), dtype=np.float32) for m, us in _EXEMPLARS.items()}
        qe = np.asarray(gateway.embed([q])[0], dtype=np.float32)
        qn = qe / (np.linalg.norm(qe) + 1e-9)
        best = None
        for m, mat in _EMB.items():
            s = float(((mat @ qn) / (np.linalg.norm(mat, axis=1) + 1e-9)).max())
            if best is None or s > best[1]:
                best = (m, s)
        return best
    except Exception:
        return None


def _mentions_library(q):
    toks = _tokens(q)
    lib = {"library", "books", "book", "texts", "dune", "quran", "kojeve", "hegel",
           "khaldun", "muqaddimah", "marx", "stalin", "hudson", "atreides", "fremen",
           "butlerian", "arrakis"}
    return bool(toks & lib)


def classify(query, embed=True) -> tuple[str, str]:
    ql = (query or "").lower().strip()
    toks = _tokens(ql)
    if ql.startswith("find:") or any(p in ql for p in _STRICT_PHRASES) or (toks & set(_STRICT_WORDS)):
        return "strict", "strict keyword"
    # social → chat ONLY when the message is primarily social (a greeting with substance —
    # e.g. "what's up with the master/slave dialectic" — routes by its content instead).
    chat_hit = (ql.startswith(_POLITE) or (toks & set(_CHAT_WORDS))
                or any(p in ql for p in _CHAT_PHRASES))
    if chat_hit and not (_mentions_library(ql) or (toks & set(_DIALECTIC_WORDS))):
        if ql.startswith(_POLITE) or len(toks) <= 5:
            return "chat", "polite/social"
    if (toks & set(_DIALECTIC_WORDS)) or any(p in ql for p in _DIALECTIC_PREFIX):
        return "dialectic", "dialectic signal"
    if " or " in ql and ql.startswith(("is ", "are ", "does ", "do ", "can ", "did ",
                                       "was ", "were ", "should ")):
        return "dialectic", "opposition question"
    if ql.startswith(("why", "does ", "do ", "did ")):
        return "dialectic", "does/why question"
    if ql.startswith(("can ", "should ", "if ")) and len(toks) > 3:
        return "dialectic", "deliberative question"
    if len(toks) <= 2:
        return "chat", "short"
    if embed:
        best = _embed_intent(ql)
        if best and best[1] >= 0.45:
            return best[0], f"embed {best[1]:.2f}"
    if ql.startswith(_QUESTION_START) or ql.endswith("?"):
        return "search", "lookup question"
    return "chat", "default"


def route(query, settings=None, has_document=False):
    settings = settings or config.load_settings()
    profile = settings.get("profile", "online")
    writer = settings.get("writer") or gateway.default_writer(profile)
    if has_document:
        # a dropped file makes this document work (edit/critique/rewrite), not a lookup
        mode, reason = "document", "attachment"
    else:
        mode, reason = classify(query)
        # adaptive retrieval (Self-RAG): a conversational turn that names the library
        # escalates to a grounded search.
        if mode == "chat" and _mentions_library((query or "").lower()):
            mode, reason = "search", "chat escalated (library mentioned)"
    return Route(profile=profile, mode=mode,
                 context_budget=int(settings.get("context_chars", 14000)),
                 writer=writer, reason=reason)
