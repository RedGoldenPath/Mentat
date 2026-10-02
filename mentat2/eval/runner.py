"""Eval runner: run v2 over the cases, or load the v1 answers, judge, and compare."""
from __future__ import annotations
import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from mentat2 import config  # noqa: E402
from mentat2.eval.cases import DIALECTIC  # noqa: E402
from mentat2.eval.judge import judge  # noqa: E402

V1_ONLINE = config.V1_STORAGE / "dia_answers" / "online"
OUT = config.V2_DATA / "eval"


def _load_v1(n):
    p = V1_ONLINE / f"{n:02d}.md"
    if not p.exists():
        return ""
    txt = p.read_text(encoding="utf-8", errors="ignore")
    # answer is after the first '---' line
    parts = txt.split("---", 1)
    return (parts[1] if len(parts) > 1 else txt).strip()


def run_v2(limit=0, rounds=2):
    from mentat2 import ask
    OUT.mkdir(parents=True, exist_ok=True)
    qs = DIALECTIC[:limit] if limit else DIALECTIC
    rows = []
    for i, q in enumerate(qs, 1):
        t = time.time()
        try:
            s = ask(q)
            ans = s.answer
            secs = time.time() - t
            v = s.verdict
            rnds = len(s.rounds)
        except Exception as e:
            ans, secs, v, rnds = f"[error {e}]", time.time() - t, None, 0
        g = judge(q, ans)
        row = {"n": i, "q": q, "secs": round(secs, 1), "rounds": rnds,
               "grounded": getattr(v, "grounded", None),
               "citations": getattr(v, "citations", None),
               "ungrounded": getattr(v, "ungrounded", None),
               "movement": g["movement"], "quality": g["quality"], "note": g["note"]}
        rows.append(row)
        (OUT / f"v2_{i:02d}.md").write_text(f"# {q}\n\n" + (ans or ""), encoding="utf-8")
        print(f"[{i}/{len(qs)}] {row['secs']}s mov={row['movement']} q={row['quality']} "
              f"cites={row['citations']} ungr={row['ungrounded']} | {q[:44]}", flush=True)
    (OUT / "v2.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    return rows


def run_v1_judge(limit=0):
    OUT.mkdir(parents=True, exist_ok=True)
    qs = DIALECTIC[:limit] if limit else DIALECTIC
    rows = []
    for i, q in enumerate(qs, 1):
        ans = _load_v1(i)
        g = judge(q, ans) if ans else {"movement": None, "quality": None, "note": "no v1 answer"}
        row = {"n": i, "q": q, "movement": g["movement"], "quality": g["quality"],
               "note": g["note"], "chars": len(ans)}
        rows.append(row)
        print(f"[{i}] v1 mov={row['movement']} q={row['quality']} chars={row['chars']} | {q[:44]}",
              flush=True)
    (OUT / "v1.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    return rows


def judge_v2():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = json.loads((OUT / "v2.json").read_text()) if (OUT / "v2.json").exists() else []
    idx = {r["n"]: r for r in rows}
    for i, q in enumerate(DIALECTIC, 1):
        p = OUT / f"v2_{i:02d}.md"
        ans = p.read_text(encoding="utf-8", errors="ignore") if p.exists() else ""
        g = judge(q, ans) if ans else {"movement": None, "quality": None, "note": "missing"}
        r = idx.get(i, {"n": i, "q": q})
        r["movement"] = g["movement"]; r["quality"] = g["quality"]; r["note"] = g["note"]
        rows = [x for x in rows if x["n"] != i] + [r]
        print(f"[{i}] v2 mov={g['movement']} q={g['quality']}", flush=True)
    rows.sort(key=lambda r: r["n"])
    (OUT / "v2.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    return rows


def pairwise(limit=0):
    from mentat2.eval.judge import judge_pairwise
    from mentat2.eval.cases import DIALECTIC
    OUT.mkdir(parents=True, exist_ok=True)
    qs = DIALECTIC[:limit] if limit else DIALECTIC
    wins = {"v2": 0, "v1": 0, "tie": 0}
    rows = []
    for i, q in enumerate(qs, 1):
        v1 = _load_v1(i)
        p2 = OUT / f"v2_{i:02d}.md"
        v2 = p2.read_text(encoding="utf-8", errors="ignore") if p2.exists() else ""
        # strip the leading "# question" line
        v2 = v2.split("\n", 1)[1] if "\n" in v2 else v2
        if not v1 or not v2:
            continue
        w = judge_pairwise(q, v1, v2)          # first=v1, second=v2
        key = {"first": "v1", "second": "v2", "tie": "tie"}[w]
        wins[key] += 1
        rows.append({"n": i, "q": q, "winner": key})
        print(f"[{i}] {key} | {q[:46]}", flush=True)
    (OUT / "pairwise.json").write_text(json.dumps({"wins": wins, "rows": rows}, indent=1))
    print("\n=== pairwise v1 vs v2 ===")
    print(f"  v2 wins: {wins['v2']}  v1 wins: {wins['v1']}  ties: {wins['tie']}")
    return wins


def compare():
    v1 = json.loads((OUT / "v1.json").read_text())
    v2 = json.loads((OUT / "v2.json").read_text())
    def avg(rows, k):
        v = [r.get(k) for r in rows if isinstance(r.get(k), (int, float))]
        return round(sum(v) / len(v), 2) if v else None
    print("\n=== v1 vs v2 (judged) ===")
    for k in ("movement", "quality"):
        print(f"  {k}: v1={avg(v1,k)}  v2={avg(v2,k)}")
    sv1 = avg(v1, "chars"); sv2 = avg(v2, "secs")
    print(f"  latency(secs): v1≈(from cache)  v2={sv2}")
    (OUT / "compare.json").write_text(json.dumps({"v1": {k: avg(v1,k) for k in ('movement','quality')},
                                                  "v2": {k: avg(v2,k) for k in ('movement','quality')},
                                                  "v2_secs": sv2}, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--v2", type=int, default=-1, help="run v2 on first N cases (0=all)")
    ap.add_argument("--v1", action="store_true", help="judge the stored v1 answers")
    ap.add_argument("--judge-v2", action="store_true", help="re-judge saved v2 answers")
    ap.add_argument("--pairwise", type=int, default=-1, help="pairwise v1-vs-v2 (0=all)")
    ap.add_argument("--compare", action="store_true")
    a = ap.parse_args()
    if a.v2 >= 0:
        run_v2(limit=a.v2)
    if a.v1:
        run_v1_judge(limit=a.v2 if a.v2 > 0 else 0)
    if a.judge_v2:
        judge_v2()
    if a.pairwise >= 0:
        pairwise(limit=a.pairwise)
    if a.compare:
        compare()


if __name__ == "__main__":
    main()
