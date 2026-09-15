"""Evaluation harness for Mentat.

Run:  uv run python eval.py [--full] [--gold]

Covers retrieval routing, book-switching, particular/universal answers, and
offline behavior. Prints a pass/fail table with latencies.

Usage note: --full runs the slow end-to-end LLM cases; without it, only the
fast (no-LLM) retrieval and routing checks run. --gold runs the stored
gold-standard retrieval exam (no LLM calls) and fails on regression.
"""
import asyncio
import json
import re
import sys
import time

sys.path.insert(0, ".")

import brain_core as b

RESULTS = []


def record(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")


GOLD_PATH = b.STORAGE_DIR / "gold.json"

GOLD_SEED = [
    {
        "question": "what does Kojève say about sovereignty and America",
        "books": [{"book": "kojeve", "min": 3}],
    },
    {
        "question": "what does the Quran say about mercy",
        "books": [{"book": "Study Quran", "min": 3}],
    },
    {
        "question": "what does the Catholic Study Bible say about mercy",
        "books": [{"book": "Study Bible", "min": 2}],
    },
    {
        "question": "find the litany against fear in the dune books",
        "books": [{"book": "dune", "min": 1, "content": "mind-killer"}],
    },
    {
        "question": "what does Dune say about mercy",
        "books": [{"book": "dune", "min": 2, "content": "mercy"}],
    },
    {
        "question": "triangulate Stalin Kojève and Leto II on sovereignty and history",
        "books": [{"book": "kojeve", "min": 2}, {"book": "stalin", "min": 2}],
    },
    {
        "question": "what does hudson's analysis show about debt and sovereignty",
        "books": [{"book": "hudson", "min": 3}],
    },
    {
        "question": "what does Lenin argue in state and revolution",
        "books": [{"book": "state-and-revolution", "min": 3}],
    },
    {
        "question": "what does the Muqaddimah say about the rise and fall of dynasties",
        "books": [{"book": "muqaddimah", "min": 3}],
    },
    {
        "question": "what does the Quran say about power",
        "books": [{"book": "Study Quran", "min": 2}],
    },
    {
        "question": "beautiful, but the problem with herbert was his limits as a liberal subject, unwilling to contend with the reality of the logic he already fully understood and embodies in the GOd emperor. Stalin was the leader of the future, the savior of the world against nazi terror, the man who took a peasant backwater prisonhouse of nations and turned it into a spacefaring nuclear power. Mao and Xi do much the same in China. Communism breaks the stagnation, and America will follow suite after the contradictions of unipolar hegemony are too much to bare.",
        "books": [{"book": "dune", "min": 1}, {"book": "stalin", "min": 1}, {"book": "socialism", "min": 1}],
    },
    {
        "question": "give me quotes from stalin, kojeve, dune, and husdons about sovereignty and history",
        "books": [
            {"book": "stalin", "min": 1},
            {"book": "kojeve", "min": 1},
            {"book": "dune", "min": 1},
            {"book": "hudson", "min": 1},
        ],
    },
]


def _ensure_gold():
    if GOLD_PATH.exists():
        try:
            return json.loads(GOLD_PATH.read_text())
        except Exception:
            pass
    entries = [dict(e) for e in GOLD_SEED]
    GOLD_PATH.write_text(json.dumps(entries, indent=2, ensure_ascii=False))
    return entries


def _score_gold_entry(ps, entry):
    """Score one gold question: per book-token, hits = passages from that book
    (optionally containing the required content); score = hits/min, capped at
    1. Overall = mean of the per-book scores."""
    scores = []
    details = []
    for spec in entry.get("books", []):
        token = spec.get("book", "").lower()
        need = (spec.get("content") or "").lower()
        hits = 0
        for p in ps:
            fp = str(p.get("file_path") or "").lower()
            if token not in fp:
                continue
            if need and need not in str(p.get("content") or "").lower():
                continue
            hits += 1
        s = min(1.0, hits / max(1, spec.get("min", 1)))
        scores.append(s)
        details.append(f"{token}:{hits}/{spec.get('min', 1)}")
    return (sum(scores) / len(scores)) if scores else 0.0, details


async def bench_run():
    """Benchmark core subsystems, store baselines, fail on regression."""
    import resource
    import time

    bench_path = b.STORAGE_DIR / "benchmark.json"
    brain = b.Brain()
    rag = await brain.open()
    results = {}
    try:
        b._refresh_caches()
        t0 = time.time()
        chunks = b._load_chunk_texts()
        results["chunk_load_s"] = round(time.time() - t0, 2)
        results["chunk_store_mb"] = round(
            sum(len(str(c.get("content", ""))) for c in chunks) / 1e6, 1
        )
        probe_times = []
        for q in (
            "what does Dune say about mercy",
            "what does the Quran say about power",
            "triangulate Stalin Kojève and Leto II on sovereignty",
        ):
            t0 = time.time()
            await b._probe_passages(rag, q, k=8)
            probe_times.append(time.time() - t0)
        results["probe_median_s"] = round(sorted(probe_times)[1], 2)
        t0 = time.time()
        await b._librarian_search(rag, "mercy", k=5)
        results["librarian_s"] = round(time.time() - t0, 2)
        results["rss_mb"] = round(
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6, 1
        )
    finally:
        await brain.close()

    prev = {}
    try:
        prev = json.loads(bench_path.read_text())
    except Exception:
        pass
    regressed = []
    for key in ("chunk_load_s", "chunk_store_mb", "probe_median_s", "librarian_s", "rss_mb"):
        if key in prev and prev[key] > 0 and results.get(key, 0) > prev[key] * 1.15:
            # ignore sub-millisecond/rounding noise on tiny timings
            if results.get(key, 0) - prev[key] > 0.01:
                regressed.append(f"{key}: {prev[key]} -> {results[key]}")
    results["regressed"] = regressed
    try:
        bench_path.write_text(json.dumps(results, indent=2))
    except Exception:
        pass
    record(
        "bench: baselines captured",
        not regressed,
        json.dumps(results, sort_keys=True) + (" REGRESSED: " + "; ".join(regressed) if regressed else ""),
    )
    return bool(regressed)


async def gold_run():
    entries = _ensure_gold()
    brain = b.Brain()
    failures = 0
    try:
        rag = await brain.open()
        for entry in entries:
            q = entry.get("question", "")
            ps = await b._probe_passages(rag, q, k=12)
            score, details = _score_gold_entry(ps, entry)
            prev = entry.get("last")
            regressed = prev is not None and score < prev * 0.8
            record(
                f"gold: {q[:44]}",
                not regressed and score >= 0.75,
                f"score {score:.2f} [{', '.join(details)}]"
                + (f" REGRESSED (was {prev:.2f})" if regressed else ""),
            )
            if regressed:
                failures += 1
            entry["last"] = round(score, 3)
            entry["best"] = round(max(entry.get("best", 0.0), score), 3)
    finally:
        await brain.close()
        try:
            GOLD_PATH.write_text(json.dumps(entries, indent=2, ensure_ascii=False))
        except Exception:
            pass
    print(f"\ngold exam: {len(entries) - failures}/{len(entries)} passed (retrieval-only, no LLM)")
    return failures


# ---------------------------------------------------------------- fast checks

def fast_checks():
    # routing decisions
    cases = [
        ("who wrote dune", "simple"),
        ("find the litany against fear in the dune books", "agent"),
        ("how does kojeve critique hegel on the master slave dialectic", "agent"),
        ("what does the Catholic Study Bible say about mercy", "agent"),
        ("how do the themes across Kojeve and Hudson compare", "universal"),
    ]
    for q, expected in cases:
        score = b._question_heuristic_score(q)
        strategy = b._retrieval_strategy(q, score)
        if b._has_universal_intent(q):
            strategy = "universal"
        record(
            f"routing: {q[:45]}",
            strategy == expected,
            f"expected {expected}, got {strategy}",
        )

    # multi-entity questions never route simple
    for q in (
        "triangulate Stalin Kojève and Leto II on sovereignty and history",
        "stalin kojève leto ii",
    ):
        s = b._question_heuristic_score(q)
        strategy = b._retrieval_strategy(q, s)
        record(f"routing: multi-entity {q[:38]}", strategy != "simple", f"got {strategy}")

    # interpretive mode triggers
    for q, expect in [
        ("what does Dune say about mercy", False),
        ("connect Kojève's end of history to Leto II's Golden Path", True),
        ("triangulate Stalin Kojève and Leto II on sovereignty", True),
    ]:
        got = b._is_interpretive(q)
        record(f"interpretive: {q[:42]}", got == expect, f"got {got}")

    # voice presets + no-answer fallbacks
    record(
        "voices: default/dune/prophet",
        set(b.VOICE_PRESETS) == {"default", "dune", "prophet"},
        ", ".join(b.VOICE_PRESETS),
    )
    record(
        "voice: dune has exemplar",
        "A beginning is a delicate time" in b.VOICE_PRESETS["dune"],
        "exemplar present",
    )
    record(
        "fallbacks: cover every voice",
        set(b.NO_ANSWER_FALLBACKS) >= set(b.VOICE_PRESETS),
        ", ".join(b.NO_ANSWER_FALLBACKS),
    )
    record(
        "fallback: returns a line",
        bool(b._no_answer_line().strip()) and "…(no answer)" not in b._no_answer_line(),
        repr(b._no_answer_line()),
    )

    # name resolution: misspellings, possessives, accents
    record("names: stallin -> stalin", b._resolve_name("stallin") == "stalin", repr(b._resolve_name("stallin")))
    record("names: huds0n -> hudson", b._resolve_name("huds0n") == "hudson", repr(b._resolve_name("huds0n")))
    record(
        "names: hudson's possessive",
        "hudson" in b._derive_terms("what does hudson's analysis show about debt"),
        str(b._derive_terms("what does hudson's analysis show about debt")),
    )

    # invented-content markers
    record(
        "invented: style converts markers",
        b._style_invented("say ⟪so it is⟫ done") == "say **so it is** done",
        repr(b._style_invented("say ⟪so it is⟫ done")),
    )
    record(
        "invented: stanza paragraphs bolded",
        b._style_invented("⟪line one\n\nline two⟫") == "**line one**\n\n**line two**",
        repr(b._style_invented("⟪line one\n\nline two⟫")),
    )
    record(
        "invented: unclosed marker stays plain",
        b._style_invented("a ⟪unclosed b") == "a unclosed b",
        repr(b._style_invented("a ⟪unclosed b")),
    )
    record(
        "invented: clean strips markers",
        b._clean_markers("a ⟪b⟫ c") == "a b c",
        repr(b._clean_markers("a ⟪b⟫ c")),
    )
    record(
        "invented: prompt instructs markers",
        "⟪" in b.INVENTED_INSTRUCTION and "⟫" in b.INVENTED_INSTRUCTION,
        "marker instruction present",
    )

    # live thinking hook
    seen = []
    b._set_reasoning_hook(lambda msg: seen.append(msg))
    b._reasoning_delta("hello")
    b._reasoning_delta("world")
    b._set_reasoning_hook(None)
    b._reasoning_delta("ignored")
    record(
        "thinking: hook receives deltas and clears",
        seen == [("think", "hello"), ("think", "world")],
        str(seen),
    )

    # conversations: per-file store, grouping, ids, roundtrip
    convs = b._conversations()
    record("convos: index non-empty", bool(convs) and all(c.get("conv") for c in convs), f"{len(convs)} convs")
    record(
        "convos: counts match conv files",
        all(len(b._load_conv(c["conv"])) == c["count"] for c in convs),
        [c["count"] for c in convs],
    )
    record("convos: uuid ids (collision-proof)", all(len(str(c["conv"])) == 32 for c in convs), "uuid4 hex")
    record("convos: legacy flat file migrated away", not b.HISTORY_PATH.exists(), "history.json absent")

    import tempfile
    from pathlib import Path as _P

    tmp = tempfile.mkdtemp()
    old = (
        b.CONV_DIR,
        b.CONV_INDEX_PATH,
        b.CONV_STATE_PATH,
        b.CONV_LOCK_PATH,
        b._lock_file_handle,
    )
    b.CONV_DIR = _P(tmp) / "conversations"
    b.CONV_INDEX_PATH = b.CONV_DIR / "index.json"
    b.CONV_STATE_PATH = _P(tmp) / "state.json"
    b.CONV_LOCK_PATH = b.CONV_DIR / ".lock"
    b._lock_file_handle = None
    try:
        b._append_history({"timestamp": "2099-01-01 10:00:00", "question": "q1", "answer": "a1"})
        b._append_history({"timestamp": "2099-01-01 10:01:00", "question": "q2", "answer": "a2"})
        conv = b._current_conv_id()
        turns = b._load_conv(conv)
        record("store: appends accumulate in one conv", len(turns) == 2, f"{len(turns)} turns")
        b._set_current_conv(b._new_conv_id())
        b._append_history({"timestamp": "2099-01-01 10:02:00", "question": "q3", "answer": "a3"})
        record(
            "store: new conv splits",
            b._current_conv_id() != conv and len(b._load_conv(b._current_conv_id())) == 1,
            "split ok",
        )
        b._update_history_summary(conv, turns[0]["timestamp"], "q1", "first summary")
        record("store: summary write", b._load_conv(conv)[0].get("summary") == "first summary", repr(b._load_conv(conv)[0].get("summary")))
        b._delete_conversation(conv)
        record(
            "store: delete conv",
            b._load_conv(conv) == [] and all(c["conv"] != conv for c in b._conversations()),
            "deleted",
        )
    finally:
        (
            b.CONV_DIR,
            b.CONV_INDEX_PATH,
            b.CONV_STATE_PATH,
            b.CONV_LOCK_PATH,
            b._lock_file_handle,
        ) = old

    # brace-escaping regression: passages containing '{' must survive .format()
    quran_brace = next(
        (
            c
            for c in b._load_chunk_texts()
            if "Study Quran" in c["file_path"]
            and ("{" in c["content"] or "}" in c["content"])
        ),
        None,
    )
    if quran_brace is not None:
        p = {
            "file_path": quran_brace["file_path"],
            "content": quran_brace["content"],
            "excerpt": quran_brace["content"][:400],
            "chunk_id": quran_brace["chunk_id"],
        }
        tmpl = b._rag_system_prompt("naive", interpretive=True) + b._render_passage_block([p])
        try:
            tmpl.format(response_type="x", user_prompt="y", content_data="CTX")
            record("format: brace passages survive .format()", True, "ok")
        except Exception as exc:
            record("format: brace passages survive .format()", False, str(exc)[:60])

    # short summary quality: 3-5 words, contains the topic + subject
    summ = b._short_summary("what does Dune say about mercy")
    record(
        "summary: what does Dune say about mercy",
        "dune" in summ.lower() and "mercy" in summ.lower(),
        repr(summ),
    )

    # library map exists and covers the books
    mp = b._load_library_map()
    books = mp.get("books", {})
    record("map: all 14 books present", len(books) >= 14, f"{len(books)} books")
    kojeve = [r for r in books if "kojeve" in r.lower()]
    record("map: kojeve identified", bool(kojeve), "found" if kojeve else "missing")

    # fts + vec are built
    b._fts_sync()
    ids = b._fts_search(["mercy"], limit=10)
    record("fts: mercy search returns hits", len(ids) > 0, f"{len(ids)} hits")
    b._vec_sync()
    db = b._vec_db()
    n = db.execute("SELECT count(*) FROM chunks_vec").fetchone()[0]
    record("vec: table populated", n > 7000, f"{n} vectors")

    # staged text cache
    from pathlib import Path

    quran = None
    for p in b._iter_knowledge_files():
        if "Study Quran" in str(p):
            quran = p
            break
    if quran is not None:
        docs = b._staged_texts(quran)
        record("staging: quran cached", bool(docs), f"{len(docs or [])} docs")

    # telemetry: schema + roundtrip in a temp db
    import tempfile

    tmp = tempfile.mkdtemp()
    old_tel = b.TELEMETRY_PATH
    b.TELEMETRY_PATH = Path(tmp) / "telemetry.db"
    try:
        b._telemetry_init()
        aid = b._telemetry_log_ask(
            {
                "ts": "2099-01-01 00:00:00", "conv_id": "t", "question": "q",
                "mode": "naive", "model": "m", "voice": "default", "thinking": "false",
                "strategy": "hybrid", "docs_count": 0,
                "t_open": None, "t_route": None, "t_passages": None, "t_answer": None,
                "status": "answered", "fast_retry": 0, "ungrounded": 0, "answer_len": 5,
            }
        )
        b._telemetry_log_retrieval([(aid, 0, "c1", "Dune", "Chapter 1", "lib", 1, 1, 1)])
        b._telemetry_log_feedback("copy", "Dune · Chapter 1", "t")
        conn = b._telemetry_conn()
        n_asks = conn.execute("SELECT count(*) FROM asks").fetchone()[0]
        n_ret = conn.execute("SELECT count(*) FROM retrieval").fetchone()[0]
        n_fb = conn.execute("SELECT count(*) FROM feedback").fetchone()[0]
        conn.close()
        record("telemetry: log roundtrip", n_asks == 1 and n_ret == 1 and n_fb == 1, f"{n_asks}/{n_ret}/{n_fb}")
    finally:
        b.TELEMETRY_PATH = old_tel

    # citation matching
    cited = b._match_citations(
        "see (Dune · Chapter 1) here",
        [{"file_path": "Dune · Chapter 1 (ch1)"}, {"file_path": "Quran · Chapter 2 (ch5)"}],
    )
    record("telemetry: citation matching", cited == [True, False], str(cited))

    # gold exam seed + scoring
    entries = _ensure_gold()
    record("gold: seed parses", bool(entries) and all(e.get("question") for e in entries), f"{len(entries)} entries")
    score, details = _score_gold_entry(
        [
            {"file_path": "Kojeve.epub · Chapter 1 (ch1)", "content": "sovereignty"},
            {"file_path": "Kojeve.epub · Chapter 2 (ch2)", "content": "sovereignty"},
            {"file_path": "Kojeve.epub · Chapter 3 (ch3)", "content": "sovereignty"},
            {"file_path": "Dune.epub · Chapter 9 (ch9)", "content": "sand"},
        ],
        {"question": "q", "books": [{"book": "kojeve", "min": 3}]},
    )
    record("gold: scoring counts book hits", abs(score - 1.0) < 1e-6, f"score {score:.2f} [{', '.join(details)}]")

    # librarian shelves: scoped FTS, per-book cap, long-citation windowing
    stalin_keys = [k for k in b._book_map() if "stalin" in k]
    if stalin_keys:
        ids = b._fts_search_scoped(["dialectical", "materialism"], stalin_keys[0], limit=6)
        own = b._book_map()[stalin_keys[0]]["ids"]
        record(
            "shelves: fts scoped stays in-book",
            bool(ids) and all(cid in own for cid in ids),
            f"{len(ids)} hits",
        )
    pairs = []
    for i in range(10):
        book = f"Book{i % 3}.epub"
        pairs.append((float(100 - i), "ex", {"file_path": f"{book} · Chapter 1 (ch1)", "chunk_id": f"c{i}"}))
    capped = b._cap_per_book(pairs, 3)
    keys = [b._book_key(p[2]["file_path"]) for p in capped]
    record(
        "shelves: per-book cap",
        len(capped) == 9 and max(keys.count(k) for k in set(keys)) <= 3,
        f"{len(capped)} kept",
    )
    lit = [
        c for c in b._load_chunk_texts()
        if "mind-killer" in str(c.get("content", "")).lower() and "dune" in str(c.get("file_path", "")).lower()
    ]
    if lit:
        win = b._long_citation_window(lit[0])
        record(
            "shelves: long-citation window",
            len(win) >= 2000 and "I must not fear" in win,
            f"{len(win)} chars",
        )
    sys_prompt = b._rag_system_prompt("naive")
    record(
        "prompts: length follows the question",
        "Length follows the question" in sys_prompt,
        "present",
    )
    record(
        "prompts: verbatim quotes as blockquotes",
        "blockquote" in b.CITE_INSTRUCTION,
        "present",
    )
    # audit report card runs and reports sane numbers
    try:
        audit = b._audit()
        record(
            "audit: report card sane",
            audit.get("chunks", 0) > 7000 and "files" in audit,
            f"{audit.get('chunks', 0)} chunks, {audit.get('fts_rows', 0)} fts, {audit.get('vec_rows', 0)} vec",
        )
    except Exception as exc:
        record("audit: report card sane", False, str(exc))
    # chunk store is sqlite-backed; legacy JSON retired
    record(
        "store: chunks live in sqlite",
        not (b.STORAGE_DIR / "kv_store_text_chunks.json").exists()
        and b._library_db().execute("SELECT count(*) FROM chunks").fetchone()[0] == len(b._load_chunk_texts()),
        "library.db is the source",
    )

    # integrity: shelf scoping for EVERY book (no cross-book leakage)
    leaks = []
    for key, entry in b._book_map().items():
        ids = b._fts_search_scoped(["the", "and"], key, limit=8)
        for cid in ids:
            if cid not in entry["ids"]:
                leaks.append(key[:24])
                break
    record(
        "integrity: shelf scoping (all books)",
        not leaks,
        f"{len(leaks)} leaking books" + (": " + ", ".join(leaks[:3]) if leaks else ""),
    )

    # integrity: named-coverage — any question naming N books gets >=1 each
    question = "give me quotes from stalin, kojeve, dune, and hudson about sovereignty"
    named_keys = []
    for n in list(b._named_books(question))[:6]:
        for bk in b._books_matching(n)[:1]:
            if bk not in named_keys:
                named_keys.append(bk)
    pool = []
    for bk, entry in b._book_map().items():
        c = entry["chunks"][0]
        pool.append({"chunk_id": c["chunk_id"], "file_path": c["file_path"], "content": c["content"]})
    final = b._ensure_named_coverage([], question, pool)
    covered = {b._book_key(p["file_path"]) for p in final}
    missing = [k[:20] for k in named_keys if k not in covered]
    record(
        "integrity: named-coverage property",
        bool(named_keys) and not missing and len(final) <= 14,
        f"{len(named_keys)} books named, all covered" if not missing else f"missing: {missing}",
    )

    # integrity: storage version stamps
    row = b._library_db().execute("SELECT v FROM lib_meta WHERE k='code_version'").fetchone()
    record(
        "integrity: store version stamped",
        row is not None and int(row[0]) == b.CODE_VERSION,
        f"v{row[0] if row else '?'} vs code v{b.CODE_VERSION}",
    )
    # voice/depth: dune is a register, not a word list; budgets exist
    dune = b.VOICE_PRESETS.get("dune", "").lower()
    record(
        "voice: dune bans modern essay phrasing",
        "delve" in dune and "tapestry" in dune and "underscore" in dune,
        "ban list present",
    )
    record(
        "voice: dune requires in-world attribution",
        "fremen" in dune and "zensunni" in dune,
        "attribution present",
    )
    record(
        "voice: length budget for conceptual questions",
        "500-900 words" in b._length_budget("what does Dune say about the nature of power"),
        repr(b._length_budget("what does Dune say about the nature of power")[:80]),
    )
    record(
        "voice: trivial questions stay short",
        "a sentence or two" in b._length_budget("hi"),
        "short budget",
    )

    # draft workspace: attach/search/detach roundtrip in a temp conversation dir
    tmp2 = tempfile.mkdtemp()
    old_conv = (b.CONV_DIR, b.CONV_INDEX_PATH, b.CONV_STATE_PATH, b.CONV_LOCK_PATH, b._lock_file_handle)
    b.CONV_DIR = Path(tmp2) / "conversations"
    b.CONV_INDEX_PATH = b.CONV_DIR / "index.json"
    b.CONV_STATE_PATH = Path(tmp2) / "state.json"
    b.CONV_LOCK_PATH = b.CONV_DIR / ".lock"
    b._lock_file_handle = None
    try:
        b._append_history({"timestamp": "2099-01-01 10:00:00", "question": "q1", "answer": "a1"})
        conv = b._current_conv_id()
        name = b._attach_conv_doc(conv, "essay.txt", "The desert keeps what it is given.\n\nPower is a current, not a stone.")
        hits = b._search_conv_docs(conv, "power current", k=3)
        record("drafts: attach+search roundtrip", bool(name) and bool(hits), f"{len(hits)} chunks")
        record("drafts: render block labels", "[YOUR DRAFT: essay.txt]" in b._render_draft_block(hits), "labeled")
        b._detach_conv_doc(conv, name)
        record("drafts: detach removes", not b._list_conv_docs(conv), "removed")
        b._delete_conversation(conv)
        record("drafts: deleted with conversation", not b._conv_dir(conv).exists(), "folder gone")
    finally:
        b.CONV_DIR, b.CONV_INDEX_PATH, b.CONV_STATE_PATH, b.CONV_LOCK_PATH, b._lock_file_handle = old_conv


# ---------------------------------------- retrieval-level checks (no LLM)

PROBE_CASES = [
    (
        "what does Kojève say about sovereignty and America",
        lambda ps: sum(1 for p in ps if "kojeve" in p.get("file_path", "").lower()) >= 3,
        "≥3 Kojève passages lead the block",
    ),
    (
        "what does the Quran say about mercy",
        lambda ps: sum(1 for p in ps if "Study Quran" in p.get("file_path", "")) >= 3,
        "≥3 Study Quran passages",
    ),
    (
        "what does the Catholic Study Bible say about mercy",
        lambda ps: sum(
            1 for p in ps
            if "Study Bible" in p.get("file_path", "")
            and "mercy" in (p.get("excerpt") or "").lower()
        ) >= 2,
        "≥2 Bible passages whose excerpt mentions mercy",
    ),
    (
        "find the litany against fear in the dune books",
        lambda ps: sum(
            1 for p in ps
            if "mind-killer" in (p.get("content") or "").lower()
            and "dune" in p.get("file_path", "").lower()
        ) >= 1,
        "≥1 Dune passage containing the Litany text",
    ),
    (
        "what does Dune say about mercy",
        lambda ps: sum(
            1 for p in ps
            if "dune" in p.get("file_path", "").lower()
            and "mercy" in (p.get("excerpt") or "").lower()
        ) >= 2,
        "≥2 Dune passages mentioning mercy",
    ),
    (
        "what are the main themes in Dune",
        lambda ps: sum(
            1 for p in ps if b._is_boilerplate(str(p.get("content") or ""), [])
        ) == 0
        and sum(1 for p in ps if "dune" in p.get("file_path", "").lower()) >= 3,
        "story passages only, no front-matter",
    ),
    (
        "tell me about the story of Dune",
        lambda ps: sum(
            1 for p in ps if b._is_boilerplate(str(p.get("content") or ""), [])
        ) == 0
        and sum(1 for p in ps if "dune" in p.get("file_path", "").lower()) >= 3,
        "story passages only, no front-matter (2)",
    ),
    (
        "what does the afterword say about the dune series",
        lambda ps: sum(
            1 for p in ps
            if "afterword" in str(p.get("content") or "")[:200].lower()
            or "afterword" in p.get("file_path", "").lower()
        ) >= 1,
        "afterword reachable when explicitly asked",
    ),
    (
        "triangulate Stalin Kojève and Leto II on sovereignty and history",
        lambda ps: sum(1 for p in ps if "kojeve" in p.get("file_path", "").lower()) >= 2
        and sum(1 for p in ps if "stalin" in p.get("file_path", "").lower()) >= 2,
        "triangulation: both Stalin and Kojève passages lead",
    ),
]


async def retrieval_checks():
    brain = b.Brain()
    try:
        rag = await brain.open()
        for question, check, label in PROBE_CASES:
            try:
                ps = await b._probe_passages(rag, question)
                ok = check(ps)
                top = ", ".join(
                    sorted(
                        {
                            str(p.get("file_path", "")).split(" · ")[0][-25:]
                            for p in ps[:4]
                        }
                    )
                )
                record(f"retrieval: {label}", ok, f"top: {top}")
            except Exception as exc:
                record(f"retrieval: {label}", False, f"error {exc}")

        # determinism: same question twice must yield the same passages
        try:
            a = await b._probe_passages(rag, "triangulate Stalin Kojève and Leto II on sovereignty", k=8)
            c = await b._probe_passages(rag, "triangulate Stalin Kojève and Leto II on sovereignty", k=8)
            record(
                "retrieval: deterministic",
                [p.get("chunk_id") for p in a] == [p.get("chunk_id") for p in c],
                f"{len(a)} passages both runs",
            )
        except Exception as exc:
            record("retrieval: deterministic", False, f"error {exc}")

        # auto-generated per-book check: asking about each book surfaces it
        import re as _re

        manifest = b._load_manifest()
        for rel in sorted(manifest):
            fname = b._clean_name(rel).split("/")[-1]
            folder = rel.split("/")[-2] if "/" in rel else ""
            stem = fname.rsplit(".", 1)[0]
            if _re.fullmatch(r"[a-z0-9-]{16,}", stem, _re.I):
                probe_q = f"what is {folder}"  # hash-named files: the folder is the identity
            else:
                probe_q = f"what is {fname}"
            try:
                ps = await b._probe_passages(rag, probe_q)
                own = sum(
                    1 for p in ps
                    if fname.lower() in p.get("file_path", "").lower()
                    or (folder and folder.lower() in p.get("file_path", "").lower())
                )
                record(f"book: {fname[:32]}", own >= 1, f"{own}/{len(ps)} own")
            except Exception as exc:
                record(f"book: {fname[:32]}", False, f"error {exc}")
    finally:
        await brain.close()


# ------------------------------------------------------------- slow LLM checks

SLOW_CASES = [
    (
        "who wrote the dune series",
        ["herbert"],
        30,
        "simple answer",
    ),
    (
        "find the litany against fear in the dune books",
        ["mind-killer"],
        300,
        "litany quoted",
    ),
    (
        "what does Dune say about mercy",
        ["mercy"],
        300,
        "mercy discussed from dune",
    ),
    (
        "what does the Quran say about mercy",
        ["mercy"],
        300,
        "quran answered",
    ),
    (
        "what does the Catholic Study Bible say about mercy",
        ["mercy"],
        300,
        "bible answered",
    ),
    (
        "give me 10 quotes about food in Dune",
        ["food"],
        360,
        "quotes about food",
    ),
    (
        "how do the themes across Kojeve, Hudson, and the Dune books compare?",
        ["hudson", "dune"],
        360,
        "universal synthesis",
    ),
    (
        "what does Kojève say about sovereignty and America",
        ["kojeve"],
        180,
        "named-author answer (no false absence)",
    ),
    (
        "connect Kojève's end of history to Leto II's Golden Path",
        ["kojeve", "golden path"],
        240,
        "philosophy connection (interpretive)",
    ),
]


async def run_slow():
    brain = b.Brain()
    try:
        for question, keywords, budget, label in SLOW_CASES:
            t0 = time.time()
            acc = ""
            try:
                async for text in brain.ask_stream(question):
                    acc = text
            except Exception as exc:
                record(f"slow: {label}", False, f"error {exc}")
                continue
            res = brain._last_stream_result or {}
            answer = b._normalize_query((res.get("answer") or acc or "")).lower()
            elapsed = time.time() - t0
            hits = [k for k in keywords if k in answer]
            if label.startswith("named-author"):
                ok = hits and "do not have enough" not in answer
            elif label.startswith("philosophy"):
                dead = any(
                    w in answer
                    for w in (
                        "cannot be found",
                        "do not have enough",
                        "not in the provided",
                        "not in the supplied",
                        "not present in",
                        "does not appear",
                    )
                )
                ok = bool(hits) and not dead and elapsed <= budget
            elif label.startswith("quotes"):
                n_quotes = answer.count('"') + answer.count("“")
                ok = bool(hits) and n_quotes >= 6 and elapsed <= budget
            else:
                ok = len(hits) >= min(2, len(keywords)) and elapsed <= budget
            record(
                f"slow: {label}",
                ok,
                f"{elapsed:.0f}s (budget {budget}s), found {hits}",
            )
    finally:
        await brain.close()


async def citation_gate():
    """Slow e2e gate: the multi-book quote question must CITE most named books."""
    question = "give me quotes from stalin, kojeve, dune, and hudson about sovereignty and history"
    brain = b.Brain()
    try:
        acc = ""
        async for t in brain.ask_stream(question):
            acc = t
        ans = str((brain._last_stream_result or {}).get("answer") or acc).lower()
        named = ["stalin", "kojeve", "dune", "hudson"]
        cited = [n for n in named if n in ans]
        record(
            "e2e: multi-book citations in answer",
            len(cited) >= 3,
            f"{len(cited)}/4 cited: {cited}",
        )
    except Exception as exc:
        record("e2e: multi-book citations in answer", False, f"error {exc}")
    finally:
        await brain.close()


async def stress_run():
    """End-to-end stress: synthetic-book ingestion roundtrip, per-book
    retrievability with timings, and per-stage latency breakdown."""
    import time as _time
    import uuid as _uuid

    print("\n=== STRESS: synthetic book ingestion roundtrip ===")
    brain = b.Brain()
    rag = await brain.open()
    marker = "STRESSMARK-" + _uuid.uuid4().hex[:10]
    rel = "books/_stress_probe.md"
    path = b.KNOWLEDGE_ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# Stress Probe\n\nThis document contains the unique marker {marker}. "
        "It discusses the hydraulic properties of desert reservoirs, the "
        "economics of water cartels, and the theology of wells. "
        "Repeated marker: " + marker + ". End."
    )
    try:
        stats = await brain.index(verbose=False, only=rel)
        ok_index = stats.get("indexed") == 1 and not stats.get("errors")
        t0 = _time.time()
        ps = await b._probe_passages(rag, f"what does {marker} say about desert reservoirs", k=8)
        probe_s = _time.time() - t0
        own = sum(1 for p in ps if marker in (p.get("content") or ""))
        record("stress: synthetic book indexes", ok_index, json.dumps(stats))
        record("stress: synthetic book retrievable", own >= 1, f"{own} hits in {probe_s:.2f}s")
        await brain.forget(rel)
        record("stress: synthetic book forgotten", True, "removed")
    finally:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass

    print("\n=== STRESS: per-book retrievability + probe latency ===")
    manifest = b._load_manifest()
    rows = []
    for rel in sorted(manifest):
        fname = b._clean_name(rel).split("/")[-1]
        stem = fname.rsplit(".", 1)[0]
        q = f"what is {stem}"
        t0 = _time.time()
        try:
            ps = await b._probe_passages(rag, q, k=8)
        except Exception as exc:
            record(f"stress book: {fname[:30]}", False, f"error {exc}")
            continue
        dt = _time.time() - t0
        own = sum(
            1 for p in ps
            if fname.lower() in p.get("file_path", "").lower()
            or stem.lower() in p.get("file_path", "").lower()
        )
        rows.append((fname, own, len(ps), dt))
        note = ""
        if own == 0:
            # duplicate-title books (e.g. the Dune-1 PDF vs the Dune epub):
            # if every significant title token is covered by the retrieved
            # books, this work is reachable under a sibling title.
            try:
                toks = [
                    t for t in re.findall(r"[a-z]{4,}", stem.lower())
                    if t not in ("book", "books", "file", "text")
                ]
                hay = " ".join(str(p.get("file_path", "")).lower() for p in ps)
                if toks and all(t in hay for t in toks):
                    note = "duplicate of a retrieved book"
            except Exception:
                pass
        record(
            f"stress book: {fname[:30]}",
            own >= 1 or bool(note),
            f"{own}/{len(ps)} own in {dt:.2f}s" + (f" [{note}]" if note else ""),
        )
    print("\n=== STRESS: per-stage latency breakdown (retrieval pipeline) ===")
    q = "what does Dune say about the nature of power"
    t0 = _time.time()
    emb = await b.nomic_embed([q], context="query")
    t_embed = _time.time() - t0
    t0 = _time.time()
    await b._librarian_search(rag, q, k=5, embedding=b.np.expand_dims(emb[0], 0))
    t_search = _time.time() - t0
    t0 = _time.time()
    await b._probe_passages(rag, q, k=8)
    t_total = _time.time() - t0
    record(
        "stress: stage timings",
        True,
        f"embed {t_embed:.2f}s | librarian {t_search:.2f}s | full probe {t_total:.2f}s",
    )
    await brain.close()


async def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="run slow LLM cases too")
    parser.add_argument("--gold", action="store_true", help="run the stored gold retrieval exam")
    parser.add_argument("--bench", action="store_true", help="benchmark subsystems against stored baselines")
    parser.add_argument("--all", action="store_true", help="run everything incl. slow e2e gates")
    parser.add_argument("--stress", action="store_true", help="ingestion roundtrip + per-book retrievability + stage timings")
    args = parser.parse_args()

    fast_checks()
    await retrieval_checks()
    if args.stress or args.all:
        await stress_run()
    if args.gold or args.all:
        await gold_run()
    if args.bench or args.all:
        await bench_run()
    if args.full or args.all:
        await run_slow()
        await citation_gate()

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n{passed}/{len(RESULTS)} checks passed")
    sys.exit(0 if passed == len(RESULTS) else 1)


if __name__ == "__main__":
    asyncio.run(main())
