"""Offline scorecard: aggregate all eval artifacts into one view.

Reads what the runs produced (no model calls):
  mentat2_data/eval/v2.json                  — v2 online vs v1
  mentat2_data/eval/h2h/*/rows.json          — writer head-to-heads
  mentat2_data/eval/thinker/rows.json        — thinker-only test
and writes mentat2_data/eval/scorecard.json + a readable table.

Usage: python -m mentat2.eval.scorecard
"""
from __future__ import annotations
import glob
import json
from statistics import mean

from .. import config

EVAL = config.V2_DATA / "eval"


def _mean(rows, key):
    v = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
    return round(mean(v), 2) if v else None


def _summarize(rows, label):
    if not rows:
        return None
    sec = [r["secs"] for r in rows if isinstance(r.get("secs"), (int, float))]
    return {
        "label": label,
        "n": len(rows),
        "latency_mean": round(mean(sec), 1) if sec else None,
        "movement": _mean(rows, "movement"),
        "quality": _mean(rows, "quality"),
        "grounded": _mean(rows, "grounded"),
        "faithfulness": _mean(rows, "faithfulness"),
        "ungrounded": sum(int(r.get("ungrounded") or 0) for r in rows),
        "miscited": sum(int(r.get("miscited") or 0) for r in rows),
        "inv_ok": sum(1 for r in rows if r.get("invariants_ok")),
    }


def collect():
    out = {}
    p = EVAL / "v2.json"
    if p.exists():
        out["v2_online"] = _summarize(json.loads(p.read_text()), "v2 (online)")
    for f in sorted(glob.glob(str(EVAL / "h2h" / "*" / "rows.json"))):
        doc = json.loads(open(f).read())
        out["h2h_" + doc.get("model", f)] = _summarize(doc["rows"], doc.get("model", "?"))
    p = EVAL / "thinker" / "rows.json"
    if p.exists():
        rows = json.loads(p.read_text())
        for model in sorted({r["model"] for r in rows}):
            out["thinker_" + model] = _summarize([r for r in rows if r["model"] == model],
                                                 f"thinker {model}")
    p = EVAL / "h2h" / "scorecard.json"
    if p.exists():
        sc = json.loads(p.read_text())
        out["pairwise_moe_vs_mlx"] = sc.get("pairwise")
    return out


def main():
    data = collect()
    (EVAL / "scorecard.json").write_text(json.dumps(data, ensure_ascii=False, indent=1))
    print(f"{'arm':<34} {'n':>2} {'lat':>6} {'mov':>4} {'qual':>4} {'faith':>5} {'gr':>4} {'ungr':>4} {'inv':>4}")
    for k, s in data.items():
        if not isinstance(s, dict) or "movement" not in s:
            print(f"{k:<34} {s}")
            continue
        print(f"{k:<34} {s['n']:>2} {str(s['latency_mean']):>6} {str(s['movement']):>4} "
              f"{str(s['quality']):>4} {str(s.get('faithfulness')):>5} {str(s['grounded']):>4} "
              f"{s['ungrounded']:>4} {s['inv_ok']:>4}")
    print(f"\nwritten: {EVAL / 'scorecard.json'}")


if __name__ == "__main__":
    main()
