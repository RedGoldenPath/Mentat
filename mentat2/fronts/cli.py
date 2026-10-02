"""Mentat v2 CLI: ask · probe · census · stats · doctor · index."""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from mentat2 import config, retrieve, telemetry, store  # noqa: E402
from mentat2.pipeline import ask  # noqa: E402


def _print_spiral(session):
    if not session.rounds:
        print("  (no contradiction found in the evidence — the position holds)")
        return
    for i, r in enumerate(session.rounds, 1):
        s = r.sublation
        rd = r.return_delta or {}
        print(f"  rung {i}:")
        print(f"    immediate       : {rd.get('position_text','—')}")
        print(f"    negation        : {rd.get('negation_text','—')}")
        print(f"    cancelled       : {', '.join(str(x) for x in s.cancelled) or '—'}")
        print(f"    preserved       : {len(s.preserved)} kept")
        print(f"    product         : {rd.get('raised','—')}")
        print(f"    new immediate   : {s.new_immediate}")
        print(f"    return          : changed={rd.get('changed')}")
        print(f"    invariants      : {'ok' if r.invariants_ok else r.violations}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mentat2", description="Mentat v2 (dialectical)")
    sub = ap.add_subparsers(dest="cmd")
    a = sub.add_parser("ask"); a.add_argument("question")
    p = sub.add_parser("probe"); p.add_argument("question")
    c = sub.add_parser("census"); c.add_argument("phrase")
    sub.add_parser("stats")
    sub.add_parser("doctor")
    ix = sub.add_parser("index"); ix.add_argument("--limit", type=int, default=0)
    d = sub.add_parser("dialectic"); d.add_argument("question")
    args = ap.parse_args(argv)

    if not args.cmd:
        ap.print_help()
        return 0

    if args.cmd == "doctor":
        from mentat2 import diagnose
        return 0 if all(r.ok for r in diagnose.run()) else 1

    if args.cmd == "index":
        from mentat2 import index as indexer
        indexer.build(limit=args.limit or None)
        print(json.dumps(indexer.status()))
        return 0

    if args.cmd == "stats":
        print("v2 telemetry (recent):")
        for row in telemetry.summary():
            print("  ", row)
        v2 = store.v2()
        for t in ("claims", "attacks", "events", "sessions", "memory"):
            try:
                n = v2.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                print(f"  {t}: {n}")
            except Exception:
                pass
        return 0

    if args.cmd == "probe":
        t = time.time()
        ps = retrieve.retrieve(args.question, k=8)
        print(f"{len(ps)} passages in {time.time()-t:.1f}s")
        for i, x in enumerate(ps, 1):
            print(f"  [{i}] {x.get('work')} · {x.get('loc')}  ({x.get('score'):.2f})")
            print("      " + (x.get("text", "")[:160].replace("\n", " ")))
        return 0

    if args.cmd == "census":
        print(json.dumps(retrieve.census(args.phrase), ensure_ascii=False))
        return 0

    q = args.question
    t = time.time()
    session = ask(q)
    print(f"\nQ: {q}\n{'='*70}")
    print(f"route: mode={session.route.mode} profile={session.route.profile} "
          f"writer={session.route.writer}")
    print("--- spiral ---")
    _print_spiral(session)
    print("--- answer ---\n")
    print(session.answer)
    v = session.verdict
    print(f"\n--- verdict --- grounded={v.grounded} citations={v.citations} "
          f"ungrounded={v.ungrounded} quotes={v.counts.get('quotes')}")
    print(f"total {time.time()-t:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
