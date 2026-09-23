"""Mentat verification harness.

Run all checks:        python verify.py
Unit checks only:      python verify.py --quick
Recent history:        python verify.py --history [--limit N]

Every check appends a structured result to storage/verification.jsonl and
logs verify_pass / verify_fail into the telemetry feedback table, so the
history is visible from inside the app (`brain stats` shows the counts and
`brain verify --history` prints the detail).

Exit code is 0 when every check passes, 1 otherwise — safe for automation.
"""
import argparse
import asyncio
import inspect
import json
import re
import sys
import time
import uuid
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))

import brain_core as bc

VERIFY_LOG = bc.STORAGE_DIR / "verification.jsonl"

PASS = "PASS"
FAIL = "FAIL"


def _log_result(run_id, name, ok, detail, ms):
    row = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "run_id": run_id,
        "check": name,
        "status": PASS if ok else FAIL,
        "detail": str(detail)[:300],
        "ms": int(ms),
    }
    try:
        VERIFY_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(VERIFY_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass
    try:
        bc._telemetry_log_feedback(
            "verify_pass" if ok else "verify_fail",
            f"{name}: {row['detail'][:160]}",
        )
    except Exception:
        pass
    return row


# --------------------------------------------------------------------------
# Unit checks (fast, no retrieval)
# --------------------------------------------------------------------------


def check_census_phrase_shapes():
    cases = [
        ("list me all the times allah or god is mentioned in the quran", "allah or god"),
        ("list me all the times the eyes of ibad are mentioned", "eyes of ibad"),
        ("find me all the instances of eys of ibad in the dune series", "eys of ibad"),
        (
            "in the entire dune series, how often does the litany against fear appear",
            "litany against fear",
        ),
        ("show me where the litany against fear shows up", "litany against fear"),
        # case-insensitive preamble stripping (caught by a live false-zero:
        # "How many times does the word mercy appear in the Quran")
        ("How many times does the word mercy appear in the Quran", "mercy"),
        ("how many times does the word mercy appear in the quran", "mercy"),
        ("How many times does Paul appear in Dune", "Paul"),
    ]
    bad = []
    for q, want in cases:
        got = bc._census_phrase(q)
        if got != want:
            bad.append(f"{q[:50]!r} -> {got!r} (want {want!r})")
    return (not bad), ("; ".join(bad) if bad else f"{len(cases)} shapes correct")


def check_census_e2e_mercy():
    """The live false-zero: 'mercy' must NOT count 0 in the Study Quran."""
    ctx = bc._census_ctx(
        "How many times does the word mercy appear in the Quran", "agent"
    )
    block = ctx.get("block") or ""
    bad = []
    if str(ctx.get("phrase") or "") != "mercy":
        bad.append(f"phrase {ctx.get('phrase')!r} != 'mercy'")
    m = re.search(r"Study Quran.*?— (\d+):", block)
    if not m:
        bad.append("no Study Quran count in the census block")
    elif int(m.group(1)) < 100:
        bad.append(f"mercy counted {m.group(1)} (absurdly low for this corpus)")
    if "0: nowhere" in block:
        bad.append("census reports 'nowhere' for mercy")
    return (
        not bad,
        "; ".join(bad) if bad else f"mercy census correct ({m.group(1)} occurrences)",
    )


def check_census_or_variants():
    q1 = "list me all the times allah or god is mentioned in the quran"
    reask = (
        "list me all the times God is mentioned in the quran, or allah, "
        "or any other variation of that, in a number"
    )
    bad = []
    if bc._census_or_phrases(q1) != ["allah", "god"]:
        bad.append(f"q1 -> {bc._census_or_phrases(q1)!r}")
    if bc._census_or_phrases(reask) != ["God", "allah"]:
        bad.append(f"reask -> {bc._census_or_phrases(reask)!r}")
    if bc._census_or_phrases("list me all the times the eyes of ibad are mentioned"):
        bad.append("non-OR question produced variants")
    junk = bc._census_or_phrases("how many times does the word variation appear, or form")
    if junk and all(t.lower() in bc._CENSUS_ALT_JUNK for t in junk):
        bad.append(f"junk variants survived: {junk!r}")
    return (not bad), ("; ".join(bad) if bad else "OR splitting correct")


def check_census_diacritics():
    pat = bc._census_pattern(["allah"])
    want = {"Allah": True, "Allāh": True, "ALLAH": True, "allahu": False}
    bad = [s for s, ok in want.items() if bool(pat.search(s)) != ok]
    n = bc._census_count_in("Allāh and Allah, allah.", ["allah"])
    if n != 3:
        bad.append(f"count of 'Allāh and Allah, allah.' = {n} (want 3)")
    return (not bad), ("; ".join(bad) if bad else "diacritic folding correct (Allāh = allah)")


def check_census_junk_guard():
    # A bare request word must never survive as a countable phrase.
    for q in (
        "list me all the times allah or god is mentioned in the quran",
        "list me all the times the eyes of ibad are mentioned",
    ):
        p = bc._census_phrase(q)
        if p in ("list", "times", "all"):
            return False, f"machinery word {p!r} became the phrase for {q[:40]!r}"
    return True, "machinery-only candidates rejected"


def check_data_integrity():
    chunks = bc._load_chunk_texts()
    fts = bc._fts_db().execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
    vec = bc._vec_db().execute("SELECT count(*) FROM chunks_vec").fetchone()[0]
    spans = bc._library_db().execute(
        "SELECT count(*), count(DISTINCT chunk_id) FROM spans"
    ).fetchone()
    bad = []
    if not chunks:
        bad.append("chunk store empty")
    if fts != len(chunks):
        bad.append(f"fts rows {fts} != chunks {len(chunks)}")
    if vec != len(chunks):
        bad.append(f"vec rows {vec} != chunks {len(chunks)}")
    if spans[0] == 0:
        bad.append("span index empty — run `brain spans --build`")
    elif spans[1] != len(chunks):
        bad.append(f"spans cover {spans[1]} of {len(chunks)} chunks")
    if not bc._store_ok():
        bad.append("storage version stale — restart or re-index")
    return (
        not bad,
        "; ".join(bad)
        if bad
        else f"{len(chunks)} chunks, fts+vec in sync, {spans[0]:,} spans",
    )


def check_span_search():
    bad = []
    hits = bc._span_search(["eyes of the ibad"], limit=5)
    if not hits:
        return False, "span search found nothing for 'eyes of the ibad'"
    if not any("eyes of the ibad" in (h.get("text") or "").lower() for h in hits):
        bad.append("span hits lack the exact phrase")
    if any(h.get("start") is None or h.get("end") is None for h in hits):
        bad.append("span hits missing offsets")
    hunt = bc._hunt_passages("find: the litany against fear", limit=10)
    anchored = sum(1 for h in hunt if h.get("span"))
    if not hunt:
        bad.append("hunt returned nothing")
    elif anchored == 0:
        bad.append("hunt results are not span-anchored")
    return (
        not bad,
        "; ".join(bad)
        if bad
        else f"span phrase hits {len(hits)}, hunt {anchored}/{len(hunt)} anchored",
    )


def check_source_regressions():
    """Static guards for bugs that shipped once and must never return."""
    src = (APP_DIR / "brain_core.py").read_text(encoding="utf-8")
    bad = []
    if "docs_count=len(doc_chunks)" in src:
        bad.append("docs_count still records doc_chunks")
    if src.count("docs_count=len(passages)") < 2:
        bad.append("docs_count fix missing from ask/ask_stream")
    if '"deepseek-chat" if r_first' in src:
        bad.append("invalid deepseek-chat retry is back")
    if "_RETRIEVAL_ERRORS.clear()" not in src:
        bad.append("retrieval degradation tracking missing")
    cli_src = (APP_DIR / "brain.py").read_text(encoding="utf-8")
    if "def cmd_kill" not in cli_src:
        bad.append("mentat kill (lock recovery) missing")
    tui_src = (APP_DIR / "brain_tui.py").read_text(encoding="utf-8")
    if "mentat kill" not in tui_src:
        bad.append("lock message does not point at mentat kill")
    return (not bad), ("; ".join(bad) if bad else "no regressions in source guards")


def check_model_config():
    settings = bc._load_settings()
    resolved = bc.resolve_model(settings.get("model") or "")
    bad = []
    if not resolved:
        bad.append("settings model resolves to empty")
    for key, val in bc.MODEL_PRESETS.items():
        if not val:
            bad.append(f"preset {key!r} empty")
    if bc.resolve_model("deepseek-flash") != "deepseek-flash":
        bad.append("deepseek-flash preset broken")
    # legacy saved names must resolve to canonical ids
    if bc.resolve_model("deepseek-chat") != "deepseek-flash":
        bad.append("legacy deepseek-chat does not resolve to flash")
    if bc.resolve_model("deepseek-v4-flash") != "deepseek-flash":
        bad.append("legacy deepseek-v4-flash does not resolve to flash")
    if bc.resolve_model("deepseek-think") != "deepseek-v4-pro":
        bad.append("deepseek-think preset broken")
    return (not bad), ("; ".join(bad) if bad else f"model {settings.get('model')!r} -> {resolved!r}")


def check_provider_routing():
    bad = []
    prov, _base, key, wire = bc.resolve_provider(bc.resolve_model("deepseek-chat"))
    if prov != "deepseek" or wire != "deepseek-flash" or not key:
        bad.append(f"legacy alias misroutes: {prov}/{wire}/key={bool(key)}")
    prov, _base, _key, wire = bc.resolve_provider(
        "openrouter/deepseek/deepseek-v4.1-flash"
    )
    if prov != "openrouter" or wire != "deepseek/deepseek-v4.1-flash":
        bad.append(f"openrouter prefix misroutes: {prov}/{wire}")
    prov, _base, _key, wire = bc.resolve_provider("moonshot/kimi-k3")
    if prov != "moonshot" or wire != "kimi-k3":
        bad.append(f"moonshot prefix misroutes: {prov}/{wire}")
    prov, _base, _key, wire = bc.resolve_provider("qwen-deep")
    if prov or wire != "qwen-deep":
        bad.append(f"local model should have no provider: {prov}/{wire}")
    if bc.model_label("deepseek-chat") != "deepseek flash (v4.1)":
        bad.append(f"label(deepseek-chat) = {bc.model_label('deepseek-chat')!r}")
    if bc.model_label("deepseek-think") != "deepseek pro":
        bad.append(f"label(deepseek-think) = {bc.model_label('deepseek-think')!r}")
    if bc.model_label("kimi-k3") != "kimi (kimi-k3)":
        bad.append(f"label(kimi-k3) = {bc.model_label('kimi-k3')!r}")
    return (
        not bad,
        "; ".join(bad)
        if bad
        else "provider prefixes + canonical labels OK",
    )


def check_models_canary():
    """Live canary: record what each remote model id actually serves."""
    if bc._offline() or not bc.DEEPSEEK_API_KEY:
        return True, "skipped (offline or no key)"

    async def _probe(model):
        return await bc.remote_llm(
            "Reply with exactly: ok",
            model=model,
            base_url=bc.DEEPSEEK_BASE_URL,
            api_key=bc.DEEPSEEK_API_KEY,
            provider="deepseek",
            max_tokens=4000,
            timeout=90,
        )

    try:
        flash = asyncio.run(_probe("deepseek-flash"))
        pro = asyncio.run(_probe("deepseek-v4-pro"))
    except Exception as exc:
        return False, f"canary call failed: {type(exc).__name__}: {str(exc)[:80]}"
    if "ok" not in str(flash or "").lower():
        return False, f"flash canary unexpected reply: {str(flash)[:40]!r}"
    if "ok" not in str(pro or "").lower():
        return False, f"pro canary unexpected reply: {str(pro)[:40]!r}"
    return True, "flash (v4.1) + pro both answering through the provider seam"


def check_thinking_structures():
    bad = []
    src = (APP_DIR / "brain_core.py").read_text(encoding="utf-8")
    if "scratch=None" not in src or "scratch=scratch" not in src:
        bad.append("planner scratchpad not wired")
    thin = bc._coverage_note(
        {"books": 1, "names": ["Dune"], "chunks": 9}, "research", "agent"
    )
    rich = bc._coverage_note(
        {"books": 3, "names": ["a", "b", "c"], "chunks": 9}, "research", "agent"
    )
    quiet = bc._coverage_note(
        {"books": 1, "names": ["Dune"], "chunks": 9}, "quotes", "agent"
    )
    if not thin or "Dune" not in thin:
        bad.append("thin coverage note missing")
    if rich:
        bad.append("coverage note fired with multi-book evidence")
    if quiet:
        bad.append("coverage note fired for a non-cross-book kind")
    cov = bc._evidence_coverage(
        [
            {"file_path": "Dune (Frank Herbert) .epub · Chapter 1 (ch1)"},
            {"file_path": "Dune (Frank Herbert) .epub · Chapter 2 (ch2)"},
            {"file_path": "Dune Messiah (Frank Herbert) .epub · Chapter 1 (ch1)"},
        ]
    )
    if cov["books"] != 2 or cov["chunks"] != 3:
        bad.append(f"evidence coverage wrong: {cov}")
    return (not bad), ("; ".join(bad) if bad else "scratchpad + coverage note verified")


def check_memory_injection():
    real = bc._load_memory_facts
    fake = [
        ("default", "Raphael prefers concise answers about Dune."),
        ("default", "The blue-within-blue eyes matter."),
    ]
    try:
        bc._load_memory_facts = lambda: fake
        hits = bc._memory_matches("what did I say about Dune answers?")
        block = bc._render_memory_block(hits)
        if not hits:
            return False, "memory match found nothing for an overlapping question"
        if "Dune" not in block:
            return False, "memory block missing the fact"
        if bc._memory_matches("zzz qqq unrelated"):
            return False, "memory matched an unrelated question"
    finally:
        bc._load_memory_facts = real
    return True, f"memory retrieval + block render OK ({len(hits)} hit)"


def check_feedback_ranking():
    try:
        bc._refresh_negative_chunks()
    except Exception as exc:
        return False, f"negative-chunk refresh raised {exc}"
    if not isinstance(bc._NEGATIVE_CHUNKS, set):
        return False, "negative chunk store is not a set"
    src = (APP_DIR / "brain_core.py").read_text(encoding="utf-8")
    if "_refresh_negative_chunks()" not in src or "score *= 0.9" not in src:
        return False, "feedback penalty not wired into ranking"
    return True, f"soft-negative ranking OK ({len(bc._NEGATIVE_CHUNKS)} chunks labelled)"


def check_renamed_to_mentat():
    bad = []
    tui = (APP_DIR / "brain_tui.py").read_text(encoding="utf-8")
    brain = (APP_DIR / "brain.py").read_text(encoding="utf-8")
    mcp = (APP_DIR / "brain_mcp.py").read_text(encoding="utf-8")
    if "SecondBrainApp" in tui or "SECOND BRAIN" in tui:
        bad.append("TUI still uses the old branding/class")
    if 'TITLE = "Mentat"' not in tui:
        bad.append("TUI title is not Mentat")
    if 'figlet_format("MENTAT"' not in brain:
        bad.append("CLI banner is not Mentat")
    if 'MCPServer("mentat")' not in mcp:
        bad.append("MCP server is not named mentat")
    if not (APP_DIR / "Mentat.command").exists():
        bad.append("Mentat.command missing")
    if (APP_DIR / "Second Brain.command").exists():
        bad.append("old Second Brain.command still present")
    if str(bc.KNOWLEDGE_ROOT).endswith("second brain"):
        bad.append(f"vault still resolves to the old path: {bc.KNOWLEDGE_ROOT}")
    return (not bad), ("; ".join(bad) if bad else f"renamed; vault at {bc.KNOWLEDGE_ROOT}")


def check_phonetic_matching():
    bad = []
    if bc._soundex("fear") != bc._soundex("feer"):
        bad.append("soundex(fear) != soundex(feer)")
    cands = bc._phonetic_match("feer")
    if "fear" not in cands:
        bad.append(f"phonetic candidates for 'feer' missing 'fear': {cands[:5]}")
    hits = bc._hunt_passages("find: the litany of feer", limit=8)
    if not any("litany" in (p.get("content") or "").lower() for p in hits):
        bad.append("phonetic hunt failed to find the litany")
    return (
        not bad,
        "; ".join(bad) if bad else f"phonetic recall OK ({len(cands)} candidates)",
    )


async def check_model_roles():
    bad = []
    defaults = bc.SETTINGS_DEFAULTS
    for key in ("planner_model", "synth_model"):
        if key not in defaults:
            bad.append(f"settings key {key} missing")
    # every declared setting must survive the coercion round-trip
    for key, value in (
        ("synth_model", "deepseek-think"),
        ("planner_model", ""),
        ("agent_rounds", 0),
    ):
        try:
            bc._coerce_setting(key, value)
        except ValueError as exc:
            bad.append(f"_coerce_setting({key}) failed: {exc}")
    settings = bc._load_settings()
    if settings.get("synth_model"):
        # a configured synth model must resolve to a known engine
        resolved = bc.resolve_model(settings["synth_model"])
        if not resolved:
            bad.append("configured synth_model does not resolve")
    route = await bc._route_model("test")
    if route not in ("deepseek-flash", "deepseek-think", "qwen", "qwen-deep", None):
        bad.append(f"unexpected default route: {route!r}")
    if not bc._offline() and not bc._load_settings().get("synth_model") and route != "deepseek-flash":
        bad.append(f"default synth should be flash (A/B verdict), got {route!r}")
    return (not bad), ("; ".join(bad) if bad else "planner/synth role settings wired")


def check_book_mode():
    bad = []
    if not hasattr(bc, "remote_llm"):
        bad.append("remote_llm (multi-provider client) missing")
    if bc._WHOLE_BOOK_MAX_CHARS < 100000:
        bad.append("whole-book cap is implausibly small")
    # plumbing test that cannot trigger a giant API call: unknown work only
    result = asyncio.run(bc.Brain().book_ask("zzz-definitely-no-such-work", "test"))
    if result.get("status") not in ("not_found", "offline", "no_key"):
        bad.append(f"unexpected book_ask status {result.get('status')!r}")
    core_src = (APP_DIR / "brain_core.py").read_text(encoding="utf-8")
    if "offline mode is on — whole-book mode needs" not in core_src:
        bad.append("book_ask offline guard missing")
    long_model = str(bc._load_settings().get("long_context_model") or "")
    provider, _base, _key, _wire = bc.resolve_provider(bc.resolve_model(long_model))
    if provider == "moonshot" and not bc.MOONSHOT_API_KEY:
        bad.append("long_context_model defaults to a keyless provider")
    src = (APP_DIR / "brain.py").read_text(encoding="utf-8")
    if 'add_parser("book"' not in src:
        bad.append("brain book CLI missing")
    return (
        not bad,
        "; ".join(bad)
        if bad
        else f"whole-book wired ({long_model or 'default'} → {provider or 'local'})",
    )


def check_enrichment():
    bad = []
    ctx = bc._load_contexts()
    chunks = bc._load_chunk_texts()
    if len(ctx) < len(chunks):
        bad.append(
            f"contexts {len(ctx)} < chunks {len(chunks)} (run brain enrich --contexts)"
        )
    llm_n = sum(1 for v in ctx.values() if v.startswith("[llm]"))
    vec_meta = {}
    try:
        vec_meta = dict(bc._vec_db().execute("SELECT k, v FROM vec_meta").fetchall())
    except Exception:
        pass
    enriched = int(vec_meta.get("enriched", 0) or 0)
    if enriched and enriched < len(chunks):
        bad.append(f"embedding index partially enriched ({enriched}/{len(chunks)})")
    if not enriched:
        bad.append("embeddings not enriched yet (run brain enrich --embed)")
    if enriched and vec_meta.get("embed_model") not in (None, "", bc.OLLAMA_EMBED_MODEL):
        bad.append(f"embed model mismatch: {vec_meta.get('embed_model')!r}")
    return (
        not bad,
        "; ".join(bad)
        if bad
        else f"{enriched:,}/{len(chunks)} enriched embeddings, {llm_n:,} llm contexts",
    )


def check_entity_graph():
    bad = []
    info = bc._graph_related("fremen")
    if not info["count"]:
        bad.append("graph has no 'fremen' entity (run brain graph --build)")
    names = {n.lower() for n, _ in info["related"]}
    if info["count"] and not ({"paul", "leto", "stilgar", "arrakis"} & names):
        bad.append(f"fremen co-occurrence looks wrong: {sorted(names)[:6]}")
    try:
        e = bc._graph_db().execute("SELECT count(*) FROM entities").fetchone()[0]
    except Exception:
        e = 0
    if e < 100:
        bad.append(f"graph only has {e} entities")
    return (
        not bad,
        "; ".join(bad) if bad else f"graph OK ({e:,} entities, fremen x{info['count']})",
    )


def check_gold_regressions():
    """Known-answer cases from real failures — expanded gold set."""
    cases = [
        # (question, expectation kind, expected)
        (
            "how many times is the word melange mentioned in dune",
            "phrase_contains",
            "melange",
        ),
        (
            "how many times does paul say \"fear is the mind-killer\"",
            "phrase_contains",
            "fear is the mind-killer",
        ),
        (
            "list me all the times the eyes of ibad are mentioned",
            "phrase_eq",
            "eyes of ibad",
        ),
    ]
    bad = []
    for q, kind, expected in cases:
        got = bc._census_phrase(q)
        if kind == "phrase_contains":
            if not got or expected.lower() not in got.lower():
                bad.append(f"{q[:44]!r} -> {got!r} (want ~{expected!r})")
        elif got != expected:
            bad.append(f"{q[:44]!r} -> {got!r} (want {expected!r})")
    hits = bc._hunt_passages("find: fear is the mind killer", limit=8)
    if not any("mind-killer" in (p.get("content") or "").lower() for p in hits):
        bad.append("hunt missed 'mind-killer'")
    return (not bad), ("; ".join(bad) if bad else f"{len(cases)} gold cases + hunt OK")


def check_scope_priority():
    """Named works must dominate cross-book evidence; sweeps are capped."""
    dune_path = "Dune (Frank Herbert) .epub · Chapter 1 (ch1)"
    bible_path = "The Catholic Study Bible (ed.) .epub · Book 1 (ch1)"
    dune_key = bc._book_key(dune_path)
    bible_key = bc._book_key(bible_path)

    def p(cid, path):
        return {"chunk_id": cid, "file_path": path}

    scope = [
        {"id": "dune", "keys": {dune_key}, "demand": True, "hits": 6},
        {"id": "bible", "keys": {bible_key}, "demand": False, "hits": 9},
    ]
    pool = {
        "dune": [p(f"d{i}", dune_path) for i in range(6)],
        "bible": [p(f"b{i}", bible_path) for i in range(9)],
    }
    final = [p("b0", bible_path), p("b1", bible_path)]
    out = bc._ensure_scope_coverage(final, scope, pool, cap_total=30)
    dune_n = sum(1 for x in out if "Dune" in x["file_path"])
    bible_n = sum(1 for x in out if "Catholic" in x["file_path"])
    bad = []
    if dune_n < 3:
        bad.append(f"named work got only {dune_n} passages")
    if bible_n > 3:
        bad.append(f"non-named sweep kept {bible_n} passages (should be capped)")
    return (
        not bad,
        "; ".join(bad) if bad else f"named quota OK (dune {dune_n}, other {bible_n})",
    )


def check_ranking_and_budget():
    bad = []
    core_src = (APP_DIR / "brain_core.py").read_text(encoding="utf-8")
    if 'kwargs["timeout"] = 240 if heavy else 90' not in core_src:
        bad.append("per-call timeout budget missing (a half-closed API can hang a question)")
    if "_NEGATIVE_CHUNKS" not in core_src or "score *= 0.9" not in core_src:
        bad.append("reask/stop soft-negative ranking missing")
    return (
        not bad,
        "; ".join(bad) if bad else "timeout budget + feedback ranking OK",
    )


def check_quote_attribution():
    bad = []
    p = {
        "file_path": "Dune (Frank Herbert) .epub · Chapter 31 (ch37)",
        "content": "He has not the eyes of the ibad. Yet he does not speak or act "
        "like a weakling of the pans.",
    }
    label = bc._citation_for(p)
    if label != "Dune · Chapter 31":
        bad.append(f"_citation_for -> {label!r}")
    answer = 'The text says "He has not the eyes of the ibad." and moves on.'
    fixed, n = bc._ensure_quote_attribution(answer, [p])
    if n != 1:
        bad.append(f"inserted {n} attributions (want 1)")
    if "(Dune · Chapter 31)" not in fixed:
        bad.append(f"citation not inserted: {fixed[:140]!r}")
    cited = 'As it says "He has not the eyes of the ibad." (Dune · Chapter 31) and more.'
    untouched, n2 = bc._ensure_quote_attribution(cited, [p])
    if n2 != 0:
        bad.append("re-attributed an already-cited quote")
    unknown, n3 = bc._ensure_quote_attribution(
        'Quote "this sentence is nowhere in the evidence at all."', [p]
    )
    if n3 != 0:
        bad.append("attributed a quote that is not in the evidence")
    return (
        not bad,
        "; ".join(bad) if bad else "quote attribution deterministic pass OK",
    )


def check_reference_filtering():
    passages = [
        {"file_path": "Dune (Frank Herbert) .epub · Chapter 1 (ch6)", "content": "x"},
        {"file_path": "The Catholic Study Bible (ed.) .epub · Book 1 (ch1)", "content": "y"},
    ]
    answer = 'Dune says the litany matters.\n\n### References\n\n- [9] stale'
    out = bc._rewrite_references(answer, passages)
    bad = []
    if "Dune" not in out:
        bad.append("cited book dropped from references")
    if "Catholic" in out:
        bad.append("uncited book kept in references")
    if "stale" in out:
        bad.append("old references section not replaced")
    return (
        not bad,
        "; ".join(bad) if bad else "references filtered to cited works",
    )


def check_settings_spec():
    bad = []
    spec_keys = {s["key"] for s in bc.SETTINGS_SPEC}
    for key, default in bc.SETTINGS_DEFAULTS.items():
        if key not in spec_keys:
            bad.append(f"{key} has no menu entry")
        try:
            bc._coerce_setting(key, default)
        except Exception as exc:
            bad.append(f"coerce {key}={default!r} failed: {exc}")
    for key in spec_keys:
        if key not in bc.SETTINGS_DEFAULTS:
            bad.append(f"menu key {key} has no default")
    src = (APP_DIR / "brain_core.py").read_text(encoding="utf-8")
    tui_src = (APP_DIR / "brain_tui.py").read_text(encoding="utf-8")
    combined = src + tui_src
    for key in (
        "spans_enabled",
        "coverage_notes",
        "auto_attribution",
        "filter_references",
        "learning_from_feedback",
        "hunt_limit",
        "hunt_cache_ttl",
        "long_context_model",
        "auto_offline",
    ):
        if f'get("{key}"' not in combined:
            bad.append(f"{key} is declared but never read")
    if "class _OptButton" not in tui_src or ".opt-picker" not in tui_src:
        bad.append("settings menu click/layout regression (buttons or picker sizing)")
    if "opt-name-btn" not in tui_src:
        bad.append("click-name-to-cycle picker affordance missing")
    if "settings-help" not in tui_src:
        bad.append("hover explainer bar missing")
    return (
        not bad,
        "; ".join(bad)
        if bad
        else f"{len(bc.SETTINGS_DEFAULTS)} settings live, coercible, and wired",
    )


def check_voice_presets():
    bad = []
    for name, text in bc.VOICE_PRESETS.items():
        if name == "default":
            continue
        for marker in ("GRAMMAR", "TABOO"):
            if marker not in text:
                bad.append(f"{name} lacks {marker} directives")
    for name in bc.VOICE_PRESETS:
        if name not in bc.NO_ANSWER_FALLBACKS:
            bad.append(f"{name} has no no-answer fallbacks")
    try:
        if bc._coerce_setting("voice", "mentat") != "mentat":
            bad.append("new voices not settable")
    except Exception as exc:
        bad.append(f"voice coercion failed: {exc}")
    return (
        not bad,
        "; ".join(bad)
        if bad
        else f"{len(bc.VOICE_PRESETS)} voices grammar-driven with fallbacks",
    )


def check_cost_model():
    bad = []
    flash = bc.MODEL_PRICES.get("deepseek-flash", {})
    pro = bc.MODEL_PRICES.get("deepseek-v4-pro", {})
    kimi = bc.MODEL_PRICES.get("kimi-k3", {})
    if abs((flash.get("in_off", 0) + flash.get("out_off", 0)) - 0.75) > 1e-9:
        bad.append("flash off-peak price drift")
    if pro.get("out") != 3.96:
        bad.append("pro price drift")
    if kimi.get("out") != 15.0:
        bad.append("kimi price drift")
    if bc._price_for("qwen-deep") is not None:
        bad.append("local model must be free")
    if bc._price_for("deepseek-chat") is None:
        bad.append("legacy alias has no price mapping")
    core = (APP_DIR / "brain_core.py").read_text(encoding="utf-8")
    if 'get("daily_budget"' not in core:
        bad.append("daily_budget setting is not read")
    if "cost_usd=estimate_cost" not in core:
        bad.append("cost is not recorded on ask flush")
    if "tokens_in" not in core or "tokens_out" not in core:
        bad.append("token usage not persisted")
    return (
        not bad,
        "; ".join(bad)
        if bad
        else "price table + budget guard + cost telemetry wired",
    )


def check_register_system():
    bad = []
    cases = {
        "what does Kull wahad mean": "concept",
        "who is Leto II": "concept",
        "compare asabiyyah and the ummah": "compare",
        "how many times does the word mercy appear in the quran": "count",
        "quote the litany against fear": "quotes",
        "why does Paul accept the jihad": "commentary",
        "trace the Mahdi across all six books": "research",
    }
    for q, want in cases.items():
        got = bc._heuristic_kind(q)
        if got != want:
            bad.append(f"{q[:36]!r} -> {got} (want {want})")
    secs = bc._sections_for_kind("what does Kull wahad mean", "concept")
    if "terminology of" not in secs:
        bad.append("concept register does not license apparatus")
    if "terminology of" in bc._sections_for_kind("quote the litany", "quotes"):
        bad.append("quotes register must not license apparatus")
    fp = "Dune (Frank Herbert) .epub · TERMINOLOGY OFTHE IMPERIUM (ch61)"
    content = "Kull wahad: an exclamation of astonishment."
    if bc._is_boilerplate(content, secs, file_path=fp):
        bad.append("terminology chunk filtered for a concept question")
    if not bc._is_boilerplate(
        content, bc._query_sections("what does Kull wahad mean"), file_path=fp
    ):
        bad.append("terminology chunk not filtered for non-apparatus questions")
    if "ONCE" not in bc._register_instruction("concept"):
        bad.append("concept register instruction missing")
    if bc._register_instruction("count"):
        bad.append("count register must not get the concept instruction")
    return (
        not bad,
        "; ".join(bad) if bad else "register classifier + apparatus rules OK",
    )


def check_register_retrieval():
    """The Kull-wahad wound: a concept question must reach the glossary."""
    try:
        hits = asyncio.run(
            bc._librarian_search("what does Kull wahad mean", k=8)
        )
    except Exception as exc:
        return True, f"skipped (retrieval unavailable: {type(exc).__name__})"
    apparatus = [p for p in hits if "TERMINOLOGY" in str(p.get("file_path", "")).upper()]
    if not apparatus:
        files = [str(p.get("file_path", ""))[:50] for p in hits[:3]]
        return False, f"no apparatus passage for a concept question (top: {files})"
    return True, f"glossary reached ({len(apparatus)} apparatus passage(s))"


def check_self_heal():
    bad = []
    for event, voices in bc.SELF_HEAL_QUIPS.items():
        for v in ("default", "dune", "prophet", "mentat", "chronicle"):
            if not voices.get(v):
                bad.append(f"quip {event}/{v} missing")
    if bc.quip("bug_found", voice="default") != bc.SELF_HEAL_QUIPS["bug_found"]["default"]:
        bad.append("quip() ignores an explicit voice")
    if bc.quip("bug_found", voice="dune") == bc.SELF_HEAL_QUIPS["bug_found"]["default"]:
        bad.append("quip() is not voice-aware")
    issues = bc._self_heal_scan_sync()
    if not isinstance(issues, list) or any(len(i) != 4 for i in issues):
        bad.append("scan shape wrong")
    core = (APP_DIR / "brain_core.py").read_text(encoding="utf-8")
    if "async def self_heal_run" not in core:
        bad.append("self_heal_run missing")
    if "def cmd_heal" not in (APP_DIR / "brain.py").read_text(encoding="utf-8"):
        bad.append("mentat heal CLI missing")
    tui = (APP_DIR / "brain_tui.py").read_text(encoding="utf-8")
    if "_auto_heal" not in tui or "self-heal sweep" not in tui:
        bad.append("TUI auto-heal sweep missing")
    return (
        not bad,
        "; ".join(bad) if bad else f"quips + scan OK ({len(issues)} current signal(s))",
    )


def check_ui_and_gates():
    bad = []
    tui = (APP_DIR / "brain_tui.py").read_text(encoding="utf-8")
    core = (APP_DIR / "brain_core.py").read_text(encoding="utf-8")
    m = re.search(r"#input-bar \{(.{0,240})", tui, re.S)
    if not m or "height: auto" not in m.group(1):
        bad.append("input bar no longer auto-grows")
    if "str(answer).strip() and _has_quote_intent" in core:
        bad.append("quote verification is gated on quote-intent again")
    if core.count("_mark_ungrounded_quotes(") < 2:
        bad.append("quote verification missing from an ask path")
    for token in ('"/stats"', '"/heal"'):
        if token not in tui:
            bad.append(f"TUI command {token} missing")
    if 'get("self_heal"' not in (core + tui):
        bad.append("self_heal setting is never read")
    return (not bad), ("; ".join(bad) if bad else "UI + verification gates OK")


def check_offline_readiness():
    bad = []
    core = (APP_DIR / "brain_core.py").read_text(encoding="utf-8")
    if 'OLLAMA_NUM_CTX", "32768"' not in core:
        bad.append("offline context window is not 32k")
    if "prompt_chars // 4" not in core:
        bad.append("num_predict is not prompt-aware (empty-answer risk)")
    if "under ~150 words" in core:
        bad.append("the 150-word offline cap is back")
    if "OFFLINE_ANSWER_RULES" not in core or "(Dune \\u00b7 Chapter 2)" not in core:
        bad.append("offline few-shot citation exemplar missing")
    if "never reproduce" not in core or "made-up location" not in core:
        bad.append("poison guard (no memory quotes / no invented locations) missing")
    if 'kwargs.get("think")' not in core:
        bad.append("per-call think override missing")
    if "_offline_gen_kwargs" not in core or '"think": kind' not in core:
        bad.append("think-routing not keyed to the register classifier")
    if "local_model=OLLAMA_FAST_MODEL,\n        think=False" not in core:
        bad.append("offline librarian still thinks (slow)")
    if 'strategy in ("universal", "hunt") and not _offline()' in core:
        bad.append("offline still truncates full passage rendering")
    try:
        rules = bc._offline_answer_rules("concept")
        plain = bc._offline_answer_rules("count")
        if "(Dune \u00b7 Chapter 2)" not in rules:
            bad.append("citation exemplar not in runtime rules")
        if "outside knowledge" not in rules:
            bad.append("concept rules lost their labeling clause")
        if "outside knowledge" in plain:
            bad.append("count rules wrongly include the concept clause")
    except Exception as exc:
        bad.append(f"rules call failed: {exc}")
    if bc.resolve_model("qwen") != bc.OLLAMA_LLM_MODEL:
        bad.append("offline synth alias does not match the default model")
    if "qwen" not in bc.resolve_model("qwen-deep"):
        bad.append("offline librarian alias broken")
    return (not bad), ("; ".join(bad) if bad else "offline contract OK (32k, think-routing, few-shot)")


def check_passage_resolution():
    """Known-hard citation labels must resolve (regression guard for A6)."""
    cases = [
        ("*Dune*", "Chapter 36"),
        ("Kojeve", "Introduction to the Reading of Hegel"),
        ("Dune", "Ch. 24"),
        ("God Emperor", "Chapter 8"),
        ("Muqaddimah", "Chapter 6"),
    ]
    bad = []
    for book, loc in cases:
        try:
            r = bc._passage_source(book, loc, "")
        except Exception as exc:
            bad.append(f"{book}: {type(exc).__name__}")
            continue
        if not r or not (r.get("text") or ""):
            bad.append(f"{book} · {loc} unresolved")
    return (
        not bad,
        "; ".join(bad) if bad else f"citation aliases resolve ({len(cases)}/{len(cases)})",
    )


def check_pdf_anchors():
    import sqlite3

    bad = []
    db = sqlite3.connect(str(APP_DIR / "storage" / "library.db"))
    try:
        db.row_factory = sqlite3.Row
        sq = db.execute(
            "SELECT file_path, content FROM chunks WHERE file_path LIKE '%Study Quran%' "
            "AND content LIKE '%no god but He%' LIMIT 1"
        ).fetchone()
        sqv = db.execute(
            "SELECT file_path, content FROM chunks WHERE file_path LIKE '%Study Quran%' "
            "AND content GLOB '*[0-9]:[0-9]*' LIMIT 1"
        ).fetchone()
        kj = db.execute(
            "SELECT file_path, content FROM chunks WHERE file_path LIKE '%Kojeve%' LIMIT 1"
        ).fetchone()
        epub = db.execute(
            "SELECT file_path, content FROM chunks WHERE file_path LIKE '%.epub · Chapter %' "
            "AND file_path LIKE '%(ch%' LIMIT 1"
        ).fetchone()
    finally:
        db.close()
    checks = [
        ("surah text", sq, lambda c: "p. " in c),
        ("surah verse", sqv, lambda c: bool(re.search(r"· \d{1,3}:\d{1,3} · p\. \d+$", c))),
        ("kojeve page", kj, lambda c: "Introduction to the Reading of Hegel" in c and "p. " in c),
        ("epub chapter", epub, lambda c: bool(re.search(r"· Chapter \d+$", c))),
    ]
    for label, row, ok in checks:
        if not row:
            bad.append(f"{label}: no sample chunk")
            continue
        cite = bc._citation_for({"file_path": row["file_path"], "content": row["content"]})
        if not ok(cite):
            bad.append(f"{label}: citation {cite!r} lacks the anchor")
    return (
        not bad,
        "; ".join(bad)
        if bad
        else "PDF pages + Quran verses anchored, epub chapters intact",
    )


def check_hunt_engine():
    bad = []
    if not bc._has_hunt_intent("where does paul say the litany against fear"):
        bad.append("hunt intent missed for 'where does ... say'")
    if not bc._has_hunt_intent("find: blue within blue"):
        bad.append("hunt intent missed for '/find' marker")
    if not bc._has_hunt_intent("half-remembered quote about fear"):
        bad.append("hunt intent missed for 'half-remembered'")
    if bc._has_hunt_intent("what is dune about"):
        bad.append("hunt intent false-positive on a plain question")
    if bc._retrieval_strategy("find: litany against fear", 0.0) != "hunt":
        bad.append("strategy did not select hunt")
    tui_src = (APP_DIR / "brain_tui.py").read_text(encoding="utf-8")
    if '"/find"' not in tui_src:
        bad.append("/find not registered in the TUI")
    hits = bc._hunt_passages("find: the litany against fear", limit=12)
    if not hits:
        return False, "hunt returned no passages for the litany"
    if not any("litany" in (p.get("content") or "").lower() for p in hits):
        bad.append("hunt hits don't contain the phrase")
    miss = bc._hunt_passages("find: eys of ibad", limit=12)
    if not any(
        "eyes of the ibad" in (p.get("content") or "").lower()
        or "eyes of the ibad" in (p.get("excerpt") or "").lower()
        for p in miss
    ):
        bad.append("spelling-rescued hunt missed 'eyes of the ibad'")
    return (
        not bad,
        "; ".join(bad)
        if bad
        else f"hunt OK ({len(hits)} litany hits, {len(miss)} rescued)",
    )


# --------------------------------------------------------------------------
# Deep checks (end-to-end, retrieval — still no LLM calls)
# --------------------------------------------------------------------------


def check_census_e2e_or():
    ctx = bc._census_ctx("list me all the times allah or god is mentioned in the quran", "agent")
    block = ctx.get("block") or ""
    bad = []
    if "list" == str(ctx.get("phrase") or "").strip().lower():
        bad.append("census phrase is 'list'")
    m_allah = re.search(r"Variant .allah. — (\d+)", block)
    m_god = re.search(r"Variant .god. — (\d+)", block)
    if not m_allah:
        bad.append("no allah variant in block")
    elif int(m_allah.group(1)) < 50:
        bad.append(f"allah count {m_allah.group(1)} suspiciously low (diacritics?)")
    if not m_god:
        bad.append("no god variant in block")
    return (
        not bad,
        "; ".join(bad)
        if bad
        else f"allah={m_allah.group(1)}, god={m_god.group(1)}",
    )


def check_census_e2e_ibad():
    ctx = bc._census_ctx("list me all the times the eyes of ibad are mentioned", "agent")
    block = ctx.get("block") or ""
    bad = []
    if str(ctx.get("phrase") or "") != "eyes of ibad":
        bad.append(f"phrase {ctx.get('phrase')!r} != 'eyes of ibad'")
    if "eyes of ibad" not in block:
        bad.append("block does not mention eyes of ibad")
    if re.search(r"census for .list.", block):
        bad.append("block censused 'list'")
    return (not bad), ("; ".join(bad) if bad else "eyes of ibad census correct")


async def check_retrieval_probe():
    brain = bc.Brain()
    try:
        info = await brain.probe("find the litany against fear in the dune books")
    finally:
        await brain.close()
    passages = info.get("passages") or []
    if not passages:
        return False, f"probe returned 0 passages (strategy={info.get('strategy')})"
    if not info.get("block_chars"):
        return False, "probe rendered an empty passage block"
    return True, f"{len(passages)} passages, {info['block_chars']} block chars"


def check_no_silent_degradation():
    note = bc._retrieval_degraded_note()
    if note:
        return False, f"retrieval degraded silently: {note}"
    return True, "no swallowed retrieval failures"


# --------------------------------------------------------------------------
# Runner / reporting
# --------------------------------------------------------------------------


def build_checks(quick=False):
    checks = [
        ("census.phrase_shapes", check_census_phrase_shapes),
        ("census.or_variants", check_census_or_variants),
        ("census.diacritics", check_census_diacritics),
        ("census.junk_guard", check_census_junk_guard),
        ("data.integrity", check_data_integrity),
        ("search.spans", check_span_search),
        ("search.scope_priority", check_scope_priority),
        ("source.regressions", check_source_regressions),
        ("retrieval.silent", check_no_silent_degradation),
        ("model.config", check_model_config),
        ("models.routing", check_provider_routing),
        ("models.canary", check_models_canary),
        ("brand.rename", check_renamed_to_mentat),
        ("thinking.structures", check_thinking_structures),
        ("thinking.memory", check_memory_injection),
        ("thinking.feedback", check_feedback_ranking),
        ("search.hunt", check_hunt_engine),
        ("search.gold", check_gold_regressions),
        ("citation.attribution", check_quote_attribution),
        ("citation.references", check_reference_filtering),
        ("search.phonetic", check_phonetic_matching),
        ("enrichment.state", check_enrichment),
        ("graph.entities", check_entity_graph),
        ("router.roles", check_model_roles),
        ("ranking.budget", check_ranking_and_budget),
        ("settings.spec", check_settings_spec),
        ("cost.model", check_cost_model),
        ("register.system", check_register_system),
        ("register.retrieval", check_register_retrieval),
        ("selfheal.system", check_self_heal),
        ("ui.gates", check_ui_and_gates),
        ("offline.contract", check_offline_readiness),
        ("citations.anchors", check_pdf_anchors),
        ("citations.resolve", check_passage_resolution),
        ("voices.grammar", check_voice_presets),
        ("book.mode", check_book_mode),
    ]
    if not quick:
        checks += [
        ("census.e2e_or", check_census_e2e_or),
        ("census.e2e_ibad", check_census_e2e_ibad),
        ("census.e2e_mercy", check_census_e2e_mercy),
            ("retrieval.probe", check_retrieval_probe),
        ]
    return checks


def run_suite(quick=False, verbose=True):
    run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    results = []
    for name, fn in build_checks(quick=quick):
        t0 = time.time()
        try:
            if inspect.iscoroutinefunction(fn):
                ok, detail = asyncio.run(fn())
            else:
                ok, detail = fn()
        except Exception as exc:
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        row = _log_result(run_id, name, ok, detail, (time.time() - t0) * 1000)
        results.append(row)
        if verbose:
            mark = "PASS" if ok else "FAIL"
            print(f"[{mark}] {name:<22} {detail}")
    passed = sum(1 for r in results if r["status"] == PASS)
    failed = len(results) - passed
    try:
        bc._telemetry_log_feedback(
            "verify_run",
            f"{passed} pass / {failed} fail (run {run_id})",
        )
    except Exception:
        pass
    if verbose:
        print(f"\n{passed} passed, {failed} failed  (run {run_id})")
    return results


def print_history(limit=5):
    if not VERIFY_LOG.exists():
        print("no verification history yet — run `brain verify` first.")
        return
    runs = {}
    order = []
    for line in VERIFY_LOG.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except Exception:
            continue
        rid = row.get("run_id", "?")
        if rid not in runs:
            runs[rid] = []
            order.append(rid)
        runs[rid].append(row)
    for rid in reversed(order[-limit:]):
        rows = runs[rid]
        passed = sum(1 for r in rows if r["status"] == PASS)
        failed = [r for r in rows if r["status"] != PASS]
        when = rows[0].get("ts", "")
        head = f"{when}  run {rid}  {passed}/{len(rows)} passed"
        print(head)
        for r in failed:
            print(f"    FAIL {r['check']}: {r['detail']}")
        print()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Mentat verification suite")
    parser.add_argument("--quick", action="store_true", help="unit checks only (no retrieval)")
    parser.add_argument("--history", action="store_true", help="print recent verification history")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args(argv)
    if args.history:
        print_history(args.limit)
        return 0
    results = run_suite(quick=args.quick)
    return 0 if all(r["status"] == PASS for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
