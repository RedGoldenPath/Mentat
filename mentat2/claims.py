"""Claim extraction — one proposition per passage, batched (1 model call), cached."""
from __future__ import annotations
import hashlib
import json
import re
from . import gateway, store
from .contracts import Claim

_PROMPT = (
    "For each numbered passage, state its single central CLAIM as one plain declarative "
    "sentence in the passage's own terms. Return ONLY a JSON object mapping the number to "
    'the sentence, e.g. {{"1":"...","2":"..."}}. No preamble.\n\n{body}'
)


def _id(chunk_id, text):
    return hashlib.md5((str(chunk_id) + "|" + text).encode("utf-8")).hexdigest()[:16]


def _first_sentence(txt):
    s = re.split(r"(?<=[.!?])\s+", (txt or "").strip())
    return (s[0] if s and s[0] else (txt or ""))[:300]


def claims_for_passages(passages, profile, model, max_score=None):
    if not passages:
        return []
    if max_score is None:
        max_score = max((p.get("score") or 0.0) for p in passages) or 1.0

    # split cached vs uncached, preserving order
    texts = {}
    for p in passages:
        cid = p.get("chunk_id")
        if not cid:
            continue
        cached = store.load_claims_for_chunks([cid])
        if cached:
            texts[cid] = cached[0]["text"]
        else:
            texts.setdefault(cid, None)

    todo = [p for p in passages if p.get("chunk_id") and texts.get(p.get("chunk_id")) is None]
    if todo:
        body = "\n\n".join(f"[{i}] {(p.get('text') or '')[:1800]}" for i, p in enumerate(todo, 1))
        claims_map = {}
        try:
            raw = gateway.chat(_PROMPT.format(body=body), profile=profile, model=model, job="extraction",
                               max_tokens=900, temperature=0.2,
                               json_schema={"type": "object",
                                            "additionalProperties": {"type": "string"}})
            m = re.search(r"\{.*\}", raw or "", re.S)
            if m:
                claims_map = json.loads(m.group(0))
        except Exception:
            claims_map = {}
        for i, p in enumerate(todo, 1):
            cid = p["chunk_id"]
            c = str(claims_map.get(str(i)) or claims_map.get(i) or "").strip().strip('"')
            if not (8 <= len(c) <= 400):
                c = _first_sentence(p.get("text"))
            if not c:
                continue
            texts[cid] = c
            store.save_claim(Claim(id=_id(cid, c), text=c, chunk_id=cid,
                                   work=p.get("work", ""), loc=p.get("loc", "")))

    out = []
    for p in passages:
        cid = p.get("chunk_id")
        text = texts.get(cid)
        if not text:
            continue
        ent = float(p.get("score") or 0.0) / max_score if max_score else 0.5
        out.append(Claim(id=_id(cid, text), text=text, chunk_id=cid,
                         work=p.get("work", ""), loc=p.get("loc", ""),
                         entrenchment=max(0.05, min(1.0, ent))))
    return out
