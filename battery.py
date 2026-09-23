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
import os
import re
import sqlite3
import subprocess
import sys
import threading
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


_COLS = ("cpu_sec", "cpu_pct", "rss_mb", "lean",
         "t_open", "t_route", "t_passages", "t_answer",
         "tokens_in", "tokens_out", "helper_calls", "helper_sec", "ans_path")


def _last_ask_perf():
    """The instrumentation row brain_core just wrote for the last ask: CPU
    seconds/percent, peak RSS, the lean flag, and the per-stage timings.

    Reading it back (rather than re-timing in the harness) is the whole point:
    the running engine and the bench share one measurement, so a change is
    judged on the same numbers it will ship with."""
    try:
        con = sqlite3.connect(bc.STORAGE_DIR / "telemetry.db")
        con.row_factory = sqlite3.Row
        row = con.execute(
            f"SELECT {', '.join(_COLS)} FROM asks ORDER BY id DESC LIMIT 1"
        ).fetchone()
        con.close()
        return {k: row[k] for k in _COLS} if row else {}
    except Exception:
        return {}


class CpuSampler:
    """Samples the resource load that actually warmed the machine while an ask
    ran: CPU% and RSS (in MB) summed over the engine + model processes, plus the
    system's free-memory floor.

    The engine's in-process ``getrusage`` only sees Python; the pressure comes
    from the model servers (``ollama``) in separate processes. ``ps`` gives
    per-process numbers without any dependency.
    """

    KEYS = ("ollama", "llama-server")

    def __init__(self, interval=0.5):
        self.interval = interval
        self.cpu = []
        self.rss = []          # MB, summed over matched processes
        self.samples = []
        self.free = []         # system free %, sampled less often
        self._stop = threading.Event()
        self._thread = None
        self._tick = 0

    def _loop(self):
        while not self._stop.is_set():
            try:
                out = subprocess.run(
                    ["ps", "-Ao", "%cpu=,rss=,command="], capture_output=True, text=True, timeout=5
                ).stdout
                cpu_total = rss_total = 0.0
                for line in out.splitlines():
                    parts = line.strip().split(None, 2)
                    if len(parts) != 3:
                        continue
                    try:
                        cpu = float(parts[0])
                        rss = float(parts[1])
                    except ValueError:
                        continue
                    cmd = parts[2].lower()
                    if any(k in cmd for k in self.KEYS):
                        cpu_total += cpu
                        rss_total += rss
                self.cpu.append(cpu_total)
                self.rss.append(rss_total / 1024.0)  # KB -> MB
                self._tick += 1
                if self._tick % 8 == 0:  # free% is the slow call; every ~4s
                    f = _free_pct()
                    if f >= 0:
                        self.free.append(f)
            except Exception:
                pass
            self._stop.wait(self.interval)

    def start(self):
        self._stop.clear()
        self.cpu, self.rss, self.free, self._tick = [], [], [], 0
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        """(cpu_peak, cpu_mean, mem_peak_mb, mem_mean_mb, free_min_pct)."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

        def agg(vals):
            if not vals:
                return (None, None)
            return (round(max(vals), 1), round(sum(vals) / len(vals), 1))

        cp, cm = agg(self.cpu)
        mp, mm = agg(self.rss)
        return (cp, cm, mp, mm, (min(self.free) if self.free else None))


_MOVEMENT = {
    "contradiction": ("contradict", "self-contradict", "internal contradiction"),
    "opposites": ("unity of opposite", "opposite", "opposed tendencies", "divided against"),
    "quantity_quality": ("qualitative leap", "quantitative", "threshold", "leap"),
    "sublation": ("sublat", "aufhebung", "aufheben", "preserved and", "cancel"),
    "negation": ("negation of the negation", "negates"),
    "material": ("material condition", "relations of production", "mode of production", "class "),
    "recognition": ("recognition", "anerkennung", "acknowledg"),
}
_TRIAD = ("thesis, antithesis, synthesis", "thesis-antithesis-synthesis")


def dialectic_rubric(answer):
    """Score how much the answer actually THINKS dialectically (0-7) and flag
    the banned triad. Measures the movement, not citation count."""
    low = (answer or "").lower()
    n = sum(1 for terms in _MOVEMENT.values() if any(t in low for t in terms))
    triad = int(any(t in low for t in _TRIAD))
    return n, triad


def score(answer, seconds, served):
    cites = CITE_RE.findall(answer or "")
    low = (answer or "").lower()
    movement, triad = dialectic_rubric(answer)
    return {
        "citations": len(cites),
        "ungrounded": (answer or "").count("⟪"),
        "refused": int(not cites and any(r in low for r in REFUSAL)),
        "chars": len(answer or ""),
        "seconds": round(seconds, 1),
        "served": served,
        "movement": movement,
        "triad": triad,
    }


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", default="battery", choices=list(GROUPS))
    ap.add_argument("--online", action="store_true", help="do not force offline")
    ap.add_argument("--synth", default="", help="pin synth_model (e.g. deepseek-think) for online A/B")
    ap.add_argument("--only", type=int, default=0, help="1-based index of a single question to run")
    ap.add_argument("--limit", type=int, default=0, help="run only the first N questions (for fast A/B)")
    ap.add_argument("--voice", default="", help="voice preset (e.g. dialectic) for A/B")
    ap.add_argument("--temp", type=float, default=0.0, help="sampling temperature (0 = deterministic)")
    ap.add_argument("--lean", action="store_true",
                    help="lean test profile: pin optional retrieval layers (no HyDE/graph)")
    ap.add_argument("--tag", default="", help="label this run, e.g. 'mlx-4bit'")
    ap.add_argument("--out", default="")
    ap.add_argument("--compare", nargs=2, metavar=("BASELINE", "CANDIDATE"),
                    help="diff two battery jsonl runs and exit")
    ap.add_argument("--metric", default="both", choices=("time", "ram", "both"),
                    help="which resource the --compare gate treats as the hard regression")
    args = ap.parse_args()

    if args.compare:
        compare(args.compare[0], args.compare[1], metric=args.metric)
        return

    if args.lean:
        os.environ["MENTAT_LEAN"] = "1"

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
    elif args.limit:
        questions = questions[: args.limit]
    run_id = time.strftime("%Y%m%d-%H%M%S")
    label = f"{args.group}{'_' + args.tag if args.tag else ''}"
    out = Path(args.out) if args.out else bc.STORAGE_DIR / f"battery_{label}_{run_id}.jsonl"

    brain = bc.Brain()
    rows = []
    try:
        for i, q in enumerate(questions, 1):
            t0 = time.time()
            sampler = CpuSampler()
            sampler.start()
            try:
                res = await brain.ask(q, lazy=True)
                ans = res.get("answer") or ""
            except Exception as exc:
                ans = ""
                res = {"status": f"error:{type(exc).__name__}"}
            secs = time.time() - t0
            cpu_peak, cpu_mean, mem_peak, mem_mean, free_min = sampler.stop()
            row = {"n": i, "question": q, "status": res.get("status"),
                   **score(ans, secs, _last_synth_model()),
                   "sys_cpu_peak": cpu_peak, "sys_cpu_mean": cpu_mean,
                   "sys_mem_peak_mb": mem_peak, "sys_mem_mean_mb": mem_mean,
                   "free_min_pct": free_min,
                   "perf": _last_ask_perf(), "answer": ans}
            rows.append(row)
            p = row["perf"]
            stages = " ".join(
                f"{k[2:]}={p[k]:.1f}" for k in ("t_open", "t_route", "t_passages", "t_answer")
                if p.get(k) is not None
            )
            cpu = p.get("cpu_pct")
            print(f"[{i}/{len(questions)}] {row['seconds']:>6}s cites={row['citations']} "
                  f"ungr={row['ungrounded']} refused={row['refused']} served={row['served']} "
                  f"| mem={mem_peak if mem_peak is not None else '-'}MB free={free_min if free_min is not None else '-'}% "
                  f"sys={cpu_mean if cpu_mean is not None else '-'}% | {stages} | {q[:30]}", flush=True)
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
    print(f"group={args.group} tag={args.tag or '-'} lean={bool(args.lean)} questions={n}")
    print(f"answered={sum(1 for r in rows if r['answer'].strip())}/{n}  "
          f"with_citations={cited}/{n}  total_citations={tot_cites}")
    print(f"ungrounded_quotes={ungr}  refused={refused}  avg_seconds={avg:.1f}")
    mv = sum(r.get("movement", 0) for r in rows) / max(n, 1)
    triad = sum(r.get("triad", 0) for r in rows)
    print(f"dialectic_movement_avg={mv:.1f}/7  triad_violations={triad}")
    _print_perf(rows)
    print(f"ollama_resident={_ollama_resident()}  system_free={_free_pct()}%")
    print(f"written: {out}")


def _avg(rows, key):
    vals = [r["perf"].get(key) for r in rows if r.get("perf") and r["perf"].get(key) is not None]
    return sum(vals) / len(vals) if vals else None


def _print_perf(rows):
    """Stage + resource breakdown — the data the A/B decision reads."""
    cpu = _avg(rows, "cpu_pct")
    rss = _avg(rows, "rss_mb")
    cpu_s = _avg(rows, "cpu_sec")
    sys_vals = [r["sys_cpu_mean"] for r in rows if r.get("sys_cpu_mean") is not None]
    sys_mean = sum(sys_vals) / len(sys_vals) if sys_vals else None
    sys_peak = max((r.get("sys_cpu_peak") or 0 for r in rows), default=0) or None
    mem_vals = [r["sys_mem_peak_mb"] for r in rows if r.get("sys_mem_peak_mb") is not None]
    mem_peak = max(mem_vals) if mem_vals else None
    frees = [r["free_min_pct"] for r in rows if r.get("free_min_pct") is not None]
    free_min = min(frees) if frees else None
    gen_tok = _avg(rows, "tokens_out")
    hcalls = _avg(rows, "helper_calls")
    hsec = _avg(rows, "helper_sec")
    paths = {}
    for r in rows:
        v = (r.get("perf") or {}).get("ans_path") or "-"
        paths[v] = paths.get(v, 0) + 1
    path_s = " ".join(f"{k}={v}" for k, v in sorted(paths.items()))
    print("\n--- resources ---")
    print(f"engine: cpu_total={f'{cpu_s:.1f}s' if cpu_s is not None else '-'}  "
          f"cpu_util={f'{cpu:.0f}%' if cpu is not None else '-'}  "
          f"peak_rss={f'{rss:.0f}MB' if rss is not None else '-'}")
    print(f"heat:   gen_tokens={f'{gen_tok:.0f}' if gen_tok is not None else '-'}  "
          f"helper_calls={f'{hcalls:.1f}' if hcalls is not None else '-'}  "
          f"helper_sec={f'{hsec:.1f}' if hsec is not None else '-'}  "
          f"paths[{path_s}]")
    print(f"system: model_procs_peak={f'{mem_peak:.0f}MB' if mem_peak is not None else '-'}  "
          f"free_floor={f'{free_min}%' if free_min is not None else '-'}  "
          f"cpu_mean={f'{sys_mean:.0f}%' if sys_mean is not None else '-'}  "
          f"cpu_peak={f'{sys_peak:.0f}%' if sys_peak else '-'}")
    print("--- stages (avg seconds) ---")
    for key in ("t_open", "t_route", "t_passages", "t_answer"):
        v = _avg(rows, key)
        print(f"  {key[2:]:<10} {'-' if v is None else f'{v:.2f}'}")


def compare(base_path, cand_path, metric="both"):
    """Diff two battery runs question-by-question and flag regressions.

    Quality is always gated (citations not lower, ungrounded not higher,
    refused not higher). The resource gate is chosen by ``metric``:
    ``time`` (wall latency), ``ram`` (peak model-process memory), or ``both``.
    """
    def load(p):
        return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]

    base, cand = load(base_path), load(cand_path)
    by_q = {r["question"]: r for r in base}
    print(f"baseline: {base_path}\ncandidate: {cand_path}  [gate metric: {metric}]\n")
    print(f"{'question':<44} {'cites':>10} {'ungr':>8} {'secs':>13} {'mem(MB)':>13}  verdict")
    regressions = 0
    for r in cand:
        b = by_q.get(r["question"])
        if not b:
            print(f"{r['question'][:44]:<44}  (no baseline)")
            continue
        dc = r["citations"] - b["citations"]
        du = r["ungrounded"] - b["ungrounded"]
        dt = r["seconds"] - b["seconds"]
        tp = dt / b["seconds"] * 100 if b["seconds"] else 0.0
        bmem = b.get("sys_mem_peak_mb")
        cmem = r.get("sys_mem_peak_mb")
        dmem = (cmem - bmem) / bmem * 100 if bmem and cmem else 0.0
        time_bad = tp > 15
        ram_bad = dmem > 15
        res_bad = {
            "time": time_bad,
            "ram": ram_bad,
            "both": time_bad and ram_bad,
        }[metric]
        bad = dc < 0 or du > 0 or r["refused"] > b["refused"] or res_bad
        regressions += int(bad)
        mem_s = f"{bmem:.0f}->{cmem:.0f}" if bmem is not None and cmem is not None else "-"
        print(f"{r['question'][:44]:<44} {b['citations']:>3}->{r['citations']:<3}({dc:+d}) "
              f"{b['ungrounded']:>3}->{r['ungrounded']:<3} {b['seconds']:>6.1f}->{r['seconds']:<6.1f}"
              f"({tp:+4.0f}%) {mem_s:>11}  {'REGRESS' if bad else 'ok'}")
    print(f"\nregressions: {regressions}/{len(cand)}")
    print("keep candidate" if regressions == 0 else "do NOT keep candidate")



if __name__ == "__main__":
    asyncio.run(main())
