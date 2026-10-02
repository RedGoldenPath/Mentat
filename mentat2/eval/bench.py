"""Controlled per-stage benchmark — find each subsystem's floor and any flaw.

Runs every stage in isolation with fixed inputs so a slow/broken stage is obvious,
plus a retrieval-quality check against known expected books. Default profile: online
(so local model variance doesn't hide systemic issues) — but note the helper models
(embed / rerank / NLI) are always local cross-encoders.

Usage: python -m mentat2.eval.bench [--profile online|local]
"""
from __future__ import annotations
import argparse
import time

from .. import config, router, retrieve, claims as claims_mod, attacks as attacks_mod
from .. import loop, writer, verify, gateway
from ..contracts import Session


def _t(fn):
    t0 = time.time()
    out = fn()
    return out, round((time.time() - t0) * 1000, 1)   # ms


QUALITY = [
    ("find: the litany against fear", "Dune"),
    ("I must not fear. Fear is the mind-killer", "Dune"),
    ("Why does Ibn Khaldun's group feeling destroy the dynasty it builds?", "Muqaddimah"),
    ("What does the Quran say about usury?", "Quran"),
    ("Does the master win the struggle for recognition?", "Kojeve"),
    ("the state is born of class antagonism", "state-and-revolution"),
    ("Leto II and the Golden Path", "God Emperor"),
    ("Muad'Dib and the Fremen", "Dune"),
]


def retrieval_quality(k=6):
    print("=== retrieval quality (top-1 book correct?) ===")
    top1 = 0
    ink = 0
    for q, book in QUALITY:
        ps, ms = _t(lambda: retrieve.retrieve(q, k=k))
        works = " ".join(p.get("work", "") for p in ps).lower()
        t1 = bool(ps) and book.lower() in (ps[0].get("work", "") or "").lower()
        anywhere = book.lower() in works
        top1 += t1
        ink += anywhere
        print(f"  [{'T1 ' if t1 else ('k  ' if anywhere else 'MISS')}] {ms:>7}ms  "
              f"top={ps[0]['work'][:34] if ps else '—'}")
    print(f"  top-1 {top1}/{len(QUALITY)} · in-top-{k} {ink}/{len(QUALITY)}\n")
    return top1, ink


def census_check():
    print("=== census correctness ===")
    import re
    from .. import store
    phrase = "mercy"
    c = retrieve.census(phrase)
    # independent recount straight from the library
    n = 0
    for r in store.v1("library").execute("SELECT content FROM chunks"):
        n += re.sub(r"\s+", " ", (r["content"] or "").lower()).count(phrase)
    ok = c["total"] == n
    print(f"  [{'ok ' if ok else 'MISMATCH'}] census={c['total']} direct={n}\n")


def stage_floors(q):
    print("=== per-stage floors (online) ===")
    settings = {"profile": "online", "top_k": 6, "max_rounds": 2}
    route = router.route(q, settings)

    b, ms_b = _t(lambda: retrieve.bm25(q, k=18))
    v, ms_v = _t(lambda: retrieve.vector(q, k=18))
    ps, ms_r = _t(lambda: retrieve.retrieve(q, k=6, budget_chars=route.context_budget))
    print(f"  bm25      {ms_b:>7}ms  n={len(b)}")
    print(f"  vector    {ms_v:>7}ms  n={len(v)}   (embed=knn; embed model local)")
    print(f"  retrieve  {ms_r:>7}ms  n={len(ps)}  (bm25+vector+rrf+rerank)")
    if not ps:
        print("  no passages; aborting stage test")
        return

    cl, ms_c = _t(lambda: claims_mod.claims_for_passages(ps, "online", config.DEEPSEEK_FLASH))
    print(f"  claims    {ms_c:>7}ms  n={len(cl)}")
    (atk, _states), ms_a = _t(lambda: attacks_mod.find_attacks(cl, "online"))
    print(f"  attacks   {ms_a:>7}ms  n={len(atk)}  (NLI cross-encoder, local)")
    sess = Session(query=q, route=route)
    sess, ms_l = _t(lambda: loop.run(sess, cl, atk, route, max_rounds=2, brief_model=config.DEEPSEEK_FLASH))
    print(f"  loop      {ms_l:>7}ms  rungs={len(sess.rounds)}  (sublation calls)")
    ans, ms_w = _t(lambda: writer.render_dialectical(sess, ps, "online", config.DEEPSEEK_FLASH, think=False))
    print(f"  writer    {ms_w:>7}ms  chars={len(ans or '')}")
    _, ms_vf = _t(lambda: verify.check(ans, ps))
    print(f"  verify    {ms_vf:>7}ms")

    total = ms_b + ms_r + ms_c + ms_a + ms_l + ms_w
    print(f"  ~total (sum of stages) {total:>7}ms\n")
    return {"retrieve": ms_r, "claims": ms_c, "attacks": ms_a, "loop": ms_l,
            "writer": ms_w, "verify": ms_vf}


def helper_load_floors():
    print("=== helper-model load floors (first call includes load) ===")
    # rerank (bge cross-encoder)
    docs = ["a passage about fear", "a passage about recognition"]
    _, ms1 = _t(lambda: gateway.rerank("fear", docs))
    _, ms2 = _t(lambda: gateway.rerank("fear", docs))
    print(f"  rerank first={ms1}ms warm={ms2}ms")
    _, ms1 = _t(lambda: gateway.nli("the master wins", "the master loses"))
    _, ms2 = _t(lambda: gateway.nli("the master wins", "the master loses"))
    print(f"  nli    first={ms1}ms warm={ms2}ms")
    _, ms1 = _t(lambda: gateway.embed(["hello world"]))
    _, ms2 = _t(lambda: gateway.embed(["hello world"]))
    print(f"  embed  first={ms1}ms warm={ms2}ms\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="online")
    a = ap.parse_args()
    q = "Does the master win or lose by winning the struggle for recognition?"
    print(f"profile={a.profile}\n")
    retrieval_quality()
    census_check()
    stage_floors(q)
    helper_load_floors()


if __name__ == "__main__":
    main()
