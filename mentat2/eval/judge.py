"""LLM judging (tests only). Anchored 0-7 movement score + pairwise A/B with bias swap."""
from __future__ import annotations
import json
import re
from .. import gateway, config

_RUBRIC = (
    "Grade the answer's DIALECTICAL MOVEMENT, 0-7. Anchors:\n"
    "0 = flat summary or pure information, no movement.\n"
    "2 = states a position but never finds a contradiction inside it.\n"
    "3 = names an external opposing view ('on the other hand'), no immanent negation.\n"
    "4 = finds a contradiction but resolves it by merging/both-sides (NOT dialectical).\n"
    "5 = immanent contradiction found and lifted, but the sublation is vague.\n"
    "6 = clear cancel/preserve/raise on ONE subject, but no new contradiction named.\n"
    "7 = immanent contradiction, determinate sublation (cancels a one-sided aspect, preserves "
    "what is true, raises a higher reading), AND a new contradiction it generates.\n"
    "Be strict. Penalize the thesis/antithesis/synthesis formula and any 'both sides' hedging. "
    'Return ONLY JSON {"movement":int,"quality":int(1-5),"note":"<=20 words"}.'
)


def judge(question, answer):
    prompt = (_RUBRIC + f"\n\nQUESTION: {question[:400]}\n\nANSWER:\n{(answer or '')[:6000]}")
    try:
        raw = gateway.chat(prompt, profile="online", model=config.DEEPSEEK_PRO, job="judge",
                           max_tokens=900, temperature=0.2, think=True)
    except Exception as e:
        return {"movement": None, "quality": None, "note": f"judge error: {e}"}
    m = re.search(r"\{.*\}", raw or "", re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except Exception:
        d = {}
    return {"movement": d.get("movement"), "quality": d.get("quality"),
            "note": str(d.get("note", ""))[:60]}


def _pair_once(question, a, b):
    prompt = (
        "Two answers to the same question are labelled A and B. Which one performs the "
        "DIALECTICAL movement better (immanent contradiction found, determinate sublation, a "
        "NEW contradiction named), AND is better grounded and more insightful? Be strict; if "
        "genuinely equal reply TIE. Return ONLY JSON "
        '{"winner":"A|B|TIE","why":"<=25 words"}.\n\n'
        f"QUESTION: {question[:400]}\n\nA:\n{(a or '')[:5000]}\n\nB:\n{(b or '')[:5000]}"
    )
    try:
        raw = gateway.chat(prompt, profile="online", model=config.DEEPSEEK_PRO, job="judge",
                           max_tokens=400, temperature=0.0, think=True)
    except Exception:
        return "TIE"
    m = re.search(r"\{.*\}", raw or "", re.S)
    try:
        w = str(json.loads(m.group(0)).get("winner", "TIE")).strip().upper()
    except Exception:
        w = "TIE"
    return "A" if w.startswith("A") else ("B" if w.startswith("B") else "TIE")


def judge_pairwise(question, first, second):
    """Return 'first', 'second', or 'tie', swapping positions to cancel bias."""
    w1 = _pair_once(question, first, second)          # first=A, second=B
    w2 = _pair_once(question, second, first)          # swapped
    v1 = 1 if w1 == "A" else (-1 if w1 == "B" else 0)
    v2 = -1 if w2 == "A" else (1 if w2 == "B" else 0)  # account for swap
    net = v1 + v2
    return "first" if net > 0 else ("second" if net < 0 else "tie")
