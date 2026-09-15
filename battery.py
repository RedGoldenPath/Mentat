#!/usr/bin/env python
"""Durable quality + RAM battery for Mentat.

Runs a fixed holdout through the REAL ask() pipeline (offline/local by default)
and scores quality and memory the same way every time, so we can iterate on
pipeline levers and keep only changes that do not regress.

Metrics per question:
  citations   inline (Book · location) anchors
  ungrounded  quotes the verifier could not match (⟪…⟫ markers)
  refused     honest "not in the library" answers
  seconds     wall clock
  served      which model answered (offline should show a qwen tag)

Usage:
  .venv/bin/python battery.py                 # offline battery (7 Qs)
  .venv/bin/python battery.py --group poison  # poison/refusal traps
  .venv/bin/python battery.py --group all
  .venv/bin/python battery.py --online        # use the online synth instead
"""
import argparse
import asyncio
import json
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import brain_core as bc  # noqa: E402

CITE_RE = re.compile(r"\([^()\n]{3,90} · [^()\n]{1,90}\)")
REFUSAL = (
    "not in", "no such", "does not contain", "doesn't contain", "do not contain",
    "no passage", "cannot find", "can't find", "couldn't find", "not present",
    "not indexed", "no mention", "no scene", "isn't in", "is not in", "no quote",
    "does not include", "doesn't include", "no record", "nothing in", "absent",
    "no verse", "not reproduced", "no occurrence", "not included",
)

BATTERY = [
    "find: the litany against fear",
    "find: eys of ibad",
    "How many times does the word mercy appear in the Quran",
    "list me all the times allah or god is mentioned in the quran",
    "I half remember a line about a beginning being a delicate time — find it in my library",
    "Who is Leto II's father?",
    "Compare Ibn Khaldun's concept of asabiyyah with the Fremen tribal cohesion in Dune. What do they share?",
]
POISON = [
    "Quote the passage from my library where Nietzsche discusses the eternal recurrence. Cite book and chapter.",
    "What does Kull wahad mean in Dune?",
]
GROUPS = {"battery": BATTERY, "poison": POISON, "all": BATTERY + POISON}


def _ollama_resident():
    try:
        out = subprocess.run(["ollama", "ps"], capture_output=True, text=True, timeout=10).stdout
        rows = [l for l in out.splitlines()[1:] if l.strip()]
        return rows[0].split()[2] if rows else "none"
    except Exception:
        return "?"


def _free_pct():
    try:
        out = subprocess.run(["memory_pressure"], capture_output=True, text=True, timeout=10).stdout
        m = re.search(r"free percentage:\s*(\d+)", out)
        return int(m.group(1)) if m else -1
    except Exception:
        return -1


def _last_synth_model():
    """The model that actually served the most recent ask (telemetry), not the
    last side-call (summarizer/librarian runs after synthesis)."""
    try:
        con = sqlite3.connect(bc.STORAGE_DIR / "telemetry.db")
        row = con.execute("SELECT model FROM asks ORDER BY id DESC LIMIT 1").fetchone()
        con.close()
        return row[0] if row else ""
    except Exception:
        return ""


def score(answer, seconds, served):
    cites = CITE_RE.findall(answer or "")
    low = (answer or "").lower()
    return {
        "citations": len(cites),
        "ungrounded": (answer or "").count("⟪"),
        "refused": int(any(r in low for r in REFUSAL)),
        "chars": len(answer or ""),
        "seconds": round(seconds, 1),
        "served": served,
    }


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", default="battery", choices=list(GROUPS))
    ap.add_argument("--online", action="store_true", help="do not force offline")
    ap.add_argument("--synth", default="", help="pin synth_model (e.g. deepseek-think) for online A/B")
    ap.add_argument("--only", type=int, default=0, help="1-based index of a single question to run")
    ap.add_argument("--voice", default="", help="voice preset (e.g. dialectic) for A/B")
    ap.add_argument("--temp", type=float, default=0.0, help="sampling temperature (0 = deterministic)")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    orig = bc._load_settings

    def forced():
        s = orig()
        s["temperature"] = args.temp
        if not args.online:
            s["offline"] = True
            s["model"] = "qwen"
        if args.synth:
            s["synth_model"] = args.synth
        if args.voice:
            s["voice"] = args.voice
        return s

    bc._load_settings = forced

    questions = GROUPS[args.group]
    if args.only:
        questions = [questions[args.only - 1]]
    run_id = time.strftime("%Y%m%d-%H%M%S")
    out = Path(args.out) if args.out else bc.STORAGE_DIR / f"battery_{args.group}_{run_id}.jsonl"

    brain = bc.Brain()
    rows = []
    try:
        for i, q in enumerate(questions, 1):
            t0 = time.time()
            try:
                res = await brain.ask(q, lazy=True)
                ans = res.get("answer") or ""
            except Exception as exc:
                ans = ""
                res = {"status": f"error:{type(exc).__name__}"}
            secs = time.time() - t0
            row = {"n": i, "question": q, "status": res.get("status"), **score(ans, secs, _last_synth_model()), "answer": ans}
            rows.append(row)
            print(f"[{i}/{len(questions)}] {row['seconds']:>6}s cites={row['citations']} "
                  f"ungr={row['ungrounded']} refused={row['refused']} served={row['served']} | {q[:50]}", flush=True)
    finally:
        await brain.close()

    with open(out, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    n = len(rows)
    tot_cites = sum(r["citations"] for r in rows)
    cited = sum(1 for r in rows if r["citations"])
    ungr = sum(r["ungrounded"] for r in rows)
    refused = sum(r["refused"] for r in rows)
    avg = sum(r["seconds"] for r in rows) / max(n, 1)
    print("\n=== SUMMARY ===")
    print(f"group={args.group} questions={n}")
    print(f"answered={sum(1 for r in rows if r['answer'].strip())}/{n}  "
          f"with_citations={cited}/{n}  total_citations={tot_cites}")
    print(f"ungrounded_quotes={ungr}  refused={refused}  avg_seconds={avg:.1f}")
    print(f"ollama_resident={_ollama_resident()}  system_free={_free_pct()}%")
    print(f"written: {out}")


asyncio.run(main())
