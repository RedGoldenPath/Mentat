#!/usr/bin/env python
"""M3 data engine — grounded training examples from Mentat's real library.

Each example is produced the way the offline pipeline actually prompts:
  system = EVIDENCE (same renderer as inference) + register rules + offline rules
  user   = a natural question
  assistant = the answer contract (inline (Book · ...) citations, verbatim
              grounded quotes, honest limitation instead of fabrication)

Registers: quotes, concept, commentary, compare, count, poison (the #1
training target — see storage/poison_findings.md).

Usage:
  .venv/bin/python train/build_dataset.py --n 12 --dry-run   # smoke test
  .venv/bin/python train/build_dataset.py --n 3000           # full run

Resume-safe (skips finished ids), budget-capped, concurrent.
"""
import argparse
import asyncio
import hashlib
import json
import random
import re
import sqlite3
import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
import brain_core as bc  # noqa: E402

DATA = Path(__file__).resolve().parent / "data"
TRAIN = DATA / "train.jsonl"
VALID = DATA / "valid.jsonl"
STATS = DATA / "stats.json"

CITE_RE = re.compile(r"\([^()\n]{3,90} · [^()\n]{1,90}\)")
REFUSAL = (
    "not in", "no such", "does not contain", "doesn't contain", "do not contain",
    "no passage", "cannot find", "can't find", "couldn't find", "not present",
    "not indexed", "no mention", "no scene", "isn't in", "is not in", "no quote",
    "does not include", "doesn't include", "no record", "nothing in", "absent",
    "no verse", "not reproduced", "no occurrence", "not included",
)
STOPWORDS = set(
    "the of and to in a is that it was for on are as with his be at one by have "
    "this from or had not but what all were when we there can an your which their "
    "said if do will each about how up out them then she many some so these would "
    "other into has more her two like him see time could no than been its who now "
    "people my made over did down only way find use may water long little very "
    "after words called just where most know get through back much before go good "
    "new write our used me man too any day same right look think also around another "
    "came come work three word must because does part even place well such here take "
    "why things help put years away again off went old number great tell men say "
    "small every found still between name should home big give air line set own under "
    "read last never us left end along while might next sound below saw something "
    "thought both few those always show large often together asked house don't".split()
)
KIND_WEIGHTS = [
    ("quotes", 0.24),
    ("concept", 0.20),
    ("commentary", 0.14),
    ("compare", 0.10),
    ("count", 0.08),
    ("poison", 0.24),
    ("dialectic", 0.00),
]
HARD_KINDS = {"compare", "poison", "dialectic"}

# The dialectical-reasoning target: train the model to PERFORM the movement,
# not to describe it. Hegel via Kojève (Aufhebung spiral, recognition) plus
# dialectical and historical materialism (the three laws; material conditions,
# relations of production, class contradiction) — the tradition present in
# this library.
DIALECTIC_RULES = (
    "\n\nDIALECTICAL METHOD (required — think by contradiction, not summary). "
    "Apply the three laws: (1) UNITY AND STRUGGLE OF OPPOSITES — find the "
    "opposed moments INSIDE the subject and show how each conditions the "
    "other; contradiction drives change. (2) QUANTITY INTO QUALITY — follow "
    "accumulated change to a qualitative leap; name the threshold. "
    "(3) NEGATION OF THE NEGATION — the Aufhebung spiral: cancel, preserve, "
    "raise, then let the result turn again. Negate determinately (this "
    "content, not 'everything'). Ground historical/social claims in material "
    "conditions and class contradictions; where self-consciousness is at "
    "stake, recognition (Kojève) is the engine. Quote verbatim and cite; mark "
    "invention with ⟪…⟫. LENGTH: ~350–450 words — the whole movement, compact, "
    "no padding. Never write 'thesis, antithesis, synthesis'."
)

FLASH = "deepseek-flash"
PRO = "deepseek-v4-pro"


class Budget:
    def __init__(self, cap):
        self.cap = cap
        self.spent = 0.0
        self.calls = 0

    def add(self, model, usage):
        self.calls += 1
        self.spent += bc.estimate_cost(
            model,
            int((usage or {}).get("prompt_tokens", 0) or 0),
            int((usage or {}).get("completion_tokens", 0) or 0),
        )

    def ok(self):
        return self.spent < self.cap


async def teacher_call(prompt, system=None, model=FLASH, max_tokens=1400,
                       retries=3, tag=""):
    """One remote call returning (text, usage). Backs off on failure."""
    chosen = bc.resolve_model(model)
    provider, base_url, api_key, wire = bc.resolve_provider(chosen)
    if not (provider and api_key):
        raise RuntimeError(f"no key for teacher {model}")
    last = None
    timeout = 240 if model == PRO else 90
    for attempt in range(retries):
        t0 = time.time()
        try:
            text = await bc.remote_llm(
                prompt,
                system_prompt=system,
                model=wire,
                base_url=base_url,
                api_key=api_key,
                provider=provider,
                max_tokens=max_tokens,
                timeout=timeout,
            )
            dt = time.time() - t0
            with open(DATA / "build_debug.log", "a") as fh:
                fh.write(
                    f"{time.strftime('%H:%M:%S')} {tag} {model} {dt:5.1f}s "
                    f"chars={len(str(text or ''))}\n"
                )
            return str(text or ""), dict(bc._LAST_USAGE or {})
        except Exception as exc:
            with open(DATA / "build_debug.log", "a") as fh:
                fh.write(
                    f"{time.strftime('%H:%M:%S')} {tag} {model} "
                    f"{time.time()-t0:5.1f}s ERROR {type(exc).__name__}: "
                    f"{str(exc)[:120]}\n"
                )
            last = exc
            await asyncio.sleep(2 + attempt * 4)
    raise RuntimeError(f"teacher {model} failed: {last}")


def load_pool(seed=7, per_book=28):
    """Sample chunk rows from the library, grouped by book."""
    rng = random.Random(seed)
    db = sqlite3.connect(str(bc.STORAGE_DIR / "library.db"))
    try:
        db.row_factory = sqlite3.Row
        books = [r["book"] for r in db.execute(
            "SELECT book, COUNT(*) n FROM chunks GROUP BY book ORDER BY n DESC"
        ).fetchall() if r["book"]]
        pool = {}
        for b in books:
            rows = db.execute(
                "SELECT file_path, content FROM chunks WHERE book=? "
                "AND length(content) > 400", (b,)
            ).fetchall()
            if not rows:
                continue
            picks = rng.sample(rows, min(per_book, len(rows)))
            pool[b] = [
                {"file_path": r["file_path"], "content": r["content"]}
                for r in picks
            ]
    finally:
        db.close()
    return pool


def build_count_pool(pool, limit=24, per_book=3):
    """Real census questions whose numbers come from the actual census engine."""
    out = []
    books = [b for b in pool if pool[b]]
    random.Random(11).shuffle(books)
    for b in books:
        if len(out) >= limit:
            break
        picked = 0
        text = " ".join(p["content"] for p in pool[b][:6])[:60000].lower()
        words = re.findall(r"[a-z][a-z'-]{4,}", text)
        freq = {}
        for w in words:
            if w in STOPWORDS or w.endswith("'s"):
                continue
            freq[w] = freq.get(w, 0) + 1
        for w, n in sorted(freq.items(), key=lambda kv: -kv[1]):
            if len(out) >= limit or picked >= per_book:
                break
            if n < 6:
                break
            q = f"How many times does the word '{w}' appear in {b}?"
            try:
                ctx = bc._census_ctx(q, "agent")
            except Exception:
                continue
            block = ctx.get("block") or ""
            m = re.search(r"—\s*([\d,]+)", block)
            if block and m:
                out.append({
                    "question": q,
                    "block": block,
                    "number": m.group(1).replace(",", ""),
                    "book": b,
                })
                picked += 1
    return out


def _norm_book(name):
    s = str(name or "").lower()
    for sep in ("›", "/"):
        if sep in s:
            s = s.rsplit(sep, 1)[1]
    s = re.sub(r"\.(epub|pdf|txt|mobi|azw3|docx?)\b", " ", s)
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def valid_cites(answer, passages):
    """Every (Book · …) citation must reference a book present in evidence.

    Compares normalized names (the model sees cleaned labels, not paths)."""
    books = []
    for p in passages:
        label = bc._clean_name(str(p.get("file_path") or ""))
        books.append(_norm_book(label.split(" · ")[0]))
    for cite in CITE_RE.findall(answer):
        cite_book = _norm_book(cite.split("·")[0])
        if not cite_book:
            continue
        ok = False
        for b in books:
            if not b:
                continue
            probe = min(len(cite_book), len(b), 18)
            if cite_book[:probe] and cite_book[:probe] in b:
                ok = True
                break
            if b[:probe] and b[:probe] in cite_book:
                ok = True
                break
        if not ok:
            return False
    return True


def score_example(kind, answer, passages, count_number=None):
    bad = []
    if not answer.strip():
        return ["empty"]
    if kind == "count":
        if count_number and count_number not in answer.replace(",", ""):
            bad.append("missing census number")
    else:
        if len(CITE_RE.findall(answer)) < 1:
            bad.append("no inline citation")
    ungrounded = bc._verify_quotes(answer, passages) or []
    if ungrounded:
        bad.append(f"{len(ungrounded)} ungrounded quote(s)")
    if not valid_cites(answer, passages):
        bad.append("citation names a book not in evidence")
    if kind == "poison":
        low = answer.lower()
        if not any(p in low for p in REFUSAL):
            bad.append("poison answer lacks a limitation statement")
    return bad


Q_SYS = (
    "You write natural, varied questions for a private library search "
    "assistant. Questions must sound like a real reader; never mention "
    "chapters, pages, or that evidence was supplied. Reply with the question "
    "only."
)


def question_prompt(kind, passages, hint=""):
    if kind == "quotes":
        ctx = passages[0]["content"][:900]
        return (
            "A reader half-remembers this passage and wants the full quote with "
            "its source. Write ONE natural question. Do not name the book.\n\n"
            f"PASSAGE:\n{ctx}\n\n{hint}"
        )
    if kind == "concept":
        ctx = passages[0]["content"][:900]
        return (
            "Write ONE natural question that this passage answers (what/why/who). "
            "Do not name the book.\n\n"
            f"PASSAGE:\n{ctx}\n\n{hint}"
        )
    if kind == "commentary":
        ctx = passages[0]["content"][:900]
        return (
            "This passage is commentary/interpretation. Write ONE natural "
            "question asking what the commentary says about its topic. Do not "
            "name the book.\n\n"
            f"PASSAGE:\n{ctx}\n\n{hint}"
        )
    if kind == "compare":
        a = passages[0]["content"][:400]
        b = passages[1]["content"][:400] if len(passages) > 1 else ""
        return (
            "Write ONE natural comparison question that BOTH passages help "
            "answer. Name the two ideas, not the books.\n\n"
            f"PASSAGE A:\n{a}\n\nPASSAGE B:\n{b}\n\n{hint}"
        )
    if kind == "dialectic":
        ctx = passages[0]["content"][:900]
        return (
            "Write ONE natural interpretive or historical question that this "
            "passage can answer by dialectical analysis — a question of "
            "meaning, contradiction, power, or historical change (what does X "
            "mean; how are A and B related; why does X turn into its "
            "opposite). Do not name the book.\n\n"
            f"PASSAGE:\n{ctx}\n\n{hint}"
        )
    if kind == "poison":
        ctx = passages[0]["content"][:700]
        return (
            "Write ONE natural question asking for a specific quote, scene, "
            "verse, or number that the passages below do NOT provide, but which "
            "belongs to the same book or tradition (plausible but absent). Do "
            "not hint that it is absent.\n\n"
            f"PASSAGES:\n{ctx}\n\n{hint}"
        )
    raise ValueError(kind)


def answer_system(kind, passages, census_block=None):
    if kind == "count" and census_block:
        block = ""
    elif kind == "dialectic":
        # Compact evidence so the dialectical reasoning (the training target)
        # fits the 3072 window; full passages would starve the movement.
        block = bc._render_passage_block(passages, max_chars=1500)
    else:
        block = bc._render_passage_block(passages, full=True)
    rules = (
        "You are the offline answerer of a private library search system. Use "
        "ONLY the evidence below. Never invent quotes, locations, numbers, or "
        "page/chapter numbers."
    )
    if block:
        rules += "\n\nEVIDENCE:\n" + block
    if census_block:
        rules += "\n\nCENSUS\n" + census_block
    rules += bc._register_instruction(kind)
    rules += bc._offline_answer_rules(kind)
    if kind == "dialectic":
        rules += DIALECTIC_RULES
    return rules


async def make_example(kind, pool, count_pool, budget, rng):
    passages = []
    census_block = None
    count_number = None
    if kind == "count":
        if not count_pool:
            return None, "no_census_pool"
        pick = rng.choice(count_pool)
        question = pick["question"]
        census_block = pick["block"]
        count_number = pick["number"]
        passages = [{"file_path": f"{pick['book']}", "content": pick["block"]}]
    else:
        books = [b for b in pool if pool[b]]
        if kind == "compare":
            if len(books) < 2:
                return None, "pool_too_small"
            b1, b2 = rng.sample(books, 2)
            passages = [rng.choice(pool[b1]), rng.choice(pool[b2])]
        else:
            b = rng.choice(books)
            n = 1 if kind in ("quotes", "concept", "commentary") else rng.randint(1, 2)
            passages = rng.sample(pool[b], min(n, len(pool[b])))
        hint = "Vary the phrasing; keep it under 30 words."
        try:
            question, usage = await teacher_call(
                question_prompt(kind, passages, hint), system=Q_SYS,
                model=FLASH, max_tokens=900, tag=f"q:{kind}",
            )
            budget.add(FLASH, usage)
            if not str(question or "").strip():
                # Reasoning can eat a small budget and leave content empty.
                question, usage = await teacher_call(
                    question_prompt(kind, passages, hint), system=Q_SYS,
                    model=FLASH, max_tokens=2400, tag=f"q2:{kind}",
                )
                budget.add(FLASH, usage)
        except Exception as exc:
            return None, f"q_error:{type(exc).__name__}"
        budget.add(FLASH, usage)
        question = str(question or "").strip().split("\n")[0].strip('" ')
        if not question:
            return None, "q_empty"
        if len(question) > 240:
            return None, "q_long"
    system = answer_system(kind, passages, census_block)
    teacher = PRO if kind in HARD_KINDS and rng.random() < 0.5 else FLASH
    try:
        answer, usage = await teacher_call(
            question, system=system, model=teacher,
            max_tokens=16000 if teacher == PRO else 1400,
            tag=f"a:{kind}:{teacher}",
        )
    except Exception as exc:
        return None, f"a_error:{type(exc).__name__}"
    budget.add(teacher, usage)
    answer = re.sub(r"\.(?:epub|pdf)\b", "", str(answer or "")).strip()
    bad = score_example(kind, answer, passages, count_number)
    if bad and teacher == FLASH:
        try:
            answer, usage = await teacher_call(
                question, system=system, model=PRO, max_tokens=16000,
                tag=f"retry:{kind}",
            )
            budget.add(PRO, usage)
            answer = re.sub(r"\.(?:epub|pdf)\b", "", str(answer or "")).strip()
            bad = score_example(kind, answer, passages, count_number)
        except Exception as exc:
            bad = bad or [f"retry_error:{type(exc).__name__}"]
    if bad:
        return None, "invalid:" + ",".join(bad)[:120]
    eid = hashlib.sha1(
        (kind + question + (passages[0]["content"][:120])).encode()
    ).hexdigest()[:16]
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": question},
        {"role": "assistant", "content": answer},
    ]
    return {
        "id": eid,
        "kind": kind,
        "teacher": teacher,
        "books": sorted({p["file_path"].split(" · ")[0] for p in passages}),
        "messages": messages,
    }, ""


def load_seen():
    seen = set()
    for path in (TRAIN, VALID):
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    seen.add(json.loads(line)["id"])
                except Exception:
                    pass
    return seen


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=3000)
    ap.add_argument("--budget", type=float, default=12.0)
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--kinds", default="", help="comma-separated kinds to generate (default: all weighted)")
    ap.add_argument("--data-dir", default="", help="override output dir (e.g. data_dialectic)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    global DATA, TRAIN, VALID
    if args.data_dir:
        DATA = Path(__file__).resolve().parent / args.data_dir
        TRAIN = DATA / "train.jsonl"
        VALID = DATA / "valid.jsonl"

    DATA.mkdir(parents=True, exist_ok=True)
    targets = {"train": TRAIN, "valid": VALID}
    if args.dry_run:
        targets = {"train": DATA / "_smoke.jsonl", "valid": DATA / "_smoke_valid.jsonl"}
        for p in targets.values():
            p.unlink(missing_ok=True)
    seen = set() if args.dry_run else load_seen()
    pool = load_pool()
    count_pool = build_count_pool(pool)
    budget = Budget(args.budget)
    print(
        f"pool: {len(pool)} books, {sum(len(v) for v in pool.values())} chunks, "
        f"{len(count_pool)} census questions | seen: {len(seen)}",
        flush=True,
    )

    stats = {"accepted": 0, "attempts": 0, "rejected": 0, "kinds": {}, "reasons": {}}
    seen_initial = len(seen)
    lock = asyncio.Lock()
    rng = random.Random()
    sem = asyncio.Semaphore(args.concurrency)
    kws = KIND_WEIGHTS
    if args.kinds:
        want = {k.strip() for k in args.kinds.split(",") if k.strip()}
        kws = [(k, 1.0) for k, _ in KIND_WEIGHTS if k in want]
        if not kws:
            raise SystemExit(f"--kinds matched nothing: {args.kinds}")
    kinds, weights = zip(*kws)
    t0 = time.time()

    async def worker():
        while True:
            async with lock:
                if stats["accepted"] + seen_initial >= args.n or not budget.ok():
                    return
                stats["attempts"] += 1
            async with sem:
                kind = rng.choices(kinds, weights=weights, k=1)[0]
                try:
                    row, reason = await make_example(kind, pool, count_pool, budget, rng)
                except Exception as exc:
                    row, reason = None, f"worker_error:{type(exc).__name__}"
            async with lock:
                if row and row["id"] not in seen:
                    seen.add(row["id"])
                    path = targets["valid"] if stats["accepted"] % 10 == 9 else targets["train"]
                    with open(path, "a", encoding="utf-8") as fh:
                        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                    stats["accepted"] += 1
                    stats["kinds"][kind] = stats["kinds"].get(kind, 0) + 1
                    if stats["accepted"] % 25 == 0 or args.dry_run:
                        print(
                            f"[{stats['accepted']:>4}/{args.n}] {kind:<10} "
                            f"${budget.spent:.2f} spent · {budget.calls} calls · "
                            f"{time.time()-t0:.0f}s",
                            flush=True,
                        )
                    if args.dry_run:
                        print(json.dumps(row, ensure_ascii=False)[:1500], flush=True)
                else:
                    stats["rejected"] += 1
                    key = (reason or "unknown")[:60]
                    stats["reasons"][key] = stats["reasons"].get(key, 0) + 1

    workers = [asyncio.create_task(worker()) for _ in range(args.concurrency * 2)]
    await asyncio.gather(*workers, return_exceptions=True)

    stats["spent_usd"] = round(budget.spent, 2)
    stats["calls"] = budget.calls
    stats["seconds"] = round(time.time() - t0)
    print("\n=== DATASET SUMMARY ===", flush=True)
    print(json.dumps(stats, indent=2), flush=True)
    if not args.dry_run:
        STATS.write_text(json.dumps(stats, indent=2), encoding="utf-8")
        for name, path in (("train", TRAIN), ("valid", VALID)):
            n = len(path.read_text().splitlines()) if path.exists() else 0
            print(f"{name}: {n} examples", flush=True)


asyncio.run(main())
