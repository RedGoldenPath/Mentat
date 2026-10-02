"""Component metrics (RAGAS-style, implemented in-house) + pairwise preference.

Offline-friendly: faithfulness uses the local NLI cross-encoder; no ground-truth needed.
"""
from __future__ import annotations
import re
from .. import gateway


def _sentences(text):
    parts = re.split(r"(?<=[.!?])\s+", (text or "").replace("\n", " "))
    return [p.strip() for p in parts if 40 <= len(p.strip()) <= 400]


def faithfulness(answer, passages, bias=0.5):
    """Fraction of answer sentences entailed by the evidence (NLI). 0-1."""
    ev = " ".join((p.get("text") or "")[:1500] for p in passages[:6])[:6000]
    if not ev:
        return 0.0
    sents = _sentences(answer)
    if not sents:
        return 1.0
    try:
        judged = gateway.nli_batch([(ev, s) for s in sents])
    except Exception:
        judged = [("neutral", 0.0)] * len(sents)
    good = 0
    for label, conf in judged:
        if label == "entailment" or (label == "neutral" and conf < bias):
            good += 1
    return round(good / len(sents), 3)


def context_relevance(question, passages):
    """Mean reranker score of kept passages (higher = better-context)."""
    sc = [p.get("score") for p in passages if isinstance(p.get("score"), (int, float))]
    return round(sum(sc) / len(sc), 3) if sc else None
