"""Sublation: cancel / preserve / raise, plus the new contradiction. Hegelian, not triadic."""
from __future__ import annotations
import json
import re
from . import gateway

_PROMPT = (
    "You are a dialectician in the tradition of Hegel, Kojève and Stalin — the method is "
    "Aufhebung, NOT the thesis/antithesis/synthesis formula. Given a POSITION and the "
    "CONTRADICTION internal to it, and the evidence, produce the SUBLATION.\n"
    "Return ONLY JSON with keys cancelled, preserved, raised, new_contradiction:\n"
    "cancelled = the one-sided aspect that is given up; preserved = the truth that is kept; "
    "raised = the higher claim that cancels and preserves both, one sentence; "
    "new_contradiction = the new contradiction the raised claim generates, or empty.\n"
    "The RAISED claim MUST be genuinely higher and DIFFERENT from the POSITION — never the "
    "position restated, never a merge of the two sides. It preserves the POSITION's truth "
    "while cancelling its one-sidedness.\n"
    "Never write the words thesis, antithesis, or synthesis.\n\n"
    "POSITION: {pos}\nCONTRADICTION: {neg}\nEVIDENCE:\n{ev}\n"
)


def build(position_text, negation_text, evidence_texts, profile, model):
    """One Aufhebung. The model proposes the *product* (the raised whole); the engine
    computes cancelled/preserved deterministically (see loop.py). Returns spiral fields."""
    ev = "\n".join(f"- {t[:500]}" for t in (evidence_texts or [])[:6])
    try:
        raw = gateway.chat(_PROMPT.format(pos=position_text, neg=negation_text, ev=ev),
                           profile=profile, model=model, job="brief", max_tokens=700,
                           temperature=0.4,
                           json_schema={"type": "object", "properties": {
                               "cancelled": {"type": "string"},
                               "preserved": {"type": "string"},
                               "raised": {"type": "string"},
                               "new_contradiction": {"type": "string"}},
                               "required": ["cancelled", "preserved", "raised"]})
    except Exception:
        return {}
    m = re.search(r"\{.*\}", raw or "", re.S)
    try:
        data = json.loads(m.group(0)) if m else {}
    except Exception:
        data = {}
    d = {k: str(data.get(k, "")).strip()
         for k in ("cancelled", "preserved", "raised", "new_contradiction")}
    return {
        "immediate": position_text,
        "cancelled": d["cancelled"],
        "preserved": d["preserved"],
        "product": d["raised"],
        "new_immediate": d["new_contradiction"],
    }
