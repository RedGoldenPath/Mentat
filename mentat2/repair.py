"""Grounding repair — an architectural stage, not a badge.

After the writer, any quotation that cannot be bound to the evidence is fixed by a
bounded revision pass (Self-RAG support / CRAG correct / CoVe verify / RARR retrofit):
replace with a verbatim evidence sentence + inline citation, or drop the quote and
paraphrase. Only unsupported spans are touched.
"""
from __future__ import annotations
from . import gateway, verify


def _flagged_quote_lines(answer, passages):
    ev = verify.norm(" \u2022 ".join((p.get("text") or "") for p in passages))
    out = []
    for line in (answer or "").splitlines():
        s = line.strip()
        if not s.startswith(">"):
            continue
        body = verify.CITE.sub("", s.lstrip(">")).strip()
        if len(body) >= 12 and not verify.bound(body, ev):
            out.append(s)
    return out


def repair(answer, passages, profile="online", model="", think=False):
    flagged = _flagged_quote_lines(answer, passages)
    if not flagged:
        return answer
    ev = "\n\n".join(f"[{i}] {p.get('work','')} · {p.get('loc','')}\n{(p.get('text') or '')[:1800]}"
                     for i, p in enumerate(passages[:8], 1))
    prompt = (
        "Fix ONLY the unsupported quotations in the DRAFT. The EVIDENCE is the only allowed "
        "source. For each listed quote: if the EVIDENCE contains a close verbatim sentence, "
        "replace the quote with that exact sentence and put the citation inline at the end "
        "of the quoted line as (Book · location); otherwise REMOVE the quote and paraphrase "
        "in your own words with no quotation marks. Change nothing else; keep all other "
        "citations. Return ONLY the full revised answer.\n\n"
        "UNSUPPORTED QUOTES:\n" + "\n".join(flagged[:8]) +
        "\n\nEVIDENCE:\n" + ev +
        "\n\nDRAFT:\n" + (answer or "")[:9000]
    )
    try:
        fixed = gateway.chat(prompt, profile=profile, model=model, job="repair",
                             max_tokens=3000, temperature=0.3, think=think)
    except Exception:
        return answer
    fixed = (fixed or "").strip()
    return fixed if len(fixed) > 200 else answer


def strip_unbound(answer, passages, keep=0.0):
    """Deterministic last guard: remove any blockquote that still cannot be bound to
    the evidence (a fabricated quote is worse than a missing one)."""
    ev = verify.norm(" \u2022 ".join((p.get("text") or "") for p in passages))
    lines = (answer or "").splitlines()
    total_q = sum(1 for l in lines if l.strip().startswith(">"))
    out, dropped = [], 0
    for line in lines:
        s = line.strip()
        if s.startswith(">"):
            body = verify.CITE.sub("", s.lstrip(">")).strip()
            if len(body) >= 12 and not verify.bound(body, ev):
                dropped += 1
                continue
        out.append(line)
    # Never nuke every quotation — that would hollow the answer.
    if total_q and dropped >= total_q:
        return answer, 0
    return "\n".join(out), dropped

