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

from brain_core import KNOWLEDGE_ROOT, STORAGE_DIR, Brain, SETTINGS_DEFAULTS, _load_manifest, model_label

PROJECT_ROOT = Path(__file__).resolve().parent
BACKUP_DIR = PROJECT_ROOT / "backups"
UV_BIN = "/Users/raphael/.local/bin/uv"
LAUNCHD_PLIST = Path.home() / "Library" / "LaunchAgents" / "com.secondbrain.autoindex.plist"

console = Console()

COMMANDS = {
    "index": "index new/changed files (books need explicit indexing)",
    "index-status": "show whether indexing is running and its progress",
    "ask": 'ask a question: brain ask "..." (add --no-lazy to skip auto-index)',
    "console": "interactive chat session (pretty)",
    "save": "save a web page into the vault: brain save <url> [--title ...]",
    "themes": "list the main themes across the whole library",
    "status": "show what is indexed and current settings",
    "history": "show past questions and answers",
    "settings": "view settings, or set one: brain settings set <key> <value>",
    "lens": "show/clear the lens, or load one: brain lens <name>",
    "remember": 'permanently remember a fact: brain remember "fact" [--topic name]',
    "backup": "back up the index: brain backup | backup list | backup --restore <name>",
    "schedule": "auto-index on a timer: brain schedule on [--every 6] | off",
    "commands": "list all commands",
    "forget": "remove one file from the index: brain forget notes/foo.md",
    "reset": "delete the entire index (use --yes)",
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

        art = pyfiglet.figlet_format("SECOND BRAIN", font="slant")
    except Exception:
        art = "SECOND BRAIN"
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
            _md(result["answer"]),
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


async def cmd_ask(args):
    brain = Brain()
    try:
        result = await brain.ask(args.question, mode=args.mode, lazy=not args.no_lazy)
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
                        result = await brain.ask(args.question, mode=args.mode, lazy=False)
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


async def cmd_index_status(args):
    _print_index_status(_index_status())


async def cmd_history(args):
    brain = Brain()
    entries = brain.history(limit=args.limit)
    if not entries:
        print("No conversation history yet.")
        return
    for index, entry in enumerate(entries, start=1):
        print(f"--- {index} [{entry['timestamp']}] ({entry['mode']}) ---")
        print(f"Q: {entry['question']}")
        answer = entry["answer"]
        print(f"A: {answer[:2000]}")
        if len(answer) > 2000:
            print(f"... (answer truncated, {len(answer)} chars total)")
        print()


async def cmd_settings(args):
    brain = Brain()
    if args.action == "set":
        result = brain.set_setting(args.key, args.value)
        print(json.dumps(result, indent=2))
        return
    settings = brain.get_settings()
    console.print(
        _kv_table(
            "settings",
            settings,
            ["thinking", "history_turns", "mode", "model", "temperature", "top_k", "chunk_top_k", "lens"],
        )
    )
    console.print(f"[dim]valid keys: {', '.join(SETTINGS_DEFAULTS)}[/dim]")


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


def _schedule_status():
    loaded = "com.secondbrain.autoindex" in subprocess.run(
        ["launchctl", "list"], capture_output=True, text=True
    ).stdout
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
        "Label": "com.secondbrain.autoindex",
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
            _chip("style", settings["mode"], "magenta"),
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
                         "history_turns", "mode", "temperature", "lens_active"],
                    )
                )
                continue
            if lowered == "settings":
                console.print(
                    _kv_table(
                        "settings",
                        brain.get_settings(),
                        ["thinking", "history_turns", "mode", "model", "temperature", "top_k", "chunk_top_k", "lens"],
                    )
                )
                continue
            if lowered == "model":
                current = model_label(brain.get_settings().get("model") or "")
                console.print(f"[dim]query model: [cyan]{current}[/cyan][/dim]")
                console.print("[dim]options: [cyan]deepseek-chat[/cyan] (default · falls back to qwen offline) · [cyan]deepseek-think[/cyan] · [cyan]qwen[/cyan] (offline) · or any model name[/dim]")
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
            result = await brain.ask(question, mode=args.mode, lazy=not args.no_lazy)
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
                        result = await brain.ask(question, mode=args.mode, lazy=False)
            if result.get("status") == "answered":
                console.print()
                console.print(
                    Panel(
                        _md(result["answer"]),
                        title=f"answer · {result['timestamp']} · {result['mode']}",
                        title_align="left",
                        border_style="green",
                    )
                )
                if show_evidence and result.get("contexts"):
                    lines = result["contexts"].splitlines()
                    console.print(Panel("\n".join(lines[:80]), title="evidence", border_style="dim"))
    finally:
        await brain.close()


def main():
    parser = argparse.ArgumentParser(prog="brain", description="Second Brain (GraphRAG)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    index_parser = subparsers.add_parser("index", help="index new/changed files in the knowledge folder")
    index_parser.add_argument("--only", default=None, help="only index files under this relative path (e.g. 'notes')")

    ask = subparsers.add_parser("ask", help="ask a question with graph-based reasoning")
    ask.add_argument("question", nargs="+")
    ask.add_argument("--mode", default=None, choices=["naive", "local", "global", "hybrid", "mix"])
    ask.add_argument("--no-lazy", action="store_true", help="never auto-index before answering")

    subparsers.add_parser("status", help="show what is indexed")

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
    console.add_argument("--mode", default=None, choices=["naive", "local", "global", "hybrid", "mix"])
    console.add_argument("--no-lazy", action="store_true")

    args = parser.parse_args()
    command = args.command
    if command == "index":
        asyncio.run(cmd_index(args))
    elif command == "ask":
        args.question = " ".join(args.question)
        asyncio.run(cmd_ask(args))
    elif command == "status":
        asyncio.run(cmd_status(args))
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


if __name__ == "__main__":
    main()
