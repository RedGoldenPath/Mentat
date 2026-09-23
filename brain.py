import argparse
import asyncio
import json
import os
import plistlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from brain_core import KNOWLEDGE_ROOT, STORAGE_DIR, Brain, _clean_markers, _load_manifest, model_label

PROJECT_ROOT = Path(__file__).resolve().parent
BACKUP_DIR = PROJECT_ROOT / "backups"
UV_BIN = "/Users/raphael/.local/bin/uv"
LAUNCHD_PLIST = Path.home() / "Library" / "LaunchAgents" / "com.mentat.autoindex.plist"
LEGACY_LAUNCHD_PLIST = Path.home() / "Library" / "LaunchAgents" / "com.secondbrain.autoindex.plist"

console = Console()

COMMANDS = {
    "index": "index new/changed files (books need explicit indexing)",
    "index-status": "show whether indexing is running and its progress",
    "ask": 'ask a question: brain ask "..." (add --no-lazy to skip auto-index)',
    "probe": 'show what a question would be grounded in: brain probe "..." (no LLM calls)',
    "console": "interactive chat session (pretty)",
    "save": "save a web page into the vault: brain save <url> [--title ...]",
    "themes": "list the main themes across the whole library",
    "status": "show what is indexed and current settings",
    "health": "run library health checks (no LLM calls)",
    "history": "show past questions and answers",
    "settings": "view settings, or set one: brain settings set <key> <value>",
    "lens": "show/clear the lens, or load one: brain lens <name>",
    "remember": 'permanently remember a fact: brain remember "fact" [--topic name]',
    "backup": "back up the index: brain backup | backup list | backup --restore <name>",
    "schedule": "auto-index on a timer: brain schedule on [--every 6] | off",
    "commands": "list all commands",
    "forget": "remove one file from the index: brain forget notes/foo.md",
    "reset": "delete the entire index (use --yes)",
    "verify": "run the verification suite (history is logged to the research diary)",
    "find": 'hunt a half-remembered quote: brain find "..." (fuzzy + exact)',
    "book": 'ask inside one whole work: brain book "Dune" "..." (Kimi K3, needs MOONSHOT_API_KEY)',
    "spans": "build/show the sentence-span index (exact quote anchors)",
    "enrich": "contextual retrieval: brain enrich [--contexts] [--llm] [--embed] [--status]",
    "graph": 'entity co-occurrence: brain graph "Fremen" (build with --build)',
    "kill": "stop a stuck Mentat instance and clear its lock",
    "models": "show model catalog: routing, keys, and verified prices",
    "heal": "self-repair: detect + fix broken subsystems (quips included)",
}


def _md(text):
    try:
        return Markdown(text)
    except Exception:
        return text


DESERT_SAND = "#E3C567"
DESERT_TAN = "#D9B96A"
DESERT_TAN_DARK = "#C2A878"
EYES_OF_IBAD = "#4A90E2"
EYES_OF_IBAD_DEEP = "#1E63C8"


def _big_banner():
    try:
        import pyfiglet

        art = pyfiglet.figlet_format("MENTAT", font="slant")
    except Exception:
        art = "MENTAT"
    line_colors = [DESERT_SAND, DESERT_TAN, DESERT_TAN_DARK, EYES_OF_IBAD, DESERT_SAND, EYES_OF_IBAD_DEEP]
    lines = art.splitlines()
    for index, line in enumerate(lines):
        if line.strip():
            console.print(f"[bold {line_colors[index % len(line_colors)]}]{line}[/]")
        else:
            console.print()
    console.print(f"[bold {EYES_OF_IBAD}]✦ your thinking partner over the knowledge vault ✦[/]")


def _chip(label, value, style):
    return f"[dim]{label}:[/dim] [{style}]{value}[/]"


def _print_answer(result):
    console.print(
        Panel(
            _md(_clean_markers(result["answer"])),
            title="answer",
            title_align="left",
            border_style="green",
        )
    )
    contexts = result.get("contexts", "").strip()
    if contexts:
        lines = contexts.splitlines()
        console.print(Panel("\n".join(lines[:80]), title="evidence", border_style="dim"))
        if len(lines) > 80:
            console.print(f"[dim]... {len(lines) - 80} more evidence lines[/dim]")


def _commands_table():
    table = Table(title="commands", box=box.ROUNDED, expand=True)
    table.add_column("command", style="cyan", no_wrap=True)
    table.add_column("what it does", style="default")
    for name, description in COMMANDS.items():
        table.add_row(name, description)
    return table


def _kv_table(title, data, rows):
    table = Table(title=title, box=box.ROUNDED, expand=True)
    table.add_column("key", style="cyan", no_wrap=True)
    table.add_column("value", style="default")
    for key in rows:
        table.add_row(key, str(data.get(key, "")))
    return table


def _index_status():
    import re as _re
    import subprocess as _sp

    procs = _sp.run(["pgrep", "-f", "brain.py index"], capture_output=True, text=True).stdout.split()
    own = {str(os.getpid()), str(os.getppid())}
    running = any(pid not in own for pid in procs)

    new_files, changed_files, removed, current = Brain()._scan_changes()
    pending = sorted([str(p.relative_to(KNOWLEDGE_ROOT)) for p in new_files + changed_files])

    log_path = PROJECT_ROOT / "index_run.log"
    indexed_this_run = []
    chunk = None
    current_file = None
    if log_path.exists():
        lines = log_path.read_text(errors="ignore").splitlines()
        indexed_this_run = [l.split("indexed: ", 1)[1] for l in lines if l.startswith("indexed:")]
        for line in reversed(lines):
            if chunk is None:
                match = _re.search(r"Chunk (\d+) of (\d+)", line)
                if match:
                    chunk = (int(match.group(1)), int(match.group(2)))
            if current_file is None:
                match = _re.search(r"Extracting stage \d+/\d+:\s*(.+)", line)
                if match:
                    current_file = match.group(1).strip()

    overall = None
    if running:
        pct_now = (chunk[0] / chunk[1]) if chunk and chunk[1] else 0.0
        position = None
        if current_file and pending:
            for index, path in enumerate(pending):
                if path.split("/")[-1] == current_file:
                    position = index
                    break
            if position is None:
                for index, path in enumerate(pending):
                    if current_file in path:
                        position = index
                        break
        if position is not None and pending:
            overall = int((position + pct_now) * 100 / len(pending))
        elif pending:
            overall = int(pct_now * 100 / len(pending))

    return {
        "running": running,
        "docs_indexed": len(_load_manifest()),
        "pending_files": len(pending),
        "pending": pending[:20],
        "chunk": chunk,
        "current_file": current_file,
        "indexed_this_run": indexed_this_run,
        "overall": overall,
    }


def _print_index_status(info):
    table = Table(title="index status", box=box.ROUNDED, expand=True)
    table.add_column("key", style="cyan", no_wrap=True)
    table.add_column("value", style="default")
    table.add_row("running", "yes" if info["running"] else "no")
    if info["running"]:
        table.add_row("current file", info["current_file"] or "—")
    if info["running"] and info["chunk"]:
        table.add_row("current", f"chunk {info['chunk'][0]}/{info['chunk'][1]}")
    if info["running"]:
        table.add_row("this run", f"{len(info['indexed_this_run'])} file(s) done")
        if info["overall"] is not None:
            table.add_row("overall (est.)", f"{info['overall']}%")
    table.add_row("files indexed (total)", str(info["docs_indexed"]))
    table.add_row("pending", str(info["pending_files"]))
    if info["pending"]:
        table.add_row("pending files", "\n".join(info["pending"][:10]))
    console.print(table)
    if not info["running"] and info["pending_files"]:
        console.print("[yellow]not running — run `brain index` to process pending files[/yellow]")
    elif not info["running"]:
        console.print("[green]index up to date[/green]")


async def cmd_index(args):
    brain = Brain()
    try:
        stats = await brain.index(verbose=True, only=args.only)
    finally:
        await brain.close()
    if stats.get("already_running"):
        console.print(f"[yellow]{stats['message']}[/yellow]")
        return
    print(json.dumps(stats, indent=2))


def cmd_kill(args):
    """Stop a stuck interactive instance and clear its lock."""
    import signal
    import time as _time

    from brain_core import _app_lock_holder_pid, _release_stale_lock

    pid = _app_lock_holder_pid()
    if pid is None:
        if _release_stale_lock():
            console.print("[green]lock cleared[/green] (no live instance was holding it)")
        else:
            console.print("no Mentat instance is running")
        return
    console.print(f"stopping Mentat instance (pid {pid})…")
    try:
        os.kill(pid, signal.SIGTERM)
    except Exception as exc:
        console.print(f"[red]could not signal pid {pid}: {exc}[/red]")
        return
    for _ in range(20):
        if _app_lock_holder_pid() is None:
            break
        _time.sleep(0.25)
    remaining = _app_lock_holder_pid()
    if remaining is not None:
        try:
            os.kill(remaining, signal.SIGKILL)
            _time.sleep(0.5)
        except Exception:
            pass
    if _release_stale_lock():
        console.print("[green]stopped; lock cleared[/green]")
    elif _app_lock_holder_pid() is None:
        console.print("[green]stopped[/green]")
    else:
        console.print(f"[red]pid {pid} is still running — stop it manually[/red]")


def cmd_models(args):
    """Show the model catalog: routing, labels, keys, and verified prices."""
    from brain_core import (
        MODEL_PRICES, MOONSHOT_API_KEY,
        resolve_model, resolve_provider,
    )

    canonical = ["qwen", "qwen-deep", "deepseek-flash", "deepseek-think", "kimi-k3"]
    table = Table(title="models", box=box.SIMPLE, title_justify="left")
    table.add_column("setting", style="cyan")
    table.add_column("resolves to")
    table.add_column("engine")
    table.add_column("key")
    table.add_column("$ in/out per 1M")
    for key in canonical:
        wire = resolve_model(key)
        provider, _base, api_key, wire_id = resolve_provider(wire)
        price = MODEL_PRICES.get(
            "kimi-k3" if provider == "moonshot"
            else ("deepseek-v4-pro" if "pro" in wire_id else "deepseek-flash")
        ) if provider else None
        engine = provider or "local ollama"
        keymark = "yes" if (api_key or not provider) else "MISSING"
        pr = f"{price['in']:.2f} / {price['out']:.2f}" if price else "free"
        table.add_row(key, wire_id, engine, keymark, pr)
    console.print(table)
    console.print(
        "[dim]legacy aliases (deepseek-chat, deepseek-v4-flash) resolve to "
        "deepseek-flash. Prefixed ids work anywhere: "
        "openrouter/deepseek/deepseek-v4.1-flash · moonshot/kimi-k3[/dim]"
    )


async def cmd_heal(args):
    """Run the self-heal scan: detect broken subsystems and repair them."""
    from brain_core import self_heal_run

    result = await self_heal_run(allow_major=bool(getattr(args, "major", False)))
    for q in result.get("quips") or []:
        console.print(f"[yellow]{q}[/yellow]")
    payload = {
        "issues": [i[0] for i in result.get("issues") or []],
        "fixed": result.get("fixed") or [],
        "pending": result.get("pending") or [],
        "failed": result.get("failed") or [],
        "notes": result.get("notes") or [],
    }
    console.print_json(json.dumps(payload, ensure_ascii=False))
    if result.get("pending"):
        console.print(
            "[dim]major repairs need approval: re-run as `mentat heal --major`[/dim]"
        )


def cmd_graph(args):
    from brain_core import _build_graph, _graph_db, _graph_related

    if args.build:
        console.print("[dim]building the entity graph from the chunk store…[/dim]")

        def _prog(done):
            console.print(f"  {done:,} chunks")

        info = _build_graph(progress=_prog)
        console.print(
            f"graph: {info['entities']:,} entities, {info['edges']:,} edges "
            f"over {info['chunks']:,} chunks"
        )
        return
    if not args.entity:
        db = _graph_db()
        try:
            e = db.execute("SELECT count(*) FROM entities").fetchone()[0]
            ed = db.execute("SELECT count(*) FROM edges").fetchone()[0]
        except Exception:
            e = ed = 0
        console.print(f"graph: {e:,} entities, {ed:,} edges (build with --build)")
        return
    info = _graph_related(args.entity)
    if not info["count"]:
        console.print(f"[yellow]'{info['entity']}' is not in the graph — try another name or --build[/yellow]")
        return
    console.print(f"[b]{info['entity']}[/b] — {info['count']} chunks")
    for name, cnt in info["related"]:
        console.print(f"  ~ {name} ({cnt})")
    for book, cnt in info["books"]:
        console.print(f"  · {book} ({cnt})")


async def cmd_enrich(args):
    from brain_core import (
        ENRICH_CONTEXTS_PATH,
        _build_contexts,
        _build_enriched_vec,
        _load_contexts,
        _llm_contexts,
    )

    if args.status:
        contexts = _load_contexts()
        llm_n = sum(1 for v in contexts.values() if v.startswith("[llm]"))
        console.print(
            f"contexts: {len(contexts):,} "
            f"({llm_n:,} llm / {len(contexts) - llm_n:,} deterministic)"
        )
        console.print(f"file: {ENRICH_CONTEXTS_PATH}")
        return
    did = False
    if args.contexts:
        n = _build_contexts(force=args.force)
        console.print(f"deterministic contexts added: {n:,}")
        did = True
    if args.llm:
        def _prog(done, ttl):
            if done == 1 or done % 200 == 0:
                console.print(f"  llm contexts {done:,}/{ttl:,}")

        n = await _llm_contexts(limit=args.limit, progress=_prog)
        console.print(f"llm contexts upgraded: {n:,}")
        did = True
    if args.embed:
        console.print(
            "[dim]rebuilding embedding index with contexts (atomic swap)…[/dim]"
        )

        def _eprog(done, ttl):
            if done % 1000 == 0:
                console.print(f"  embedded {done:,}/{ttl:,}")

        res = await _build_enriched_vec(progress=_eprog)
        console.print(json.dumps(res, indent=2))
        did = True
    if not did:
        n = _build_contexts(force=args.force)
        console.print(
            f"deterministic contexts added: {n:,} "
            "(use --llm and --embed to finish enrichment)"
        )


async def cmd_book(args):
    brain = Brain()
    try:
        result = await brain.book_ask(args.work, args.question)
        if result.get("status") == "answered":
            console.print(
                f"[dim]whole-book context: {result['work']} "
                f"({result['chars']:,} chars"
                f"{', truncated' if result.get('truncated') else ''})[/dim]"
            )
            _print_answer(
                {"status": "answered", "answer": result["answer"], "contexts": ""}
            )
        else:
            console.print(f"[yellow]{result.get('message')}[/yellow]")
    finally:
        await brain.close()


async def cmd_ask(args):
    brain = Brain()
    try:
        if getattr(args, "trace", False):
            acc = ""
            async for text in brain.ask_stream(args.question):
                acc = text
            res = brain._last_stream_result or {}
            answer = res.get("answer") or acc or "…(no answer)"
            _print_answer({"status": "answered", "answer": answer, "contexts": ""})
            console.print("[dim]trace (per phase):[/dim]")
            prev = 0.0
            for name, t in getattr(brain, "_trace", []):
                console.print(f"  [dim]{name:>16}[/]  +{t - prev:>6.2f}s   (t={t:.1f}s)")
                prev = t
            return
        result = await brain.ask(args.question, lazy=not args.no_lazy)
        if result.get("status") == "indexing_running":
            console.print(f"[yellow]{result['message']}[/yellow]")
        elif result.get("status") == "needs_index":
            console.print(f"[yellow]{result['message']}[/yellow]")
            if sys.stdin.isatty():
                try:
                    answer = input("Index now? [y/N] ").strip().lower()
                except EOFError:
                    answer = ""
                if answer in ("y", "yes"):
                    stats = await brain.index(verbose=True)
                    if stats.get("already_running"):
                        console.print(f"[yellow]{stats['message']}[/yellow]")
                    else:
                        print(json.dumps(stats, indent=2))
                        result = await brain.ask(args.question, lazy=False)
        if result.get("status") == "answered":
            _print_answer(result)
    finally:
        await brain.close()


async def cmd_status(args):
    brain = Brain()
    try:
        info = await brain.status()
    finally:
        await brain.close()
    print(json.dumps(info, indent=2))


async def cmd_health(args):
    """Run library health checks (no LLM calls)."""
    brain = Brain()
    try:
        results = await brain.health()
    finally:
        await brain.close()
    table = Table(title="health", box=box.SIMPLE)
    table.add_column("check", style="dim")
    table.add_column("status")
    table.add_column("detail", style="dim")
    failed = 0
    for name, ok, detail in results:
        table.add_row(name, "[green]ok[/]" if ok else "[red]FAIL[/]", str(detail))
        if not ok:
            failed += 1
    console.print(table)
    console.print(
        f"[green]{len(results) - failed} ok[/] · "
        f"[red]{failed} failed[/]" if failed else f"[green]all {len(results)} checks ok[/]"
    )


async def cmd_probe(args):
    """Show what a question would be grounded in — no LLM calls, no cost."""
    brain = Brain()
    try:
        info = await brain.probe(args.question)
    finally:
        await brain.close()
    table = Table(title="probe", box=box.SIMPLE)
    table.add_column("key", style="dim")
    table.add_column("value")
    table.add_row("question", info["question"])
    table.add_row(
        "strategy",
        f"{info['strategy']}  (score {info['score']}, "
        f"universal={info['universal']}, quotes={info['quote_intent']})",
    )
    table.add_row("named sources", ", ".join(info["named_sources"]) or "—")
    table.add_row("search terms", ", ".join(info["terms"]) or "—")
    table.add_row("answer model", info["route_model"])
    table.add_row("elapsed", f"{info['elapsed_s']}s (no LLM calls)")
    console.print(table)
    for i, p in enumerate(info["passages"], 1):
        tag = "[orange1]named[/]" if p["named"] else "semantic"
        console.print(f"[dim]{i:>2}.[/] [{tag}] {p['file_path']}")
        console.print(f"      [dim]{p['excerpt'][:180]}[/]")
    console.print(f"[dim]block chars: {info['block_chars']}[/]")


async def cmd_index_status(args):
    _print_index_status(_index_status())


async def cmd_history(args):
    brain = Brain()
    entries = brain.history(limit=args.limit)
    if not entries:
        print("No conversation history yet.")
        return
    for index, entry in enumerate(entries, start=1):
        print(f"--- {index} [{entry['timestamp']}] ---")
        print(f"Q: {entry['question']}")
        answer = entry["answer"]
        print(f"A: {answer[:2000]}")
        if len(answer) > 2000:
            print(f"... (answer truncated, {len(answer)} chars total)")
        print()


def cmd_audit(args):
    """Report card over every subsystem: storage, index, telemetry, convos."""
    from brain_core import _audit

    try:
        r = _audit()
    except Exception as exc:
        console.print(f"[red]audit failed: {exc}[/red]")
        return
    table = Table(title="brain audit", title_justify="left")
    table.add_column("system")
    table.add_column("state")
    total_mb = sum(r["files"].values()) / 1e6
    table.add_row(
        "storage",
        f"{len(r['files'])} files, {total_mb:.0f} MB"
        + (f" · legacy JSON stores: {', '.join(r['legacy_json_stores'])}" if r["legacy_json_stores"] else ""),
    )
    status = "OK" if r["index_consistent"] else "MISMATCH"
    style = "green" if r["index_consistent"] else "red"
    table.add_row(
        "index consistency",
        f"[{style}]{status}[/{style}] · chunks {r['chunks']} · fts {r['fts_rows']} · vec {r['vec_rows']}",
    )
    table.add_row(
        "library",
        f"{r['manifest_books']} books indexed · {r['pending_files']} pending · {r['removed_files']} stale",
    )
    table.add_row(
        "conversations",
        f"{r['conversations']} saved · {r['broken_convs']} broken"
        + (" [red]FIX[/red]" if r["broken_convs"] else ""),
    )
    t = r.get("telemetry") or {}
    if t:
        table.add_row(
            "research diary",
            f"{t.get('asks', 0)} asks · {t.get('retries', 0)} retries · "
            f"{t.get('no_answer', 0)} no-answer · {t.get('citation_precision_pct', 0)}% citation precision",
        )
    integ = r.get("integrity") or {}
    if integ:
        fresh = integ.get("store_fresh", True)
        table.add_row(
            "integrity gates",
            f"[{'green' if fresh else 'red'}]{'OK' if fresh else 'STALE — restart required'}[/{'green' if fresh else 'red'}]"
            f" · store v{integ.get('store_version', '?')} / code v{integ.get('code_version', '?')}"
            f" · shelf leaks: {integ.get('shelf_leaks', '?')}",
        )
    console.print(table)


def cmd_stats(args):
    """The research diary: asks, retrieval usage, and feedback summaries."""
    from brain_core import _telemetry_conn, _telemetry_init

    _telemetry_init()
    try:
        conn = _telemetry_conn()
    except Exception as exc:
        console.print(f"[yellow]telemetry unavailable: {exc}[/yellow]")
        return
    try:
        n_asks = conn.execute("SELECT count(*) FROM asks").fetchone()[0]
        if not n_asks:
            console.print("[dim]no research diary yet — ask a few questions first.[/dim]")
            return
        n_ret = conn.execute("SELECT count(*) FROM retrieval").fetchone()[0]
        n_cited = conn.execute("SELECT count(*) FROM retrieval WHERE cited=1").fetchone()[0]
        by_day = conn.execute(
            "SELECT substr(ts,1,10) d, count(*) FROM asks GROUP BY d ORDER BY d DESC LIMIT 7"
        ).fetchall()
        statuses = conn.execute(
            "SELECT status, count(*) FROM asks GROUP BY status"
        ).fetchall()
        retries = conn.execute(
            "SELECT count(*) FROM asks WHERE fast_retry=1"
        ).fetchone()[0]
        lat = conn.execute(
            "SELECT round(avg(t_passages),2), round(avg(t_answer),2) FROM asks WHERE t_passages IS NOT NULL"
        ).fetchone()
        top_books = conn.execute(
            """SELECT book, count(*) c, sum(cited) cited FROM retrieval
               GROUP BY book ORDER BY cited DESC, c DESC LIMIT 8"""
        ).fetchall()
        feedback = conn.execute(
            "SELECT kind, count(*) FROM feedback GROUP BY kind"
        ).fetchall()
        try:
            day = time.strftime("%Y-%m-%d")
            today_cost = conn.execute(
                "SELECT coalesce(round(sum(cost_usd), 4), 0) FROM asks "
                "WHERE substr(ts, 1, 10) = ?",
                (day,),
            ).fetchone()[0]
            total_cost = conn.execute(
                "SELECT coalesce(round(sum(cost_usd), 4), 0) FROM asks"
            ).fetchone()[0]
            tokens = conn.execute(
                "SELECT coalesce(sum(tokens_in),0), coalesce(sum(tokens_out),0) FROM asks"
            ).fetchone()
        except Exception:
            today_cost, total_cost, tokens = 0, 0, (0, 0)

        table = Table(title="research diary", title_justify="left")
        table.add_column("metric")
        table.add_column("value")
        table.add_row("questions logged", str(n_asks))
        table.add_row("passages retrieved", str(n_ret))
        table.add_row(
            "passages actually cited",
            f"{n_cited} ({round(100 * n_cited / max(1, n_ret))}% precision)",
        )
        table.add_row("fast-model retries", str(retries))
        table.add_row(
            "spend (USD)",
            f"today ${today_cost:.4f} · all-time ${total_cost:.4f} "
            f"({tokens[0]:,} in / {tokens[1]:,} out tokens)",
        )
        table.add_row("statuses", ", ".join(f"{s}:{c}" for s, c in statuses))
        table.add_row("avg retrieval / answer (s)", f"{lat[0]} / {lat[1]}")
        table.add_row("by day", "; ".join(f"{d}:{c}" for d, c in by_day))
        table.add_row(
            "top books (cited/total)",
            "; ".join(f"{book}: {cited}/{c}" for book, c, cited in top_books),
        )
        table.add_row(
            "your actions",
            ", ".join(f"{k}:{c}" for k, c in feedback) or "none yet",
        )
        console.print(table)
    finally:
        conn.close()


async def cmd_settings(args):
    brain = Brain()
    if args.action == "set":
        result = brain.set_setting(args.key, args.value)
        print(json.dumps(result, indent=2))
        return
    from brain_core import SETTINGS_SPEC

    settings = brain.get_settings()
    table = Table(title="settings · debug menu", box=box.SIMPLE, title_justify="left")
    table.add_column("key", style="cyan")
    table.add_column("value")
    table.add_column("what it does", style="dim")
    section = None
    for spec in SETTINGS_SPEC:
        if spec["section"] != section:
            section = spec["section"]
            table.add_row(f"[b]{section}[/b]", "", "")
        value = settings.get(spec["key"], "")
        if isinstance(value, bool):
            value = "on" if value else "off"
        table.add_row(spec["key"], str(value), spec["help"])
    console.print(table)
    console.print("[dim]change one: mentat settings set <key> <value>[/dim]")


async def cmd_lens(args):
    brain = Brain()
    if args.clear:
        result = brain.set_setting("lens", "")
        print(json.dumps(result, indent=2))
        return
    if args.name:
        result = brain.lens_from_file(args.name)
        print(json.dumps(result, indent=2))
        return
    settings = brain.get_settings()
    lens = settings.get("lens") or ""
    if lens:
        console.print(Panel(_md(lens), title="lens", border_style="yellow"))
    else:
        console.print("[dim]no active lens[/dim]")


async def cmd_remember(args):
    brain = Brain()
    try:
        result = await brain.remember(args.text, topic=args.topic)
    finally:
        await brain.close()
    print(json.dumps(result, indent=2))


async def cmd_save(args):
    brain = Brain()
    try:
        result = await brain.save_url(args.url, title=args.title)
    finally:
        await brain.close()
    print(json.dumps(result, indent=2, ensure_ascii=False))


async def cmd_themes(args):
    brain = Brain()
    try:
        answer = await brain.themes()
    finally:
        await brain.close()
    console.print(Panel(_md(answer), title="themes across the library", border_style="magenta"))


def _do_backup(keep=5):
    if not STORAGE_DIR.exists():
        return {"ok": False, "reason": "no index to back up (run index first)"}
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = BACKUP_DIR / stamp
    shutil.copytree(STORAGE_DIR, dest)
    backups = sorted(BACKUP_DIR.glob("*"))
    removed = []
    for old in backups[:-keep]:
        shutil.rmtree(old)
        removed.append(old.name)
    return {"ok": True, "backup": str(dest), "removed_old": removed}


def _list_backups():
    if not BACKUP_DIR.exists():
        return []
    return [{"name": p.name, "size": sum(f.stat().st_size for f in p.rglob("*") if f.is_file())}
            for p in sorted(BACKUP_DIR.glob("*"))]


def _restore_backup(name):
    src = BACKUP_DIR / name
    if not src.exists() or not src.is_dir():
        return {"ok": False, "reason": f"no backup named '{name}'"}
    if STORAGE_DIR.exists():
        shutil.rmtree(STORAGE_DIR)
    shutil.copytree(src, STORAGE_DIR)
    return {"ok": True, "restored": name}


async def cmd_backup(args):
    if args.list:
        print(json.dumps(_list_backups(), indent=2))
        return
    if args.restore:
        print(json.dumps(_restore_backup(args.restore), indent=2))
        return
    print(json.dumps(_do_backup(), indent=2))


def cmd_spans(args):
    from brain_core import _build_spans, _library_db

    db = _library_db()
    if args.build:
        console.print("[dim]building spans from the chunk store…[/dim]")
        n = _build_spans()
        console.print(f"spans built: [b]{n:,}[/b]")
    row = db.execute(
        "SELECT count(*), count(DISTINCT chunk_id) FROM spans"
    ).fetchone()
    chunks = db.execute("SELECT count(*) FROM chunks").fetchone()[0]
    console.print(
        f"spans: {row[0]:,} across {row[1]:,}/{chunks:,} chunks "
        f"({(100 * row[1] / max(1, chunks)):.0f}% coverage)"
    )


def _schedule_status():
    listing = subprocess.run(
        ["launchctl", "list"], capture_output=True, text=True
    ).stdout
    loaded = "com.mentat.autoindex" in listing or "com.secondbrain.autoindex" in listing
    plist = None
    if LAUNCHD_PLIST.exists():
        try:
            with open(LAUNCHD_PLIST, "rb") as handle:
                plist = plistlib.load(handle)
        except Exception:
            plist = None
    interval = plist.get("StartInterval", 0) if plist else 0
    return {
        "configured": LAUNCHD_PLIST.exists(),
        "loaded": loaded,
        "every_hours": round(interval / 3600, 1) if interval else None,
    }


def _schedule_on(hours):
    interval = max(1, int(hours)) * 3600
    command = (
        f"cd {PROJECT_ROOT} && {UV_BIN} run python brain.py index "
        f">> {PROJECT_ROOT}/autoindex.log 2>&1"
    )
    plist = {
        "Label": "com.mentat.autoindex",
        "ProgramArguments": ["/bin/zsh", "-lc", command],
        "StartInterval": interval,
        "RunAtLoad": False,
        "StandardOutPath": str(PROJECT_ROOT / "autoindex.log"),
        "StandardErrorPath": str(PROJECT_ROOT / "autoindex.log"),
    }
    LAUNCHD_PLIST.parent.mkdir(parents=True, exist_ok=True)
    with open(LAUNCHD_PLIST, "wb") as handle:
        plistlib.dump(plist, handle)
    subprocess.run(["launchctl", "unload", str(LAUNCHD_PLIST)], capture_output=True)
    subprocess.run(["launchctl", "load", str(LAUNCHD_PLIST)], capture_output=True)
    return {"ok": True, "every_hours": int(hours)}


def _schedule_off():
    subprocess.run(["launchctl", "unload", str(LAUNCHD_PLIST)], capture_output=True)
    if LAUNCHD_PLIST.exists():
        LAUNCHD_PLIST.unlink()
    # clean up a pre-rename agent if it is still installed
    if LEGACY_LAUNCHD_PLIST.exists():
        subprocess.run(
            ["launchctl", "unload", str(LEGACY_LAUNCHD_PLIST)], capture_output=True
        )
        try:
            LEGACY_LAUNCHD_PLIST.unlink()
        except Exception:
            pass
    return {"ok": True}


async def cmd_schedule(args):
    if args.action == "on":
        print(json.dumps(_schedule_on(args.every), indent=2))
    elif args.action == "off":
        print(json.dumps(_schedule_off(), indent=2))
    else:
        print(json.dumps(_schedule_status(), indent=2))


async def cmd_commands(args):
    console.print(_commands_table())


async def cmd_forget(args):
    brain = Brain()
    try:
        result = await brain.forget(args.path)
    finally:
        await brain.close()
    print(json.dumps(result, indent=2))


async def cmd_reset(args):
    if not args.yes:
        print("This permanently deletes the entire index and history. Re-run with --yes to confirm.")
        return
    if STORAGE_DIR.exists():
        shutil.rmtree(STORAGE_DIR)
    print("Index reset. Run 'index' to rebuild.")


async def cmd_console(args):
    brain = Brain()
    show_evidence = False
    settings = brain.get_settings()
    lens = (settings.get("lens") or "").strip()
    _big_banner()
    idx = _index_status()
    if idx["running"]:
        if idx["overall"] is not None:
            index_chip = _chip("index", f"running {idx['overall']}%", "yellow")
        else:
            index_chip = _chip("index", "running", "yellow")
    elif idx["pending_files"]:
        index_chip = _chip("index", f"idle · {idx['pending_files']} pending", "yellow")
    else:
        index_chip = _chip("index", "up to date", "green")
    chips = "   ".join(
        [
            _chip("lens", "active" if lens else "none", "yellow" if lens else "dim"),
            _chip("thinking", settings["thinking"], "bright_blue"),
            _chip("model", model_label(settings.get("model") or ""), "magenta" if settings.get("model") not in (None, "", "qwen") else "bright_cyan"),
            _chip("docs", idx["docs_indexed"], "green"),
            index_chip,
        ]
    )
    console.print(f"[bold]{chips}[/]")
    console.print("[dim]type [cyan]help[/cyan] for commands · [cyan]index-status[/cyan] shows index progress · [cyan]model <name>[/cyan] switches the query model · just ask.[/dim]")
    try:
        while True:
            try:
                question = console.input("[cyan]> [/cyan]").strip()
            except (EOFError, KeyboardInterrupt):
                console.print()
                break
            if not question:
                continue
            lowered = question.lower()
            if lowered in ("quit", "exit", "q"):
                break
            if lowered in ("help", "commands", "?"):
                console.print(_commands_table())
                continue
            if lowered == "evidence":
                show_evidence = not show_evidence
                console.print(f"[dim]evidence {'on' if show_evidence else 'off'}[/dim]")
                continue
            if lowered in ("index-status", "index status"):
                _print_index_status(_index_status())
                continue
            if lowered == "index":
                stats = await brain.index(verbose=False)
                if stats.get("already_running"):
                    console.print(f"[yellow]{stats['message']}[/yellow]")
                else:
                    console.print(f"[green]{stats}[/green]")
                continue
            if lowered == "status":
                info = await brain.status()
                info.pop("files", None)
                console.print(
                    _kv_table(
                        "status",
                        info,
                        ["documents", "entities", "relationships", "chunks", "pending_files",
                         "extract_model", "query_model", "embed_model", "thinking",
                         "history_turns", "temperature", "lens_active"],
                    )
                )
                continue
            if lowered == "settings":
                console.print(
                    _kv_table(
                        "settings",
                        brain.get_settings(),
                        ["thinking", "history_turns", "model", "temperature", "top_k", "chunk_top_k", "sweep_depth", "lens"],
                    )
                )
                continue
            if lowered == "model":
                current = model_label(brain.get_settings().get("model") or "")
                console.print(f"[dim]query model: [cyan]{current}[/cyan][/dim]")
                console.print("[dim]options: [cyan]deepseek-flash[/cyan] (default · falls back to qwen offline) · [cyan]deepseek-think[/cyan] · [cyan]qwen[/cyan] (offline) · or any model name[/dim]")
                console.print("[dim]switch with: [cyan]model deepseek-think[/cyan][/dim]")
                continue
            if lowered.startswith("model "):
                name = question[len("model "):].strip()
                result = brain.set_setting("model", name)
                console.print(f"[green]{result}[/green]")
                continue
            if lowered == "lens":
                active = (brain.get_settings().get("lens") or "")
                if active:
                    console.print(Panel(_md(active), title="lens", border_style="yellow"))
                else:
                    console.print("[dim]no active lens[/dim]")
                continue
            if lowered == "themes":
                console.print("[dim]computing themes...[/dim]")
                answer = await brain.themes()
                console.print(Panel(_md(answer), title="themes across the library", border_style="magenta"))
                continue
            if lowered.startswith("remember "):
                result = await brain.remember(question[len("remember "):].strip())
                console.print(f"[green]{result}[/green]")
                continue
            if lowered.startswith("save "):
                console.print("[dim]fetching page...[/dim]")
                result = await brain.save_url(question[len("save "):].strip())
                console.print(f"[green]{result}[/green]")
                continue
            if lowered == "backup":
                await brain.close()
                console.print(f"[green]{_do_backup()}[/green]")
                brain = Brain()
                continue
            console.print(f"[cyan]you:[/cyan] {question}")
            console.print("[dim]thinking...[/dim]", end="")
            result = await brain.ask(question, lazy=not args.no_lazy)
            if result.get("status") == "indexing_running":
                console.print()
                console.print(f"[yellow]{result['message']}[/yellow]")
            elif result.get("status") == "needs_index":
                console.print()
                console.print(f"[yellow]{result['message']}[/yellow]")
                proceed = console.input("[cyan]Index now? [y/N] [/cyan]").strip().lower()
                if proceed in ("y", "yes"):
                    stats = await brain.index(verbose=False)
                    if stats.get("already_running"):
                        console.print(f"[yellow]{stats['message']}[/yellow]")
                    else:
                        console.print(f"[green]{stats}[/green]")
                        result = await brain.ask(question, lazy=False)
            if result.get("status") == "answered":
                console.print()
                console.print(
                    Panel(
                        _md(result["answer"]),
                        title=f"answer · {result['timestamp']}",
                        title_align="left",
                        border_style="green",
                    )
                )
                if show_evidence and result.get("contexts"):
                    lines = result["contexts"].splitlines()
                    console.print(Panel("\n".join(lines[:80]), title="evidence", border_style="dim"))
    finally:
        await brain.close()


def cmd_inventory(args):
    """What did I put in my index? Per-work stats + totals."""
    from brain_core import _library_profiles

    data = _library_profiles()
    if not data.get("works"):
        console.print("[dim]nothing indexed yet — run `brain index`.[/dim]")
        return
    table = Table(title="library inventory", box=box.SIMPLE)
    table.add_column("work")
    table.add_column("copies", justify="right")
    table.add_column("chunks", justify="right")
    table.add_column("chapters", justify="right")
    table.add_column("apparatus", justify="right")
    table.add_column("words", justify="right")
    for w in data["works"]:
        table.add_row(
            w["work"][:70],
            str(w["copies"]),
            f"{w['chunks']:,}",
            f"{w['chapters']:,}",
            f"{w['apparatus']:,}",
            f"{w['words']:,}",
        )
    t = data.get("totals") or {}
    console.print(table)
    console.print(
        f"[bold]totals:[/] {t.get('works') or len(data['works'])} works · "
        f"{t.get('chunks', 0):,} chunks · "
        f"{t.get('chapters', 0):,} story chapters · "
        f"{t.get('apparatus', 0):,} front/back-matter sections · "
        f"{t.get('words', 0):,} words"
    )


def cmd_freq(args):
    """Exact occurrence count of a word/phrase per book (story vs apparatus)."""
    from brain_core import _term_frequency

    term = args.term
    rows = _term_frequency(term)
    if not rows:
        console.print("[dim]no matches.[/dim]")
        return
    table = Table(title=f"frequency: {term}", box=box.SIMPLE)
    table.add_column("work")
    table.add_column("story", justify="right")
    table.add_column("front/back matter", justify="right")
    total = 0
    for r in rows:
        if not r["story"] and not r["apparatus"]:
            continue
        table.add_row(r["work"][:70], f"{r['story']:,}", f"{r['apparatus']:,}")
        total += r["story"]
    console.print(table)
    console.print(f"[bold]{total:,}[/] occurrences in story text")


def main():
    parser = argparse.ArgumentParser(prog="mentat", description="Mentat — library search, census, and reasoning (alias: brain)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    index_parser = subparsers.add_parser("index", help="index new/changed files in the knowledge folder")
    index_parser.add_argument("--only", default=None, help="only index files under this relative path (e.g. 'notes')")

    ask = subparsers.add_parser("ask", help="ask a question with graph-based reasoning")
    ask.add_argument("question", nargs="+")
    ask.add_argument("--no-lazy", action="store_true", help="never auto-index before answering")
    ask.add_argument("--trace", action="store_true", help="print per-phase timing after the answer")

    probe = subparsers.add_parser("probe", help="show what a question would be grounded in (no LLM calls)")
    probe.add_argument("question", nargs="+")

    find = subparsers.add_parser("find", help="hunt a half-remembered quote across all books")
    find.add_argument("question", nargs="+")
    find.add_argument("--no-lazy", action="store_true", help="never auto-index before answering")
    find.add_argument("--trace", action="store_true", help="print per-phase timing after the answer")

    book = subparsers.add_parser("book", help="ask inside one whole work (Kimi K3, 1M context)")
    book.add_argument("work", help="book title or distinctive words")
    book.add_argument("question", nargs="+")

    spans = subparsers.add_parser("spans", help="build/show the sentence-span index")
    spans.add_argument("--build", action="store_true", help="rebuild spans from the chunk store")

    subparsers.add_parser("kill", help="stop a stuck Mentat instance and clear its lock")
    subparsers.add_parser("models", help="show model catalog: routing, keys, prices")

    heal = subparsers.add_parser("heal", help="self-repair: detect + fix broken subsystems")
    heal.add_argument("--major", action="store_true", help="also allow major repairs (full re-embed)")

    enrich = subparsers.add_parser(
        "enrich", help="contextual-retrieval enrichment (contexts + embeddings)"
    )
    enrich.add_argument("--contexts", action="store_true", help="build deterministic context lines")
    enrich.add_argument("--llm", action="store_true", help="upgrade contexts with the fast model (resumable)")
    enrich.add_argument("--embed", action="store_true", help="rebuild embeddings with contexts (atomic swap)")
    enrich.add_argument("--status", action="store_true", help="show enrichment status")
    enrich.add_argument("--force", action="store_true", help="rebuild deterministic contexts from scratch")
    enrich.add_argument("--limit", type=int, default=None, help="max chunks for --llm")

    graph = subparsers.add_parser("graph", help="entity co-occurrence graph")
    graph.add_argument("entity", nargs="?", default=None, help="show what co-occurs with this name")
    graph.add_argument("--build", action="store_true", help="rebuild from the chunk store")
    subparsers.add_parser("status", help="show what is indexed")

    subparsers.add_parser("health", help="run library health checks")

    subparsers.add_parser("index-status", help="show whether indexing is running and its progress")

    history = subparsers.add_parser("history", help="show past conversations")
    history.add_argument("--limit", type=int, default=10)

    settings = subparsers.add_parser("settings", help="view or change settings")
    settings.add_argument("action", nargs="?", choices=["set"], default=None)
    settings.add_argument("key", nargs="?")
    settings.add_argument("value", nargs="?")

    lens = subparsers.add_parser("lens", help="show, set, or clear the active lens")
    lens.add_argument("name", nargs="?", default=None)
    lens.add_argument("--clear", action="store_true")

    remember = subparsers.add_parser("remember", help="permanently remember a fact")
    remember.add_argument("text", nargs="+")
    remember.add_argument("--topic", default="default")

    save = subparsers.add_parser("save", help="save a web page into the vault")
    save.add_argument("url")
    save.add_argument("--title", default=None)

    subparsers.add_parser("themes", help="list the main themes across the library")

    backup = subparsers.add_parser("backup", help="back up the index")
    backup.add_argument("--list", action="store_true", help="list existing backups")
    backup.add_argument("--restore", metavar="NAME", default=None, help="restore a backup by name")

    schedule = subparsers.add_parser("schedule", help="auto-index on a timer")
    schedule.add_argument("action", nargs="?", choices=["on", "off"], default=None)
    schedule.add_argument("--every", type=int, default=6, help="hours between runs (default 6)")

    subparsers.add_parser("commands", help="list all commands")

    forget = subparsers.add_parser("forget", help="remove one file from the index")
    forget.add_argument("path")

    reset = subparsers.add_parser("reset", help="delete the entire index")
    reset.add_argument("--yes", action="store_true")

    console = subparsers.add_parser("console", help="interactive console")
    console.add_argument("--no-lazy", action="store_true")

    subparsers.add_parser("stats", help="show the research diary (telemetry) summaries")

    verify = subparsers.add_parser("verify", help="run the verification suite")
    verify.add_argument("--history", action="store_true", help="print recent verification history")
    verify.add_argument("--quick", action="store_true", help="unit checks only (no retrieval)")
    verify.add_argument("--limit", type=int, default=5)

    inventory = subparsers.add_parser("inventory", help="show what is in the index (per-book stats)")
    inventory.add_argument("--refresh", action="store_true", help="rebuild the profile cache")

    freq = subparsers.add_parser("freq", help="occurrence count of a word/phrase per book")
    freq.add_argument("term")

    subparsers.add_parser("audit", help="report card over every subsystem")

    args = parser.parse_args()
    command = args.command
    if command == "index":
        asyncio.run(cmd_index(args))
    elif command == "ask":
        args.question = " ".join(args.question)
        asyncio.run(cmd_ask(args))
    elif command == "probe":
        args.question = " ".join(args.question)
        asyncio.run(cmd_probe(args))
    elif command == "find":
        args.question = "find: " + " ".join(args.question)
        asyncio.run(cmd_ask(args))
    elif command == "book":
        args.question = " ".join(args.question)
        asyncio.run(cmd_book(args))
    elif command == "spans":
        cmd_spans(args)
    elif command == "kill":
        cmd_kill(args)
    elif command == "models":
        cmd_models(args)
    elif command == "heal":
        asyncio.run(cmd_heal(args))
    elif command == "enrich":
        asyncio.run(cmd_enrich(args))
    elif command == "graph":
        cmd_graph(args)
    elif command == "status":
        asyncio.run(cmd_status(args))
    elif command == "health":
        asyncio.run(cmd_health(args))
    elif command == "index-status":
        asyncio.run(cmd_index_status(args))
    elif command == "history":
        asyncio.run(cmd_history(args))
    elif command == "settings":
        asyncio.run(cmd_settings(args))
    elif command == "lens":
        asyncio.run(cmd_lens(args))
    elif command == "remember":
        args.text = " ".join(args.text)
        asyncio.run(cmd_remember(args))
    elif command == "save":
        asyncio.run(cmd_save(args))
    elif command == "themes":
        asyncio.run(cmd_themes(args))
    elif command == "backup":
        asyncio.run(cmd_backup(args))
    elif command == "schedule":
        asyncio.run(cmd_schedule(args))
    elif command == "commands":
        asyncio.run(cmd_commands(args))
    elif command == "forget":
        asyncio.run(cmd_forget(args))
    elif command == "reset":
        asyncio.run(cmd_reset(args))
    elif command == "console":
        asyncio.run(cmd_console(args))
    elif command == "stats":
        cmd_stats(args)
    elif command == "verify":
        from verify import main as verify_main

        argv = []
        if args.history:
            argv += ["--history", "--limit", str(args.limit)]
        if args.quick:
            argv.append("--quick")
        raise SystemExit(verify_main(argv))
    elif command == "inventory":
        if args.refresh:
            from brain_core import _library_profiles

            _library_profiles(refresh=True)
        cmd_inventory(args)
    elif command == "freq":
        cmd_freq(args)
    elif command == "audit":
        cmd_audit(args)


if __name__ == "__main__":
    main()
