"""Head-to-head: run the eval cases under two offline writers and compare.

Per model: unload the others, RAM-guard, run `ask` over the cases, record latency +
deterministic grounding, and judge quality online. Then a bias-swapped pairwise.

Usage:
  python -m mentat2.eval.head2head run --model qwen3.5:35b-a3b-nvfp4 --tag moe --limit 6
  python -m mentat2.eval.head2head run --model qwen3.8:27b-mlx        --tag mlx --limit 6
  python -m mentat2.eval.head2head compare --a moe --b mlx
"""
from __future__ import annotations
import argparse
import json
import subprocess
import time
from pathlib import Path
from statistics import mean, median

from .. import config, gateway
from .cases import DIALECTIC
from .judge import judge, judge_pairwise

OUT = config.V2_DATA / "eval" / "h2h"


def _free_pct():
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
        return [m.get("name") or m.get("model") for m in gateway._ollama().list().get("models", [])
                if m.get("size_vram") or m.get("size")]
    except Exception:
        return []


def run(model, tag, limit=6, max_rounds=2, profile="local"):
    OUT.mkdir(parents=True, exist_ok=True)
    d = OUT / tag
    d.mkdir(exist_ok=True)
    if profile == "local":
        # unload the other heavy models to honour one-at-a-time
        others = [m for m in _loaded() if m and m != model]
        if others:
            gateway.unload_local(*others)
            time.sleep(3)
        free = _free_pct()
        if free < 35:
            raise SystemExit(f"aborting: free memory {free}% < 35%")
    settings = {"profile": profile, "writer": model, "max_rounds": max_rounds,
                "writer_think": True, "repair": True}
    rows = []
    for i, q in enumerate(DIALECTIC[:limit], 1):
        from .. import ask
        t = time.time()
        try:
            s = ask(q, settings=settings)
            ans, secs, v = s.answer, time.time() - t, s.verdict
            rounds = len(s.rounds)
            inv_ok = all(r.invariants_ok for r in s.rounds) if s.rounds else None
        except Exception as e:
            ans, secs, v, rounds, inv_ok = f"[error {e}]", time.time() - t, None, 0, None
        g = judge(q, ans)
        try:
            from . import metrics
            faith = metrics.faithfulness(ans, getattr(s, "evidence", []))
        except Exception:
            faith = None
        row = {"n": i, "q": q, "secs": round(secs, 1), "rounds": rounds,
               "grounded": getattr(v, "grounded", None),
               "citations": getattr(v, "citations", None),
               "ungrounded": getattr(v, "ungrounded", None),
               "miscited": (getattr(v, "counts", {}) or {}).get("miscited"),
               "invariants_ok": inv_ok, "faithfulness": faith,
               "movement": g["movement"], "quality": g["quality"]}
        rows.append(row)
        (d / f"{i:02d}.md").write_text(f"# {q}\n\n{ans or ''}", encoding="utf-8")
        print(f"[{tag} {i}/{limit}] {row['secs']}s mov={row['movement']} q={row['quality']} "
              f"gr={row['grounded']} inv={row['invariants_ok']} | {q[:40]}", flush=True)
    (d / "rows.json").write_text(json.dumps({"model": model or profile, "rows": rows}, ensure_ascii=False, indent=1))
    if profile == "local" and model:
        gateway.unload_local(model)
    return rows


def compare(a, b):
    ra = json.loads((OUT / a / "rows.json").read_text())
    rb = json.loads((OUT / b / "rows.json").read_text())
    A = {r["n"]: r for r in ra["rows"]}
    B = {r["n"]: r for r in rb["rows"]}

    def summ(rows, model="?"):
        g = [r for r in rows if isinstance(r.get("grounded"), (int, float))]
        m = [r for r in rows if isinstance(r.get("movement"), (int, float))]
        q = [r for r in rows if isinstance(r.get("quality"), (int, float))]
        sec = [r["secs"] for r in rows if isinstance(r.get("secs"), (int, float))]
        return {
            "model": model,
            "n": len(rows),
            "latency_mean": round(mean(sec), 1) if sec else None,
            "latency_median": round(median(sec), 1) if sec else None,
            "movement_mean": round(mean([r["movement"] for r in m]), 2) if m else None,
            "quality_mean": round(mean([r["quality"] for r in q]), 2) if q else None,
            "grounded_mean": round(mean([r["grounded"] for r in g]), 2) if g else None,
            "ungrounded": sum(int(r.get("ungrounded") or 0) for r in rows),
            "miscited": sum(int(r.get("miscited") or 0) for r in rows),
            "inv_ok": sum(1 for r in rows if r.get("invariants_ok")),
        }

    wins = {"a": 0, "b": 0, "tie": 0}
    pair_rows = []
    for n in sorted(set(A) & set(B)):
        pa = OUT / a / f"{n:02d}.md"
        pb = OUT / b / f"{n:02d}.md"
        if not (pa.exists() and pb.exists()):
            continue
        aa = pa.read_text().split("\n", 1)[-1]
        bb = pb.read_text().split("\n", 1)[-1]
        w = judge_pairwise(A[n]["q"], aa, bb)      # first=A(model a), second=B(model b)
        key = {"first": "a", "second": "b", "tie": "tie"}[w]
        wins[key] += 1
        pair_rows.append({"n": n, "winner": key, "q": A[n]["q"]})

    score = {"a": summ(ra["rows"], ra.get("model")), "b": summ(rb["rows"], rb.get("model")),
             "pairwise": wins, "pairwise_rows": pair_rows}
    (OUT / "scorecard.json").write_text(json.dumps(score, ensure_ascii=False, indent=1))
    print("\n=== head-to-head ===")
    for k in ("a", "b"):
        s = score[k]
        print(f"  {s['model']:<26} lat(mean/med)={s['latency_mean']}/{s['latency_median']} "
              f"mov={s['movement_mean']} qual={s['quality_mean']} gr={s['grounded_mean']} "
              f"ungr={s['ungrounded']} miscited={s['miscited']} inv_ok={s['inv_ok']}/{s['n']}")
    print(f"  pairwise: a={wins['a']} b={wins['b']} tie={wins['tie']}")
    return score


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("run"); r.add_argument("--model", default="")
    r.add_argument("--tag", required=True); r.add_argument("--limit", type=int, default=6)
    r.add_argument("--max-rounds", type=int, default=2)
    r.add_argument("--profile", default="local", choices=["local", "online"])
    c = sub.add_parser("compare"); c.add_argument("--a", required=True); c.add_argument("--b", required=True)
    a = ap.parse_args()
    if a.cmd == "run":
        run(a.model, a.tag, a.limit, a.max_rounds, a.profile)
    elif a.cmd == "compare":
        compare(a.a, a.b)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
