"""Deterministic verification: are the quotes really in the evidence? Citations counted."""
from __future__ import annotations
import re
from .contracts import Verdict

# Looser citation matcher: tolerates nested parens like "(God Emperor of Dune · Ch.34 (ch42))".
_CITE = re.compile(r"\(([^)\n]{2,120})·[^)\n]{1,120}\)")
_DQ = re.compile(r"[\u201c\"]([^\u201d\"]{12,300})[\u201d\"]")


def _norm(s):
    s = (s or "").replace("\u2019", "'").lower()
    s = re.sub(r"[^a-z0-9' ]+", " ", s)   # drop punctuation; OCR/format drift tolerant
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _bound(q, ev_norm):
    """Grounding with tolerance: exact substring, or >=90% token coverage."""
    nq = _norm(q)
    if len(nq) < 12:
        return True
    if nq in ev_norm:
        return True
    words = [w for w in nq.split() if len(w) > 2]
    if not words:
        return True
    hit = sum(1 for w in words if w in ev_norm)
    return hit / len(words) >= 0.9


def _quotes(answer):
    """Blockquote blocks as (quote, line) pairs (citation-only lines dropped),
    else inline quotes."""
    out, cur = [], []

    def flush():
        if cur:
            out.append((" ".join(q for q, _ in cur), " ".join(ln for _, ln in cur)))
            cur.clear()

    for line in (answer or "").splitlines():
        s = line.strip()
        if s.startswith(">"):
            body = s[1:].strip()
            if not body:
                continue
            if _CITE.fullmatch(body):     # a citation on its own line, not a quote
                continue
            cur.append((body, body))
        else:
            flush()
    flush()
    if not out:
        out = [(m.group(1), m.group(0)) for m in _DQ.finditer(answer or "")]
    return out


def _cited_works(text):
    """Book names named in citations on a line, e.g. (Book (X) · p12)."""
    return [m.group(1).strip() for m in _CITE.finditer(text or "") if m.group(1).strip()]


def _work_matches(book, works_norm):
    """Match a citation's book name to an evidence work. Citation names are human
    titles ("Kojeve, Introduction to the Reading of Hegel") while works are filenames
    ("Kojeve_IntroToHegel.pdf") — so accept substring OR significant-token overlap."""
    nb = _norm(book)
    if not nb:
        return None
    btok = {t for t in nb.split() if len(t) > 3}
    for w in works_norm:
        if not w:
            continue
        if nb == w or nb in w or w in nb:
            return w
        if btok and (btok & {t for t in w.split() if len(t) > 3}):
            return w
    return None


def _count_citations(text):
    """Count citation locators: a middle-dot '·' while inside parentheses,
    tolerating nested parens like (Book (Author) · Page 175)."""
    depth, n = 0, 0
    for ch in (text or ""):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch == "\u00b7" and depth > 0:
            n += 1
    return n


def check(answer, passages):
    passages = passages or []
    ev = _norm(" \u2022 ".join((p.get("text") or "") for p in passages))
    # per-work evidence, so a quote can be grounded against the book it cites
    works_norm = {_norm(p.get("work") or ""): [] for p in passages}
    for p in passages:
        works_norm[_norm(p.get("work") or "")].append(_norm(p.get("text") or ""))
    work_ev = {w: " ".join(v) for w, v in works_norm.items()}
    quotes = _quotes(answer)
    ungrounded, miscited = 0, 0
    for q, line in quotes:
        q = _CITE.sub("", q)              # strip an inline citation from the quote
        cited = _cited_works(line)
        target = ev
        if cited:
            matched = next((m for m in (_work_matches(b, work_ev) for b in cited) if m), None)
            if matched is None:
                # cites a book that is not in the evidence — a fabricated/mismatched locator
                miscited += 1
                ungrounded += 1
                continue
            target = work_ev[matched]
        if _bound(q, target):
            continue
        ungrounded += 1
    cites = _count_citations(answer or "")
    total = max(1, len(quotes))
    return Verdict(grounded=round(1.0 - ungrounded / total, 3), citations=cites,
                   ungrounded=ungrounded,
                   counts={"quotes": len(quotes), "miscited": miscited})


# public aliases — the internals stay private; repair/pipeline use these
norm = _norm
CITE = _CITE
bound = _bound
