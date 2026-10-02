#!/usr/bin/env python
"""Stream the dialectic gold set live, one answer at a time — with resume.

Run it in one terminal, watch it in another:

    .venv/bin/python stream_dialectic.py                 # local qwen, auto mode
    .venv/bin/python stream_dialectic.py --online --synth deepseek-v4-pro
    .venv/bin/python stream_dialectic.py --fresh          # ignore the cache

Watching (any of these):
    tail -f storage/dia_stream.log                       # live log
    open storage/dia_answers/                            # one .md file per answer

Completed answers are cached in storage/dia_cache.json (keyed by mode + question),
so restarting skips what is already done instead of paying for it again.
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import brain_core as bc  # noqa: E402
from battery import DIALECTIC, score  # noqa: E402

CACHE_PATH = bc.STORAGE_DIR / "dia_cache.json"
ANS_DIR = bc.STORAGE_DIR / "dia_answers"


def _ans_dir(mode_key):
    return ANS_DIR / "online" if mode_key.startswith("online") else ANS_DIR


def _load_cache():
    try:
        return json.loads(CACHE_PATH.read_text())
    except Exception:
        return {}


def _save_cache(cache):
    try:
        CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=1))
    except Exception:
        pass


def _write_answer_file(n, question, answer, sc, mode_key):
    try:
        d = _ans_dir(mode_key)
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"{n:02d}.md"
        f.write_text(
            f"# {n}. {question}\n\n"
            f"movement {sc.get('movement')}/7 · triad {sc.get('triad')} · "
            f"c/p/r {sc.get('sub_cancel')}/{sc.get('sub_preserve')}/{sc.get('sub_raise')} · "
            f"both_sides {sc.get('both_sides')} · erasure {sc.get('erasure')} · "
            f"cites {sc.get('citations')} · ungrounded {sc.get('ungrounded')} · "
            f"{sc.get('seconds')}s · {sc.get('served')}\n\n---\n\n{answer}\n",
            encoding="utf-8",
        )
    except Exception:
        pass


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--online", action="store_true", help="online synth instead of offline qwen")
    ap.add_argument("--synth", default="", help="pin synth_model (e.g. deepseek-v4-pro)")
    ap.add_argument("--tag", default="", help="label for the summary")
    ap.add_argument("--fresh", action="store_true", help="ignore the resume cache")
    args = ap.parse_args()

    mode_key = f"online:{args.synth or 'auto'}" if args.online else "local"
    cache = {} if args.fresh else _load_cache()

    orig = bc._load_settings

    def forced():
        s = orig()
        s["temperature"] = 0.0
        if args.online:
            # settings.json may say offline:true — override it, or "--online"
            # silently runs the local model (the bug that made the first
            # "online" leg slow and mislabeled).
            s["offline"] = False
            s["auto_offline"] = False
            s["model"] = "deepseek-flash"
            s["synth_model"] = args.synth or "deepseek-v4-pro"
        else:
            s["offline"] = True
            s["model"] = "qwen"
            if args.synth:
                s["synth_model"] = args.synth
        return s

    bc._load_settings = forced

    brain = bc.Brain()
    rows = []
    n = len(DIALECTIC)
    t_all = time.time()
    try:
        for i, q in enumerate(DIALECTIC, 1):
            key = f"{mode_key}|{q}"
            print(f"\n{'=' * 78}\n[{i}/{n}] {q}\n{'=' * 78}", flush=True)

            hit = cache.get(key)
            if hit and hit.get("answer"):
                sc = {k: hit["scores"].get(k) for k in hit["scores"]} if hit.get("scores") else score(hit["answer"], 0, hit.get("served"))
                print(f"  (cached · {hit.get('served', '?')}) resume", flush=True)
                rows.append(sc)
                _write_answer_file(i, q, hit["answer"], sc, mode_key)
                continue

            t0 = time.time()

            def note(msg, _t0=t0):
                if not isinstance(msg, tuple):
                    print(f"  (+{time.time() - _t0:5.1f}s) · {msg}", flush=True)

            brain._progress = note
            last, buf = "", ""
            try:
                async for acc in brain.ask_stream(q):
                    if len(acc) <= len(last):
                        continue
                    delta = acc[len(last):]
                    last = acc
                    buf += delta
                    if "\n" in buf or len(buf) > 220 or delta.rstrip().endswith((".", "!", "?", '"')):
                        print(f"  (+{time.time() - t0:5.1f}s) {buf}", flush=True)
                        buf = ""
                if buf:
                    print(f"  (+{time.time() - t0:5.1f}s) {buf}", flush=True)
            except Exception as e:
                print(f"  ERROR {type(e).__name__}: {e}", flush=True)

            r = brain._last_stream_result or {}
            ans = r.get("answer") or ""
            sc = score(ans, time.time() - t0, r.get("served_model") or "")
            print(
                f"  -- {sc['seconds']}s cites={sc['citations']} ungr={sc['ungrounded']} "
                f"movement={sc['movement']}/7 triad={sc['triad']} "
                f"c/p/r={sc['sub_cancel']}/{sc['sub_preserve']}/{sc['sub_raise']} "
                f"both={sc['both_sides']} erasure={sc['erasure']}",
                flush=True,
            )
            rows.append(sc)
            if ans.strip():
                cache[key] = {
                    "answer": ans,
                    "served": r.get("served_model") or "",
                    "scores": sc,
                    "ts": time.time(),
                }
                _save_cache(cache)
            _write_answer_file(i, q, ans, sc, mode_key)
            print(f"\n  ANSWER {i}  (saved to {_ans_dir(mode_key)}/{i:02d}.md)", flush=True)
    finally:
        await brain.close()

    m = len(rows) or 1
    mv = sum(r["movement"] for r in rows) / m
    print(f"\n=== SUMMARY ({args.tag or ('online' if args.online else 'local')}) ===", flush=True)
    print(
        f"questions={len(rows)}  movement_avg={mv:.1f}/7  "
        f"triad={sum(r['triad'] for r in rows)}  both_sides={sum(r['both_sides'] for r in rows)}  "
        f"erasure={sum(r['erasure'] for r in rows)}",
        flush=True,
    )
    print(
        f"sublation cancel/preserve/raise="
        f"{sum(r['sub_cancel'] for r in rows)}/{sum(r['sub_preserve'] for r in rows)}/{sum(r['sub_raise'] for r in rows)}"
        f" of {len(rows)}  |  cites={sum(r['citations'] for r in rows)}  "
        f"ungrounded={sum(r['ungrounded'] for r in rows)}  avg_sec={sum(r['seconds'] for r in rows) / m:.1f}",
        flush=True,
    )
    print(f"total wall {time.time() - t_all:.0f}s", flush=True)


asyncio.run(main())
