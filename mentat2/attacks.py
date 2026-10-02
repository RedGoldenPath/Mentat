"""Attack detection — same-subject candidate gating (bi-encoder) then NLI contradiction."""
from __future__ import annotations
import hashlib
import numpy as np
from dataclasses import asdict
from . import gateway, store
from .contracts import Attack


def _norm(x):
    n = np.linalg.norm(x)
    return x / n if n else x


# Attack graph cache: the contradiction structure over a given claim set is stable,
# so recomputing NLI for the same passages on a repeat query is wasted work.
_CACHE: dict = {}
_CACHE_MAX = 64


def find_attacks(claims, profile="online"):
    """Return (attacks, states). Direction: the less-entrenched claim attacks the more."""
    if len(claims) < 2:
        return [], {}
    sig = tuple(sorted(c.id for c in claims))
    cached = _CACHE.get(sig)
    if cached is not None:
        return list(cached), {}
    texts = [c.text for c in claims]
    try:
        embs = gateway.embed(texts)
        embs = np.vstack([_norm(e) for e in embs])
        sim = embs @ embs.T
    except Exception:
        sim = np.ones((len(claims), len(claims)))

    # candidate pairs that pass the same-subject gate, then ONE batched NLI pass
    cand = []
    for i in range(len(claims)):
        for j in range(i + 1, len(claims)):
            if sim[i][j] < 0.32 and claims[i].work != claims[j].work:
                continue
            cand.append((i, j))
    if not cand:
        _CACHE[sig] = []
        return [], {}
    try:
        judged = gateway.nli_batch([(claims[i].text, claims[j].text) for i, j in cand])
    except Exception:
        judged = [("neutral", 0.0)] * len(cand)

    attacks = []
    seen = set()
    for (i, j), (label, conf) in zip(cand, judged):
        if label != "contradiction" or conf < 0.5:
            continue
        # attacker = less entrenched; target = more entrenched (the position)
        if claims[i].entrenchment >= claims[j].entrenchment:
            src, dst = claims[j], claims[i]
        else:
            src, dst = claims[i], claims[j]
        key = (src.id, dst.id)
        if key in seen:
            continue
        seen.add(key)
        same_work = src.work == dst.work
        scope = "immanent" if same_work else "cross-work"
        # immanence: same work, or a same-subject cross-work contradiction (cosine)
        immanent = bool(same_work or sim[i][j] >= 0.55)
        aid = hashlib.md5(("|".join(key)).encode()).hexdigest()[:16]
        atk = Attack(id=aid, src=src.id, dst=dst.id, kind="rebut",
                     scope=scope, confidence=round(float(conf), 3),
                     immanent=immanent)
        store.save_attack(atk)
        attacks.append(asdict(atk))
    _CACHE[sig] = attacks
    if len(_CACHE) > _CACHE_MAX:
        _CACHE.pop(next(iter(_CACHE)))
    return attacks, {}
