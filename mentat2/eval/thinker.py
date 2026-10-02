"""Thinker-only test: which model should propose the raised product (the `brief` job)?

Holds retrieval/claims/attacks fixed and varies ONLY the sublation model, then judges
the resulting movement (the product + new immediacy) with the online judge. This isolates
the thinker from the writer (no writer generation at all).

Usage: python -m mentat2.eval.thinker --limit 3
"""
from __future__ import annotations
import argparse
import copy
import json
import time
from statistics import mean

from .. import config, gateway, retrieve, claims as claims_mod, attacks as attacks_mod, loop
from ..contracts import Session, Route
from .cases import DIALECTIC
from .judge import judge

OUT = config.V2_DATA / "eval" / "thinker"
THINKERS = ["qwen2.5:7b", "qwen3.5:35b-a3b-nvfp4", "qwen3.8:27b-mlx"]


def _free_pct():
    import subprocess
    try:
        out = subprocess.run(["memory_pressure"], capture_output=True, text=True, timeout=10).stdout
        for line in out.splitlines():
            if "free percentage" in line.lower():
                return int(line.split(":")[-1].strip().rstrip("%"))
    except Exception:
        pass
    return 100


def _loaded():
    try:
        return [m.get("name") or m.get("model") for m in gateway._ollama().list().get("models", [])]
    except Exception:
        return []


def movement_text(session):
    parts = []
    for i, r in enumerate(session.rounds, 1):
        s = r.sublation
        parts.append(f"[rung {i}] immediate: {r.immediate}\n"
                     f"contradiction: {r.negation}\n"
                     f"cancelled: {s.cancelled}\npreserved: {s.preserved}\n"
                     f"PRODUCT: {s.product}\nnew immediacy: {s.new_immediate}")
    return "\n\n".join(parts) or "(no movement)"


def run(limit=3, max_rounds=2):
    OUT.mkdir(parents=True, exist_ok=True)
    qs = DIALECTIC[:limit]
    rows = []
    for model in THINKERS:
        others = [m for m in _loaded() if m and m != model]
        if others:
            gateway.unload_local(*others)
            time.sleep(3)
        free = _free_pct()
        if free < 35:
            raise SystemExit(f"aborting: free {free}% < 35%")
        for i, q in enumerate(qs, 1):
            # fixed substrate (same across thinkers)
            passages = retrieve.retrieve(q, k=8, budget_chars=12000)
            base_claims = claims_mod.claims_for_passages(
                passages, "local", config.OLLAMA_FAST_MODEL)
            atk, _ = attacks_mod.find_attacks(base_claims, "local")
            route = Route(profile="local", mode="dialectic", context_budget=12000, writer=model)
            sess = Session(query=q, route=route)
            t = time.time()
            try:
                loop.run(sess, copy.deepcopy(base_claims), copy.deepcopy(atk), route,
                         max_rounds=max_rounds, brief_model=model)
                secs = time.time() - t
            except Exception as e:
                secs = time.time() - t
                rows.append({"model": model, "n": i, "q": q, "secs": round(secs, 1),
                             "rounds": 0, "invariants_ok": None,
                             "movement": None, "quality": None, "note": str(e)[:80]})
                continue
            mt = movement_text(sess)
            g = judge(q, mt)
            inv = all(r.invariants_ok for r in sess.rounds) if sess.rounds else None
            try:
                from . import metrics
                faith = metrics.faithfulness(mt, passages)
            except Exception:
                faith = None
            row = {"model": model, "n": i, "q": q, "secs": round(secs, 1),
                   "rounds": len(sess.rounds), "invariants_ok": inv,
                   "movement": g["movement"], "quality": g["quality"],
                   "faithfulness": faith}
            rows.append(row)
            print(f"[{model:<26} {i}/{limit}] {row['secs']}s rungs={row['rounds']} "
                  f"inv={inv} mov={row['movement']} q={row['quality']}", flush=True)
        gateway.unload_local(model)
    (OUT / "rows.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))

    print("\n=== thinker-only (movement of the product) ===")
    for model in THINKERS:
        rs = [r for r in rows if r["model"] == model]
        mv = [r["movement"] for r in rs if isinstance(r.get("movement"), (int, float))]
        ql = [r["quality"] for r in rs if isinstance(r.get("quality"), (int, float))]
        sec = [r["secs"] for r in rs if isinstance(r.get("secs"), (int, float))]
        ok = sum(1 for r in rs if r.get("invariants_ok"))
        print(f"  {model:<26} mov={mean(mv):.2f} qual={mean(ql):.2f} "
              f"sec={mean(sec):.1f} inv_ok={ok}/{len(rs)}" if mv else f"  {model}: no data")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=3)
    ap.add_argument("--max-rounds", type=int, default=2)
    a = ap.parse_args()
    run(a.limit, a.max_rounds)


if __name__ == "__main__":
    main()
