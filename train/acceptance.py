#!/usr/bin/env python
"""M4 acceptance gate — pipeline-level, not raw model calls.

Runs a fixed question set through the REAL ask() pipeline for three arms:
  baseline : offline, current qwen3.8:27b
  candidate: offline, the fine-tuned Mentat model (mentat-local in Ollama)
  flash    : online, deepseek-flash (the reference to beat)

Gate (from the plan):
  - candidate inline citations >= 80% of flash's
  - candidate ungrounded-quote markers <= baseline's
  - zero fabricated locations on poison questions (refusal + no invented cites)
  - at least 1 clean refusal of the 2 poison questions
  - answers all questions (no crashes/empties)

Usage:
  .venv/bin/python train/acceptance.py --candidate mentat-local
"""
import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
import brain_core as bc  # noqa: E402

CITE_RE = re.compile(r"\([^()\n]{3,90} · [^()\n]{1,90}\)")
REFUSAL = (
    "not in", "no such", "does not contain", "do not contain", "no passage",
    "cannot find", "can't find", "no mention", "no scene", "is not in",
    "isn't in", "no quote", "does not include", "no verse", "not reproduced",
)
QUESTIONS = [
    "find: the litany against fear",
    "find: eys of ibad",
    "How many times does the word mercy appear in the Quran",
    "What does the Quran say in 2:255 (Ayat al-Kursi)?",
    "Where does Kojeve discuss the Master-Slave dialectic in his Hegel lectures?",
    "Who is Leto II's father?",
    "Compare Ibn Khaldun's concept of asabiyyah with the Fremen tribal cohesion in Dune. What do they share?",
    "Find the scene in Dune where Paul uses a computer and quote it with book and chapter.",
    "Quote the passage from my library where Nietzsche discusses the eternal recurrence. Cite book and chapter.",
    "What does Kull wahad mean in Dune?",
]
POISON_IDS = (7, 8)


def patch_for_model(base="qwen3.8:27b", target="mentat-local"):
    """Redirect the offline synth alias to the candidate model."""
    bc.OLLAMA_LLM_MODEL = target
    presets = getattr(bc, "MODEL_PRESETS", {})
    for key in ("qwen", "qwen-deep"):
        if key in presets:
            presets[key] = target
    orig = bc.resolve_model

    def wrapped(name):
        chosen = orig(name)
        if target != base and chosen == base:
            return target
        return chosen

    bc.resolve_model = wrapped


async def run_arm(name, offline):
    bc.Brain().set_setting("offline", bool(offline))
    brain = bc.Brain()
    rows = []
    for i, q in enumerate(QUESTIONS):
        t0 = time.time()
        try:
            entry = await brain.ask(q)
            answer = str(entry.get("answer") or "")
            status = str(entry.get("status") or "?")
        except Exception as exc:
            answer, status = "", f"EXCEPTION:{type(exc).__name__}"
        dt = time.time() - t0
        low = answer.lower()
        rows.append({
            "i": i,
            "question": q,
            "status": status,
            "seconds": round(dt, 1),
            "chars": len(answer),
            "cites": len(CITE_RE.findall(answer)),
            "ungrounded_markers": answer.count("⟪"),
            "refused": any(p in low for p in REFUSAL),
            "is_poison": i in POISON_IDS,
            "answer": answer,
        })
        print(
            f"[{name}] Q{i:02d} {status:<9} {dt:6.1f}s cites={rows[-1]['cites']:>2} "
            f"ungrounded={rows[-1]['ungrounded_markers']} refused={rows[-1]['refused']}",
            flush=True,
        )
    return rows


def summarize(rows):
    return {
        "answered": sum(1 for r in rows if r["status"] == "answered"),
        "cites": sum(r["cites"] for r in rows),
        "ungrounded": sum(r["ungrounded_markers"] for r in rows),
        "poison_clean": sum(
            1 for r in rows
            if r["is_poison"] and r["refused"] and r["ungrounded_markers"] == 0
        ),
        "avg_seconds": round(sum(r["seconds"] for r in rows) / len(rows), 1),
    }


def verdict(base, cand, flash):
    checks = {
        "answered_all": cand["answered"] == len(QUESTIONS),
        "cites_ge_80pct_flash": cand["cites"] >= 0.8 * flash["cites"],
        "ungrounded_le_baseline": cand["ungrounded"] <= max(base["ungrounded"], 1),
        "poison_ge_1_of_2": cand["poison_clean"] >= 1,
    }
    return checks


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", default="mentat-local")
    ap.add_argument("--skip-baseline", action="store_true")
    ap.add_argument("--skip-flash", action="store_true")
    args = ap.parse_args()

    out = {}
    if not args.skip_baseline:
        patch_for_model(target="qwen3.8:27b")
        base_rows = await run_arm("baseline", offline=True)
        out["baseline"] = {"summary": summarize(base_rows), "rows": base_rows}
    if not args.skip_flash:
        patch_for_model(target="deepseek-flash")
        flash_rows = await run_arm("flash", offline=False)
        out["flash"] = {"summary": summarize(flash_rows), "rows": flash_rows}
    patch_for_model(target=args.candidate)
    cand_rows = await run_arm("candidate", offline=True)
    out["candidate"] = {"summary": summarize(cand_rows), "rows": cand_rows}

    if "baseline" in out and "flash" in out:
        out["verdict"] = verdict(
            out["baseline"]["summary"], out["candidate"]["summary"], out["flash"]["summary"]
        )
    report = Path(__file__).resolve().parent / "acceptance_report.json"
    report.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n=== SUMMARY ===")
    for arm in ("baseline", "flash", "candidate"):
        if arm in out:
            print(f"{arm:<10} {out[arm]['summary']}")
    if "verdict" in out:
        print("VERDICT:", out["verdict"])
    print(f"report: {report}")


asyncio.run(main())
