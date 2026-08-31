"""Second Brain — an opencode-style chat app for your knowledge vault.

Run:  uv run python brain_tui.py        (or double-click "Second Brain.command")
Chat with everything indexed from ~/Everything/second brain/.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.command import SimpleCommand
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Collapsible,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Markdown,
    Static,
)

from brain_core import Brain, KNOWLEDGE_ROOT, _load_manifest, model_label

DESERT_GOLD = "#E3C567"
EYES_OF_IBAD = "#4A90E2"


class SecondBrainApp(App):
    TITLE = "Second Brain"
    CSS = """
    Screen {
        background: #0d1117;
    }
    #row {
        height: 1fr;
    }
    #sidebar {
        width: 34;
        background: #161b22;
        border-right: solid #30363d;
        padding: 0 1;
    }
    #sidebar-title {
        padding: 1 1;
        color: #8b949e;
        text-style: bold;
    }
    #sidebar ListView {
        background: #161b22;
    }
    #chat {
        height: 1fr;
        padding: 1 2;
        background: #0d1117;
        overflow-y: auto;
    }
    #input-bar {
        dock: bottom;
        height: auto;
        background: #161b22;
        border-top: solid #30363d;
        padding: 0 1;
    }
    #input {
        background: #0d1117;
        border: round #30363d;
        color: #e6edf3;
    }
    #input:focus {
        border: round #4A90E2;
    }
    .msg-user {
        background: #1f3a5f;
        border: round #4A90E2;
        margin: 1 10 0 0;
        padding: 0 1;
    }
    .msg-ai {
        background: #161b22;
        border: round #30363d;
        margin: 1 0 0 10;
        padding: 0 1;
    }
    .msg-sys {
        color: #8b949e;
        margin: 1 0 0 0;
    }
    .sources {
        margin: 0 0 1 12;
        background: #161b22;
        border: round #2ea043;
    }
    .sources > .collapsible--title {
        color: #7ee787;
    }
    .bubble-user Label { padding: 0; }
    """
    BINDINGS = [
        Binding("ctrl+p", "search_commands", "Commands"),
        Binding("ctrl+n", "clear_chat", "New chat"),
        Binding("ctrl+r", "load_history", "History"),
        Binding("ctrl+c", "quit", "Quit"),
        Binding("escape", "focus_input", "Focus input"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.brain = Brain()
        self._busy = False
        self._history_entries = []

    # ---------- layout ----------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="row"):
            with Vertical(id="sidebar"):
                yield Label("PAST CONVERSATIONS", id="sidebar-title")
                yield ListView(id="history-list")
            with Vertical(id="chat"):
                yield VerticalScroll(id="chat-scroll")
        with Horizontal(id="input-bar"):
            yield Input(id="input", placeholder="ask your second brain…  (type /help)")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_status()
        self._append_system(
            "Welcome to your Second Brain. Ask anything about your indexed files — "
            "quote pulls, connections between texts, philosophy, whatever. "
            "Type [b]/help[/b] for commands."
        )
        self._refresh_history_sidebar()

    # ---------- helpers ----------

    def _refresh_status(self) -> None:
        s = self.brain.get_settings()
        model = model_label(s.get("model") or "")
        lens = (s.get("lens") or "").strip()
        lens_short = f"lens:{lens[:14]}" if lens else "no lens"
        self.sub_title = (
            f"{model} · {s.get('mode','mix')} · {lens_short} · "
            f"thoughts:{s.get('thinking','false')}"
        )

    def _chat(self) -> VerticalScroll:
        return self.query_one("#chat-scroll", VerticalScroll)

    def _scroll_end(self) -> None:
        self._chat().scroll_end(animate=False)

    def _append_system(self, text: str) -> None:
        self._chat().mount(Static(text, classes="msg-sys"))
        self._scroll_end()

    def _append_user(self, text: str) -> None:
        self._chat().mount(Static(f"[b]you[/b] — {text}", classes="msg-user"))
        self._scroll_end()

    def _append_ai(self, answer: str, contexts: str = "") -> None:
        self._chat().mount(Markdown(answer, classes="msg-ai"))
        ctx = (contexts or "").strip()
        if ctx:
            self._chat().mount(
                Collapsible(
                    Markdown(ctx[:4000], classes="msg-sys"),
                    title=f"sources ({len(ctx)} chars)",
                    classes="sources",
                )
            )
        self._scroll_end()

    def _refresh_history_sidebar(self) -> None:
        entries = self.brain.history(limit=100)
        self._history_entries = list(entries)
        lv = self.query_one("#history-list", ListView)
        lv.clear()
        for i, e in enumerate(reversed(entries)):
            q = (e.get("question") or "…").replace("\n", " ")[:48]
            ts = (e.get("timestamp") or "")[5:16]
            item = ListItem(Label(f"{ts}  {q}"))
            item._hist_idx = i
            lv.append(item)

    # ---------- input ----------

    @on(Input.Submitted)
    def _on_submit(self, event: Input.Submitted) -> None:
        text = (event.value or "").strip()
        event.input.value = ""
        if not text or self._busy:
            return
        if text.startswith("/"):
            self._run_command(text)
        else:
            self._ask(text)

    # ---------- asking ----------

    def _ask(self, question: str) -> None:
        self._append_user(question)
        self._set_busy(True, "thinking…")
        self.run_worker(self._do_ask(question), group="ask")

    async def _do_ask(self, question: str) -> None:
        try:
            entry = await self.brain.ask(question, lazy=False)
            answer = entry.get("answer") or "…(no answer)"
            contexts = entry.get("contexts") or ""
            self._append_ai(str(answer), str(contexts))
            self._refresh_history_sidebar()
        except Exception as exc:
            self._append_system(f"[red]error:[/red] {exc}")
        finally:
            self._set_busy(False)

    def _set_busy(self, busy: bool, placeholder: str = "") -> None:
        self._busy = busy
        inp = self.query_one("#input", Input)
        inp.disabled = busy
        if busy:
            inp.placeholder = placeholder
        else:
            inp.placeholder = "ask your second brain…  (type /help)"
            inp.focus()

    # ---------- commands ----------

    def _run_command(self, text: str) -> None:
        parts = text[1:].split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""
        handlers = {
            "help": lambda: self._append_system(HELP_TEXT),
            "clear": self._clear_chat,
            "quit": self.exit,
            "status": self._cmd_status,
            "settings": self._cmd_settings,
            "model": lambda: self._cmd_model(arg),
            "lens": lambda: self._cmd_lens(arg),
            "remember": lambda: self._cmd_remember(arg),
            "quotes": lambda: self._cmd_quotes(arg),
            "index": lambda: self._cmd_index(),
            "history": lambda: self._cmd_history(),
        }
        fn = handlers.get(cmd)
        if fn is None:
            self._append_system(f"[yellow]unknown command:[/yellow] /{cmd}  (try /help)")
            return
        self._append_system(f"/{cmd} {arg}".strip())
        fn()

    def _cmd_status(self) -> None:
        try:
            new, changed, removed, current = self.brain._scan_changes()
        except Exception as exc:
            self._append_system(f"[red]{exc}[/red]")
            return
        manifest = len(_load_manifest())
        pending = len(new) + len(changed)
        self._append_system(
            f"indexed documents: [b]{manifest}[/b] · pending: [b]{pending}[/b]"
            f"\nvault: {KNOWLEDGE_ROOT}"
        )

    def _cmd_settings(self) -> None:
        s = self.brain.get_settings()
        lines = "\n".join(f"  [b]{k}[/b]: {v}" for k, v in s.items())
        self._append_system(f"settings:\n{lines}")

    def _cmd_model(self, arg: str) -> None:
        if not arg:
            s = self.brain.get_settings()
            self._append_system(f"model: [b]{model_label(s.get('model') or '')}[/b]")
            return
        try:
            self.brain.set_setting("model", arg)
        except Exception as exc:
            self._append_system(f"[red]{exc}[/red]")
            return
        self._refresh_status()
        self._append_system(f"answer model → [b]{model_label(arg)}[/b]")

    def _cmd_lens(self, arg: str) -> None:
        if arg in ("", "--clear", "clear", "off"):
            self.brain.set_setting("lens", "")
            self._append_system("lens cleared.")
            self._refresh_status()
            return
        lens_file = KNOWLEDGE_ROOT / "lenses" / f"{arg}.md"
        if lens_file.exists():
            content = lens_file.read_text()
        else:
            content = arg
        self.brain.set_setting("lens", content)
        self._refresh_status()
        self._append_system(f"lens set: [b]{arg}[/b]")

    def _cmd_remember(self, arg: str) -> None:
        if not arg:
            self._append_system("usage: /remember <fact>  [--topic name]")
            return
        topic = "default"
        if "--topic" in arg:
            arg, _, topic = arg.partition("--topic")
            topic = topic.strip() or "default"
        self._set_busy(True, "remembering…")
        self.run_worker(self._do_remember(arg.strip(), topic))

    async def _do_remember(self, text: str, topic: str) -> None:
        try:
            await self.brain.remember(text, topic=topic)
            self._append_system(f"[green]remembered[/green] → {topic}")
            self._refresh_history_sidebar()
        except Exception as exc:
            self._append_system(f"[red]error:[/red] {exc}")
        finally:
            self._set_busy(False)

    def _cmd_quotes(self, arg: str) -> None:
        if not arg:
            self._append_system("usage: /quotes <topic>")
            return
        self._ask(
            "Find direct quotes about this topic. Return the exact verbatim "
            f"passages from the indexed texts, each with the document it comes "
            f"from. Topic: {arg}"
        )

    def _cmd_index(self) -> None:
        self._set_busy(True, "indexing… (this can take a while)")
        self.run_worker(self._do_index())

    async def _do_index(self) -> None:
        try:
            stats = await self.brain.index(verbose=False)
            if stats.get("already_running"):
                self._append_system(stats.get("message", "index already running"))
            else:
                self._append_system(
                    f"index: [b]+{stats.get('indexed',0)}[/b] new, "
                    f"[b]~{stats.get('updated',0)}[/b] changed, "
                    f"[b]-{stats.get('deleted',0)}[/b] removed "
                    f"({len(stats.get('errors',[]))} errors)"
                )
            self._refresh_status()
        except Exception as exc:
            self._append_system(f"[red]error:[/red] {exc}")
        finally:
            self._set_busy(False)

    def _cmd_history(self) -> None:
        entries = self.brain.history(limit=10)
        if not entries:
            self._append_system("no history yet.")
            return
        lines = []
        for e in reversed(entries):
            q = (e.get("question") or "…").replace("\n", " ")[:60]
            lines.append(f"  [dim]{e.get('timestamp','')}[/dim]  {q}")
        self._append_system("recent:\n" + "\n".join(lines))

    def _clear_chat(self) -> None:
        self._chat().remove_children()
        self._append_system("new chat. ask away.")

    # ---------- actions / palette ----------

    def action_clear_chat(self) -> None:
        self._clear_chat()

    def action_load_history(self) -> None:
        self._refresh_history_sidebar()
        self._append_system("history refreshed (sidebar).")

    def action_focus_input(self) -> None:
        self.query_one("#input", Input).focus()

    @on(ListView.Selected)
    def _on_history_selected(self, event: ListView.Selected) -> None:
        idx = getattr(event.item, "_hist_idx", None)
        if idx is None:
            return
        entries = list(reversed(self._history_entries))
        if idx >= len(entries):
            return
        e = entries[idx]
        self._clear_chat()
        self._append_user(e.get("question", "…"))
        self._append_ai(e.get("answer", "…"), e.get("contexts", ""))

    def action_search_commands(self) -> None:
        self.search_commands(
            [
                SimpleCommand("New chat (clear view)", self._clear_chat, "Clear the current conversation view"),
                SimpleCommand("Ask brain to index", self._cmd_index, "Index new/changed files"),
                SimpleCommand("Index status", self._cmd_status, "What is indexed, what is pending"),
                SimpleCommand("Show settings", self._cmd_settings, "Current settings"),
                SimpleCommand("Switch model", lambda: self._cmd_model(""), "Show current answer model"),
                SimpleCommand("Quotes", lambda: self._cmd_quotes(""), "Pull quotes about a topic"),
                SimpleCommand("Remember a fact", lambda: self._cmd_remember(""), "Store a permanent fact"),
                SimpleCommand("Quit", self.exit, "Exit the app"),
            ]
        )


HELP_TEXT = """[b]commands[/b]
  /ask <question>          any other text is asked directly
  /quotes <topic>          pull verbatim quotes about a topic
  /index                   index new/changed files
  /status                  what is indexed / pending
  /settings                show settings
  /model <name>            switch answer model (deepseek-chat · deepseek-think · qwen)
  /lens <name>             set a lens (from vault/lenses/); /lens --clear to clear
  /remember <fact>         permanently remember a fact [--topic name]
  /history                 recent questions
  /clear                   new chat
  /quit                    exit

[b]keys[/b]  ctrl+p commands · ctrl+n new chat · ctrl+r refresh history · escape focus input"""


def main() -> None:
    SecondBrainApp().run()


if __name__ == "__main__":
    main()
