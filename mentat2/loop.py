"""The dialectical SPIRAL (not a triad).

One turn: an immediate determination -> its own immanent contradiction -> Aufhebung
(cancel / preserve / raise) -> the product becomes the NEXT immediate -> the Return
re-weights the parts by the whole. It climbs until Totality: no grounded new
contradiction remains (nothing immediate left to mediate). See TRUTH.md §dialectic.

The engine computes the movement (contradiction, cancel, preserve, new immediacy,
Return); the model proposes only the raised product (sublation.build).
"""
from __future__ import annotations
import copy
import hashlib
import re
from . import semantics, sublation as sub, gateway, invariants
from .contracts import Round, Sublation, Claim

# The computed movement (the spiral) is a pure function of (query, evidence, brief
# model, max_rounds) — it does NOT depend on the conversation. So it is safe to cache
# and reuse across turns/regenerations; only the writer re-samples prose. This skips
# the sublation calls on repeats (a lossless speedup).
_MOVE_CACHE: dict = {}
_MOVE_MAX = 64


def _move_sig(session, claims, max_rounds, brief_model):
    cids = "|".join(sorted(c.chunk_id for c in claims))
    raw = f"{(session.query or '').strip().lower()}|{brief_model}|{max_rounds}|{cids}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _id(*parts):
    return hashlib.md5("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:16]


def _tokens(s):
    return {w for w in re.findall(r"[a-z0-9']+", (s or "").lower()) if len(w) > 2}


def _overlap(a, b):
    """Token-set overlap relative to the smaller side (0-1). Near 1 means the product
    is a restatement of the immediate — a fixed point, not an advance."""
    A, B = _tokens(a), _tokens(b)
    if not A or not B:
        return 0.0
    return len(A & B) / min(len(A), len(B))


def _return_to_fixed_point(product, claims, pos_id, attacks, labels, iters=4, eps=1e-6):
    """THE RETURN: the raised whole re-determines the parts. Re-weight each claim by
    how it now stands to the product, recompute the grounded labelling, and iterate to
    a fixed point (the labelling stabilises once weights stop moving). ``labels`` are
    the pre-computed NLI results (product, claim) — computed once, batched."""
    state = {}
    for _ in range(iters):
        before = [c.entrenchment for c in claims]
        for c in claims:
            if c.id == pos_id:
                continue
            label, _conf = labels.get(c.id, ("neutral", 0.0))
            if label == "entailment":
                c.entrenchment = min(1.0, c.entrenchment + 0.1)
            elif label == "contradiction":
                c.entrenchment = max(0.05, c.entrenchment - 0.1)
        state = semantics.grounded([c.id for c in claims], attacks)
        if max((abs(c.entrenchment - b) for c, b in zip(claims, before)), default=0.0) < eps:
            break
    return {"state": state, "labels": labels}


def run(session, claims, attacks, route, max_rounds=3, brief_model=""):
    if not claims:
        return session
    brief_model = brief_model or route.writer
    sig = _move_sig(session, claims, max_rounds, brief_model)
    hit = _MOVE_CACHE.get(sig)
    if hit is not None:
        session.rounds = copy.deepcopy(hit)
        return session
    by = {c.id: c for c in claims}
    all_attacks = list(attacks)
    rounds = []

    # the initial immediate: the most entrenched determination (the given)
    pos = max(claims, key=lambda c: c.entrenchment)
    pos_id = pos.id

    for r in range(max_rounds):
        # MOMENT 1/2 — the position and its OWN contradiction (immanent preferred)
        negs = [a for a in all_attacks if a["dst"] == pos_id and a.get("immanent")]
        if not negs:
            negs = [a for a in all_attacks if a["dst"] == pos_id]
        if not negs:
            # no contradiction in the material: the immediate stands; the spiral
            # cannot turn. This is NOT a dialectical stop (Totality) — flag it.
            rounds.append(Round(immediate=pos.text, negation="",
                                sublation=Sublation(immediate=pos.text, product=pos.text),
                                parent=r - 1, invariants_ok=False,
                                violations=["no immanent contradiction on the position"]))
            break
        neg = max(negs, key=lambda a: (bool(a.get("immanent")), a["confidence"]))
        neg_claim = by.get(neg["src"])
        if neg_claim is None:
            break

        # MOMENT 3 — Aufhebung. The model proposes the product; the engine computes
        # cancel (the negated one-sided aspect) and preserve (what the product entails).
        s = sub.build(pos.text, neg_claim.text, [c.text for c in claims],
                      route.profile, brief_model or route.writer)
        product = (s.get("product") or "").strip() or pos.text
        raised_id = _id("raised", product, r)

        cancelled = [neg_claim.text[:280]]
        # ONE batched NLI pass over (product, claim) for the whole turn — used for both
        # preservation and the new immediacy, and reused by the Return.
        others = [c for c in claims if c.id != pos_id]
        try:
            res = gateway.nli_batch([(product, c.text) for c in others])
            labels = {c.id: r for c, r in zip(others, res)}
        except Exception:
            labels = {c.id: ("neutral", 0.0) for c in others}

        preserved = [c.text[:280] for c in others
                     if labels[c.id][0] == "entailment" and labels[c.id][1] > 0.5]
        if not preserved and s.get("preserved"):
            preserved = [str(s["preserved"])[:280]]
        if not preserved:
            # the position's own truth is always preserved in the product
            preserved = [pos.text[:280]]

        # the new immediacy: what the product contradicts (grounded, via NLI)
        newc = [[raised_id, c.id, round(float(labels[c.id][1]), 3)] for c in others
                if labels[c.id][0] == "contradiction" and labels[c.id][1] > 0.5]

        # THE RETURN
        ret = _return_to_fixed_point(product, claims, pos_id, all_attacks, labels)
        state2 = ret["state"]

        changed = _overlap(product, pos.text) < 0.9
        rd = {"changed": changed, "raised": product[:280],
              "position_text": pos.text[:220], "negation_text": neg_claim.text[:220],
              "preserved_n": len(preserved),
              "state": {"in": len(state2["in"]), "out": len(state2["out"]),
                        "undec": len(state2["undec"])}}

        # the new immediacy (text) — Totality test is "no grounded new contradiction"
        totality = not newc
        sub_obj = Sublation(immediate=pos.text, cancelled=cancelled, preserved=preserved,
                            product=product, raised=[raised_id], new_immediate=newc)
        rnd = Round(immediate=pos.text, negation=neg_claim.text, sublation=sub_obj,
                    return_delta=rd,
                    next_immediate=([pos_id] if totality else [nc[1] for nc in newc]),
                    parent=r - 1)

        # INVARIANTS (observe): a valid turn must negate immanently, cancel AND
        # preserve, raise one determinate product, execute the Return, and either
        # produce the next immediacy or reach Totality.
        ok, viol = invariants.check_turn(
            immanent=bool(neg.get("immanent")), cancelled=cancelled,
            preserved=preserved, product=product, return_delta=rd,
            new_immediate=newc, totality=totality, changed=changed)
        rnd.invariants_ok, rnd.violations = ok, viol
        rounds.append(rnd)

        # Totality: nothing immediate left to mediate -> the spiral closes.
        if totality:
            break
        if not changed:
            break

        # the product is the next immediate (carrying the preserved, not replacing it)
        nc_claim = Claim(id=raised_id, text=product, chunk_id=pos.chunk_id,
                         work=pos.work, loc=pos.loc,
                         entrenchment=max(pos.entrenchment, neg_claim.entrenchment),
                         span_start=getattr(pos, "span_start", 0),
                         span_end=getattr(pos, "span_end", 0),
                         page=getattr(pos, "page", 0), mediated=True)
        by[raised_id] = nc_claim
        for a, b, c in newc:                 # a = product id, b = the claim it contradicts
            # the product's own new contradiction must negate the product at the next
            # rung: direct it ONTO the product (dst = product), immanent.
            all_attacks.append({"id": _id("atk", b, a), "src": b, "dst": a,
                                "kind": "rebut", "scope": "immanent",
                                "confidence": c, "immanent": True})
        pos, pos_id = nc_claim, raised_id

    session.rounds = rounds
    _MOVE_CACHE[sig] = copy.deepcopy(rounds)
    if len(_MOVE_CACHE) > _MOVE_MAX:
        _MOVE_CACHE.pop(next(iter(_MOVE_CACHE)))
    return session
