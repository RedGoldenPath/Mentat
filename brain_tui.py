"""Mentat — an opencode-style chat app for your knowledge vault.

Run:  uv run python brain_tui.py        (or double-click "Mentat.command")
Chat with everything indexed from ~/Everything/mentat/.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from textual import events, on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.command import SimpleCommand
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    Collapsible,
    Input,
    Label,
    ListItem,
    ListView,
    Markdown,
    Static,
    Switch,
    TextArea,
)

from brain_core import (
    Brain,
    KNOWLEDGE_ROOT,
    VALID_MODES,
    VALID_ROUTING,
    VALID_THINKING,
    VOICE_PRESETS,
    _clean_markers,
    _index_is_running,
    effective_synth_model,
    _load_manifest,
    _no_answer_line,
    _library_profiles,
    _term_frequency,
    _short_summary,
    _style_invented,
    model_label,
)


def _silence_logs():
    """Keep openai/http noise from leaking into the terminal."""
    import logging
    for name in (
        "nano-vectordb",
        "httpx",
        "httpcore",
        "openai",
        "openai._base_client",
        "uvicorn",
        "asyncio",
    ):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    logging.getLogger().setLevel(logging.ERROR)


_silence_logs()


class _DelLabel(Label):
    """A ✕ label whose click stops propagation, so pressing it does NOT select
    (and therefore open) the ListItem row it lives in."""

    def __init__(self, callback, **kwargs):
        super().__init__("✕", **kwargs)
        self._callback = callback

    def on_click(self, event) -> None:
        event.stop()
        try:
            self._callback()
        except Exception:
            pass


class _OptButton(Button):
    """Clickable option chip; carries its value and callback for the screen."""

    def __init__(self, text, value, callback, **kwargs):
        super().__init__(str(text), **kwargs)
        self._value = value
        self._callback = callback


class _OptPicker(Vertical):
    """Setting row: a full-width name line, then clickable option chips below.

    The active option is marked and colored, so the current value is obvious
    at a glance. Options are real Buttons (not Labels) so clicks are delivered
    reliably by every Textual version.
    """

    def __init__(self, name, options, value, on_pick, **kwargs):
        super().__init__(**kwargs)
        self.add_class("opt-picker")
        self._name = name
        self._options = list(options)
        self._value = value
        self._on_pick = on_pick
        self._buttons = []

    def compose(self) -> ComposeResult:
        yield Button(str(self._name), classes="opt-name-btn")
        with Horizontal(classes="opt-row"):
            for opt in self._options:
                btn = _OptButton(opt, opt, self._on_pick, classes="opt-item")
                self._buttons.append(btn)
                yield btn

    def on_mount(self) -> None:
        self._refresh_highlight()

    def cycle(self) -> None:
        """Advance to the next option (clicking the setting name cycles)."""
        if not self._options:
            return
        try:
            i = self._options.index(self._value)
        except ValueError:
            i = -1
        self._on_pick(self._options[(i + 1) % len(self._options)])

    def set_value(self, value) -> None:
        self._value = value
        self._refresh_highlight()

    def _refresh_highlight(self) -> None:
        for btn in self._buttons:
            active = btn._value == self._value
            btn.set_class(active, "opt-active")
            btn.set_class(not active, "opt-idle")
            try:
                btn.variant = "success" if active else "default"
            except Exception:
                pass
            try:
                btn.label = f"{'●' if active else '○'} {btn._value}"
            except Exception:
                pass


class SettingsScreen(Screen):
    """Full-page settings: every /command becomes a clickable text option."""

    BINDINGS = [Binding("escape", "back", "Back")]

    def action_back(self) -> None:
        self.app.pop_screen()

    MODELS = ["deepseek-flash", "deepseek-think", "qwen", "qwen-deep"]
    NONE_LENS = "- none -"

    @classmethod
    def _lens_options(cls):
        options = [cls.NONE_LENS]
        try:
            lens_dir = KNOWLEDGE_ROOT / "lenses"
            if lens_dir.exists():
                options += sorted(p.stem for p in lens_dir.glob("*.md"))
        except Exception:
            pass
        return options

    def compose(self) -> ComposeResult:
        yield Static(
            "settings — debug menu · click an option · ● = active · esc = back",
            classes="msg-sys",
        )
        yield Static(
            "hover any setting for a plain-English explanation",
            id="settings-help",
            classes="settings-help",
        )
        with VerticalScroll(id="settings-panel"):
            yield from self._form()

    @staticmethod
    def _pretty(key):
        return key.replace("_", " ").strip().capitalize()

    @classmethod
    def _options_for(cls, key):
        if key == "model":
            return cls.MODELS
        if key == "voice":
            return list(VOICE_PRESETS)
        if key == "thinking":
            return list(VALID_THINKING)
        if key == "mode":
            return list(VALID_MODES)
        if key == "routing":
            return list(VALID_ROUTING)
        if key == "search_depth":
            return ["auto", "always", "off"]
        if key == "lens":
            return cls._lens_options()
        return []

    @staticmethod
    def _kind(key, default):
        if isinstance(default, bool):
            return "bool"
        if key in (
            "model", "voice", "thinking", "mode", "routing", "search_depth", "lens",
        ):
            return "pick"
        if isinstance(default, (int, float)):
            return "int"
        return "text"

    def _form(self):
        from brain_core import SETTINGS_SPEC

        s = self.app.brain.get_settings()
        section = None
        for spec in SETTINGS_SPEC:
            key = spec["key"]
            help_text = f"{self._pretty(key)} — {spec.get('help', '')}"
            if spec["section"] != section:
                section = spec["section"]
                yield Label(f"── {section} ──", classes="settings-section")
            default = s.get(key)
            kind = self._kind(key, default)
            if kind == "pick":
                current = default
                if key == "lens":
                    lens_val = str(default or "")
                    current = (
                        self.NONE_LENS
                        if not lens_val.strip()
                        else next(
                            (o for o in self._lens_options() if o != self.NONE_LENS),
                            self.NONE_LENS,
                        )
                    )
                picker = _OptPicker(
                    help_text,
                    self._options_for(key),
                    current,
                    (lambda v, k=key: self._pick(k, v)),
                    id=f"set-{key}",
                )
                picker._setting_help = help_text
                yield picker
            elif kind == "bool":
                lbl = Label(help_text)
                lbl._setting_help = help_text
                yield lbl
                with Horizontal(classes="opt-row"):
                    sw = Switch(id=f"set-{key}")
                    sw._setting_help = help_text
                    yield sw
                    state = Label("", id=f"state-{key}", classes="opt-state")
                    state._setting_help = help_text
                    yield state
            else:
                lbl = Label(help_text)
                lbl._setting_help = help_text
                yield lbl
                inp = Input(
                    id=f"set-{key}",
                    placeholder=str(default if default is not None else ""),
                )
                inp._setting_help = help_text
                yield inp
        yield Static("", id="settings-msg", classes="msg-sys")
        with Horizontal(id="settings-actions"):
            yield Button("Run index", id="btn-run-index", classes="mini-btn")
            yield Button("Run health", id="btn-run-health", classes="mini-btn")
            yield Button("Reset defaults", id="btn-settings-reset", classes="mini-btn")
            yield Button("back", id="btn-settings-close", classes="mini-btn")

    def refresh_values(self) -> None:
        from brain_core import SETTINGS_SPEC

        s = self.app.brain.get_settings()
        for spec in SETTINGS_SPEC:
            key = spec["key"]
            default = s.get(key)
            kind = self._kind(key, default)
            try:
                if kind == "pick":
                    if key == "lens":
                        lens_val = str(default or "")
                        current = (
                            self.NONE_LENS
                            if not lens_val.strip()
                            else next(
                                (o for o in self._lens_options() if o != self.NONE_LENS),
                                self.NONE_LENS,
                            )
                        )
                    else:
                        current = default
                    self.query_one(f"#set-{key}", _OptPicker).set_value(current)
                elif kind == "bool":
                    self.query_one(f"#set-{key}", Switch).value = bool(default)
                    state = self.query_one(f"#state-{key}", Label)
                    state.update("on" if bool(default) else "off")
                    state.set_class(bool(default), "state-on")
                    state.set_class(not bool(default), "state-off")
                else:
                    self.query_one(f"#set-{key}", Input).value = (
                        "" if default is None else str(default)
                    )
            except Exception:
                continue

    def on_mount(self) -> None:
        try:
            self.refresh_values()
        except Exception:
            pass

    def _pick(self, key: str, value) -> None:
        if key == "lens":
            if value == self.NONE_LENS:
                self._apply("lens", "")
            else:
                try:
                    content = (KNOWLEDGE_ROOT / "lenses" / f"{value}.md").read_text()
                except Exception:
                    content = value
                self._apply("lens", content)
        elif key == "model":
            self._apply("model", str(value))
        else:
            self._apply(key, value)
        try:
            self.refresh_values()
        except Exception:
            pass

    def _apply(self, key: str, value) -> None:
        msg = self.query_one("#settings-msg", Static)
        try:
            self.app.brain.set_setting(key, value)
            msg.update(f"[green]ok: {key} -> {value}[/green]")
            self.app._refresh_status()
            self.app._render_header()
        except Exception as exc:
            msg.update(f"[red]{exc}[/red]")

    @on(events.MouseMove)
    def _on_mouse_move(self, event) -> None:
        """Hover explainer: show the setting's plain-English help under the title."""
        try:
            hit = self.get_widget_at(
                getattr(event, "screen_x", event.x),
                getattr(event, "screen_y", event.y),
            )
            widget = hit[0] if isinstance(hit, tuple) else hit
        except Exception:
            return
        node = widget
        while node is not None and not getattr(node, "_setting_help", None):
            node = getattr(node, "parent", None)
        try:
            bar = self.query_one("#settings-help", Static)
        except Exception:
            return
        text = (
            node._setting_help
            if node is not None
            else "hover any setting for a plain-English explanation"
        )
        if getattr(bar, "_last_help", None) != text:
            bar._last_help = text
            bar.update(text)

    @on(Input.Submitted)
    def _on_input_submitted(self, event: Input.Submitted) -> None:
        cid = event.input.id or ""
        if not cid.startswith("set-"):
            return
        key = cid[4:]
        raw = event.value.strip()
        self._apply(key, None if not raw and key == "temperature" else raw)

    @on(Switch.Changed)
    def _on_switch_changed(self, event: Switch.Changed) -> None:
        cid = getattr(event.switch, "id", "") or ""
        if cid.startswith("set-"):
            self._apply(cid[4:], event.value)
            try:
                state = self.query_one(f"#state-{cid[4:]}", Label)
                state.update("on" if event.value else "off")
                state.set_class(event.value, "state-on")
                state.set_class(not event.value, "state-off")
            except Exception:
                pass

    @on(Button.Pressed)
    def _on_panel_button(self, event: Button.Pressed) -> None:
        btn = event.button
        if btn.has_class("opt-name-btn"):
            node = btn.parent
            while node is not None and not isinstance(node, _OptPicker):
                node = node.parent
            if isinstance(node, _OptPicker):
                try:
                    node.cycle()
                except Exception as exc:
                    try:
                        self.query_one("#settings-msg", Static).update(
                            f"[red]{exc}[/red]"
                        )
                    except Exception:
                        pass
            return
        if btn.has_class("opt-item"):
            cb = getattr(btn, "_callback", None)
            val = getattr(btn, "_value", None)
            if cb is not None:
                try:
                    cb(val)
                except Exception as exc:
                    try:
                        self.query_one("#settings-msg", Static).update(
                            f"[red]{exc}[/red]"
                        )
                    except Exception:
                        pass
            return
        bid = btn.id or ""
        if bid == "btn-settings-close":
            self.action_back()
        elif bid == "btn-run-index":
            self.app._cmd_index()
            self.action_back()
        elif bid == "btn-run-health":
            self.app._cmd_health()
            self.action_back()
        elif bid == "btn-settings-reset":
            from brain_core import SETTINGS_DEFAULTS

            for key, value in SETTINGS_DEFAULTS.items():
                try:
                    self.app.brain.set_setting(key, value)
                except Exception:
                    continue
            self.refresh_values()
            msg = self.query_one("#settings-msg", Static)
            msg.update("[green]settings reset to defaults[/green]")


class CommandTextArea(TextArea):
    """TextArea that routes Tab/arrows/Enter to the command suggestion list when it's open."""

    async def _on_key(self, event) -> None:
        app = self.app
        if getattr(app, "_suggestions_visible", False):
            if event.key in ("down", "tab"):
                app._suggestion_move(1)
                event.prevent_default()
                return
            if event.key == "up":
                app._suggestion_move(-1)
                event.prevent_default()
                return
            if event.key == "enter":
                app._suggestion_accept()
                event.prevent_default()
                return
        # plain Enter sends; shift+enter inserts a new line
        if event.key == "enter":
            app.action_submit_input()
            event.prevent_default()
            return
        await super()._on_key(event)


class MentatApp(App):
    TITLE = "Mentat"
    CSS = """
    $spice: #FFB066;
    $ibad:  #4A90E2;
    $gold:  #E3C567;
    $green: #2F855A;
    $paper: #F5F0E6;
    $ink-dim: #B08D62;
    $border: #4A3420;
    $good:  #7FD37F;
    $bad:   #E07A6A;
    $hover: #FFD37A;

    Screen {
        background: #1C1209;
    }
    #row {
        height: 1fr;
    }
    #sidebar {
        width: 1fr;
        min-width: 16;
        max-width: 44;
        background: #261609;
        border-right: solid $border;
        padding: 0 1;
    }
    #sidebar-title {
        padding: 1 1;
        color: $spice;
        text-style: bold;
    }
    .new-btn {
        width: 1fr;
        height: 3;
        margin: 1 0 0 0;
        background: #331E10;
        border: round $spice;
        color: $paper;
    }
    .new-btn:hover {
        background: #4A2A15;
        border: round $gold;
    }
    .new-btn:focus {
        border: round $ibad;
    }
    #sidebar ListView {
        background: #261609;
        padding: 0;
    }
    #sidebar ListView ListItem {
        height: 1;
        width: 1fr;
        padding: 0 0 0 1;
        color: #C9A87A;
        text-wrap: nowrap;
        overflow: hidden;
    }
    #sidebar ListView ListItem Horizontal {
        width: 1fr;
        height: 1;
    }
    #sidebar ListView ListItem.--highlight {
        background: #3A2413;
        color: $paper;
    }
    #chat {
        width: 4fr;
        height: 1fr;
        padding: 1 2;
        background: #1C1209;
        overflow-y: auto;
    }
    #bottom {
        height: auto;
    }
    #suggestions {
        display: none;
        height: auto;
        max-height: 8;
        margin: 0 2;
        background: #0E1A2B;
        border: round $ibad;
    }
    #suggestions.visible {
        display: block;
    }
    #suggestions ListView {
        background: #0E1A2B;
    }
    #suggestions ListItem {
        height: 1;
        color: #C9D9E8;
        padding: 0 1;
    }
    #suggestions ListItem.--highlight {
        background: #4A2A15;
        color: $paper;
    }
    #meta-bar {
        height: 1;
        align-horizontal: right;
        padding: 0 1;
        background: #1C1209;
    }
    #input-bar {
        height: auto;
        min-height: 3;
        max-height: 16;
        padding: 0 1;
        background: #1C1209;
    }
    #input {
        height: auto;
        min-height: 3;
        max-height: 14;
        background: #0E1A2B;
        border: round $ibad;
        color: $paper;
        padding: 0 1;
    }
    #input:focus {
        border: round #6FB1FF;
    }
    #input > .text-area--placeholder {
        color: $ink-dim;
    }
    #input > .text-area--cursor {
        color: $ibad;
    }
    .msg-row { width: 1fr; height: auto; }
    .msg-row-user { align-horizontal: right; }
    .msg-row-ai { align-horizontal: left; }
    .msg-box { height: auto; width: auto; }
    .msg-box-user { margin: 1 0 0 0; }
    .msg-box-ai { margin: 1 0 0 0; }
    .msg-user {
        background: #331E10;
        border: round $spice;
        color: #FFFFFF;
        padding: 0 1;
    }
    .msg-ai {
        background: #23150A;
        border: round #5A4026;
        color: #FFFFFF;
        padding: 0 1;
    }
    .msg-actions { height: 1; }
    .msg-actions-user { align-horizontal: right; }
    .msg-actions-ai { align-horizontal: left; }
    .mini-btn {
        width: auto;
        height: 1;
        min-height: 0;
        padding: 0 1;
        margin: 0 0 0 1;
        background: transparent;
        border: none;
        color: $ink-dim;
        text-style: not bold;
    }
    .mini-btn:hover {
        color: $paper;
    }
    .mini-btn.copied {
        color: $green;
    }
    .paste-btn {
        margin: 0 0 0 1;
    }
    #settings-panel {
        width: 100%;
        height: 1fr;
        background: #171007;
        border: round #5A4026;
        padding: 0 1;
    }
    #settings-panel Label {
        color: $spice;
        margin: 1 0 0 0;
    }
    .opt-name {
        width: 100%;
        height: 1;
        color: $paper;
    }
    #settings-panel Button.opt-name-btn {
        width: 100%;
        height: 1;
        min-width: 0;
        border: none;
        background: transparent;
        color: $paper;
        padding: 0;
    }
    #settings-panel Button.opt-name-btn:hover {
        color: $hover;
        text-style: bold;
        background: transparent;
    }
    #settings-panel Button.opt-name-btn > .button--label {
        width: 100%;
        text-align: left;
    }
    #settings-panel .opt-picker {
        height: auto;
    }
    .settings-section {
        width: 100%;
        height: 1;
        color: $gold;
        text-style: bold;
        margin: 1 0 0 0;
    }
    .opt-row {
        height: auto;
    }
    .opt-state {
        width: auto;
        height: 1;
        padding: 0 1;
    }
    .state-on {
        color: $good;
        text-style: bold;
    }
    .state-off {
        color: $bad;
    }
    #settings-panel Button.opt-item {
        min-width: 0;
        width: auto;
        height: 1;
        padding: 0 1;
        margin: 0 1 0 0;
        border: none;
        background: transparent;
        color: $ink-dim;
    }
    #settings-panel Button.opt-item:hover {
        color: $hover;
        text-style: bold;
        background: $border;
    }
    #settings-panel Button.opt-item.opt-active {
        color: $good;
        text-style: bold;
    }
    #settings-panel .msg-sys {
        margin: 0;
    }
    #settings-actions {
        margin: 1 0 1 0;
        height: 1;
    }
    #settings-panel Input {
        width: 1fr;
        height: 1;
        background: #23150A;
        border: round #5A4026;
        color: $paper;
    }
    #settings-panel Input:focus {
        border: round $spice;
    }
    #settings-panel Switch {
        height: 1;
        background: #23150A;
    }
    #settings-panel Switch .switch--slider {
        background: $bad 60%;
    }
    #settings-panel Switch.-on .switch--slider {
        background: $good;
    }
    .settings-help {
        color: $gold;
        height: 1;
        margin: 0;
    }
    .msg-sys {
        color: $ink-dim;
        margin: 1 0 0 0;
    }
    .sources {
        margin: 0 0 1 16;
        background: #171007;
        border: round #5A4026;
    }
    .sources > .collapsible--title {
        color: $spice;
    }
    .thinking {
        margin: 0 0 1 2;
        background: #171007;
        border: round #5A4026;
    }
    .thinking > .collapsible--title {
        color: $ink-dim;
        text-style: italic;
    }
    .bubble-user Label { padding: 0; }
    #status-panel {
        height: 25%;
        background: #0A0704;
        border-bottom: solid $border;
        padding: 0 2;
    }
    #header {
        height: 100%;
    }
    .hist-label {
        width: 1fr;
        height: 1;
        padding: 0;
        text-wrap: nowrap;
        overflow: hidden;
    }
    .hist-del {
        width: 5;
        min-width: 5;
        height: 1;
        min-height: 0;
        padding: 0;
        margin: 0;
        background: transparent;
        border: none;
        color: $ink-dim;
    }
    .hist-del:hover {
        color: #FF5F57;
    }
    #typing {
        color: $spice;
        margin: 0 0 0 1;
        height: 1;
    }

    /* color-code markdown themes/info: gold headings & quotes, spice code, white body */
    .msg-ai MarkdownH1,
    .msg-ai MarkdownH2,
    .msg-ai MarkdownH3,
    .msg-ai MarkdownH4,
    .msg-ai MarkdownH5,
    .msg-ai MarkdownH6 {
        color: $spice;
    }
    .msg-ai MarkdownBlockQuote {
        color: $gold;
    }
    .msg-ai .code_inline {
        color: $gold;
    }
    .msg-ai .strong {
        color: #9EC3FF;
    }
    """

    BINDINGS = [
        Binding("ctrl+p", "search_commands", "Commands"),
        Binding("ctrl+n", "clear_chat", "New chat"),
        Binding("ctrl+r", "load_history", "History"),
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+y", "copy_last", "Copy last answer"),
        Binding("ctrl+shift+y", "copy_user", "Copy your last message", show=False),
        Binding("ctrl+shift+x", "stop_thinking", "Stop"),
        Binding("ctrl+shift+c", "copy", "Copy", show=False),
        Binding("ctrl+shift+v", "paste_clipboard", "Paste", show=False),
        Binding("super+c", "copy", "Copy", show=False),
        Binding("super+v", "paste_clipboard", "Paste", show=False),
        Binding("escape", "escape_handler", "Focus / stop", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.brain = Brain()
        self._busy = False
        self._history_entries = []
        self._convs = []
        self._displayed_convs = []
        self._hist_ready = False
        self._think_md = None
        self._think_panel = None
        self._think_acc = ""
        self._think_last = 0.0
        self._think_anchor = None
        self._think_collapsed = False
        self._last_answer = ""
        self._last_user_message = ""
        self._typing_indicator = None
        self._typing_timer = None
        self._progress_msg = ""
        self._typing_dots = ["·", "··", "···", " "]
        self._last_question = None
        self._last_q_widget = None
        self._last_a_widgets = []
        self._pending_edit = False
        self._pending_edit_removals = 0
        self._pending_confirm = None
        self._request_queue = []
        self._queue_active = False
        self._queue_gen = 0
        self._queue_worker = None
        self._active_request = None
        self._index_worker = None
        self._conv_sig = None
        self._code_sig = None
        self._splash_art = "MENTAT"
        self._status_lines = ["", ""]
        self._suggestions_visible = False

    async def on_event(self, event):
        """Crash-proof event dispatch.

        Live markdown re-renders can race with mouse/keyboard events targeting
        a widget that was just swapped out (Textual then forwards to a widget
        whose container is None and raises). Swallow those so a stray click
        during streaming can never kill the app.
        """
        try:
            await super().on_event(event)
        except AttributeError:
            pass

    # ---------- layout ----------

    def compose(self) -> ComposeResult:
        with Vertical(id="status-panel"):
            yield Static(id="header")
        with Horizontal(id="row"):
            with Vertical(id="sidebar"):
                yield Button("＋  New conversation", id="btn-new", classes="new-btn")
                yield Label("PAST CONVERSATIONS", id="sidebar-title")
                yield ListView(id="history-list")
            with Vertical(id="chat"):
                yield VerticalScroll(id="chat-scroll")
        with Vertical(id="bottom"):
            yield ListView(id="suggestions")
            with Horizontal(id="meta-bar"):
                yield Button(
                    "settings",
                    id="btn-settings",
                    classes="mini-btn",
                    tooltip="toggle the settings panel",
                )
            with Horizontal(id="input-bar"):
                yield CommandTextArea(
                    id="input",
                    placeholder="ask mentat…  (enter = send · drop a file path or /attach to attach · shift+enter = new line)",
                    soft_wrap=True,
                )
    def on_mount(self) -> None:
        self._refresh_splash()
        self._refresh_status()
        self.set_timer(0.05, self._render_header)
        self._append_system(
            "[b]what wisdom do you seek...?[/b]  [dim]/help for commands[/dim]"
        )
        self._restore_last_conversation()
        self.query_one("#history-list", ListView).can_focus = False
        self._refresh_history_sidebar()
        # Enable sidebar clicks only after the startup auto-highlight settles,
        # so a synthetic selection at mount can't wipe the restored transcript.
        self.set_timer(0.6, self._enable_hist_clicks)
        self.run_worker(self._backfill_worker(), group="backfill", exclusive=False)
        self.run_worker(self._health_worker(), group="health", exclusive=False)
        self.query_one("#input", TextArea).focus()
        self._code_sig = self._code_signature()
        self._fit_new_button()
        self.set_interval(5, self._tick)

    def _enable_hist_clicks(self) -> None:
        self._hist_ready = True

    def _restore_last_conversation(self) -> None:
        """Show the most recent conversation so follow-ups have context after a restart."""
        try:
            entries = self.brain.history(limit=6)
        except Exception:
            return
        for e in entries:
            self._append_user(e.get("question", "…"))
            self._append_ai(e.get("answer", "…"))

    def on_resize(self) -> None:
        self._render_header()
        self._fit_new_button()

    def _fit_new_button(self) -> None:
        """Shrink the new-conversation label to fit the sidebar width."""
        try:
            width = self.query_one("#sidebar").container_size.width
            btn = self.query_one("#btn-new", Button)
            label = "＋  New conversation"
            if width < 16:
                label = "New"
            elif width < 24:
                label = "New convo"
            btn.label = label
        except Exception:
            pass

    # ---------- helpers ----------

    def _refresh_status(self) -> None:
        try:
            new, changed, removed, current = self.brain._scan_changes()
            self._status_pending = len(new) + len(changed)
        except Exception:
            self._status_pending = 0
        self._status_docs = self._storage_docs()
        self._update_status()

    @staticmethod
    def _storage_docs() -> int:
        try:
            return len(_load_manifest())
        except Exception:
            return 0

    def _refresh_splash(self) -> None:
        try:
            import pyfiglet
            art = pyfiglet.figlet_format("MENTAT", font="small").rstrip("\n")
        except Exception:
            art = "MENTAT"
        self._splash_art = art
        self._render_header()

    def _render_header(self) -> None:
        """One Static = star field with the centered splash + status spliced in."""
        try:
            w = self.query_one("#header").region.width
            h = self.query_one("#header").region.height
        except Exception:
            return
        if w < 10 or h < 4:
            return
        import random
        rng = random.Random(7)
        chars = ["·", "·", "·", "*", "+", "°", "•"]
        colors = ["#FFFFFF", "#C7D3FF", "#E8D9A0", "#9DB4FF", "#FFE9C7"]
        cx, cy = w / 2.0, h / 2.0
        hw, hh = max(w / 2.0, 1), max(h / 2.0, 1)
        grid = []
        for y in range(h):
            row = []
            for x in range(w):
                dx = (x - cx) / hw
                dy = (y - cy) / hh
                d = min(1.0, (dx * dx + dy * dy) ** 0.5)
                if rng.random() < 0.036 * (d ** 1.5):
                    row.append([rng.choice(chars), rng.choice(colors)])
                else:
                    row.append([" ", None])
            grid.append(row)

        splash_lines = getattr(self, "_splash_art", "MENTAT").split("\n")
        status_lines = getattr(self, "_status_lines", ["", ""])
        content = [(ln, "#FFB066") for ln in splash_lines] + [
            (ln, "#F5F0E6") for ln in status_lines
        ]
        top = max(0, (h - len(content)) // 2)
        for i, (line, color) in enumerate(content):
            ry = top + i
            if ry >= h or not line:
                continue
            pad = max(0, (w - len(line)) // 2)
            row = grid[ry]
            for j, ch in enumerate(line):
                idx = pad + j
                if idx < len(row):
                    row[idx] = [ch, color]

        out = []
        for row in grid:
            parts = []
            i = 0
            n = len(row)
            while i < n:
                ch, col = row[i]
                if col:
                    run = []
                    while i < n and row[i][1] == col:
                        run.append(row[i][0])
                        i += 1
                    parts.append(f"[{col}]{''.join(run)}[/]")
                else:
                    parts.append(ch or " ")
                    i += 1
            out.append("".join(parts))
        self.query_one("#header", Static).update("\n".join(out))

    def _update_status(self) -> None:
        s = self.brain.get_settings()
        try:
            model = model_label(effective_synth_model())
        except Exception:
            model = model_label(s.get("model") or "")
        kind = (getattr(self, "_last_served_info", None) or {}).get("kind") or "—"
        thinking = s.get("thinking", "false")
        lens = (s.get("lens") or "").strip()
        lens_short = (lens[:12] + "…") if len(lens) > 12 else (lens or "none")
        voice = s.get("voice", "default") or "default"
        offline = "  · OFFLINE" if s.get("offline") else ""
        running = "indexing" if self._indexing() else "ready"
        self._status_lines = [
            f"MODEL {model}  KIND {kind}  THINKING {thinking}  LENS {lens_short}{offline}",
            f"VOICE {voice} · INDEX {self._status_docs} files · {self._status_pending} pending · "
            f"{running}  · {time.strftime('%H:%M')}",
        ]
        self._render_header()

    def _indexing(self) -> bool:
        return (
            (self._index_worker is not None and not self._index_worker.is_finished)
            or _index_is_running()
        )

    def _tick(self) -> None:
        self._status_docs = self._storage_docs()
        self._tick_n = getattr(self, "_tick_n", 0) + 1
        if self._tick_n % 6 == 0:
            prev = self._status_pending
            self._refresh_status()
            if self._status_pending and self._status_pending != prev:
                self._append_system(
                    f"[yellow]{self._status_pending} file(s) added or changed — /index to process[/yellow]"
                )
        # auto-reload: when code files change and we're idle, restart in
        # place so new features apply without quitting.
        try:
            if (
                self.brain.get_settings().get("auto_reload", False)
                and not self._busy
                and not self._queue_active
                and self._code_signature() != getattr(self, "_code_sig", None)
            ):
                self._cmd_reload()
                return
        except Exception:
            pass
        # live preview: external writers (tests, CLI) touching the
        # conversations show up within one tick — no restart needed.
        try:
            sig = self._conv_signature()
            if sig != getattr(self, "_conv_sig", None):
                self._conv_sig = sig
                self._refresh_history_sidebar()
        except Exception:
            pass
        self._update_status()
        # network canary: detect an unreachable API and offer/auto-flip offline
        if self._tick_n % 6 == 0 and not getattr(self, "_net_check_running", False):
            self._net_check_running = True
            self.run_worker(self._network_canary(), group="canary", exclusive=False)
        # self-heal sweep once a minute, only while idle
        if (
            self._tick_n % 12 == 0
            and not getattr(self, "_heal_running", False)
            and not self._busy
            and not self._queue_active
        ):
            try:
                if self.brain.get_settings().get("self_heal", "remediate") in ("remediate", "full"):
                    self._heal_running = True
                    self.run_worker(self._auto_heal(), group="heal", exclusive=False)
            except Exception:
                pass

    async def _network_canary(self) -> None:
        """Check API reachability; banner + optional auto-offline on change."""
        try:
            from brain_core import provider_status

            settings = self.brain.get_settings()
            if settings.get("offline"):
                return  # already local-only; nothing to check
            state = await asyncio.to_thread(provider_status)
        except Exception:
            return
        finally:
            self._net_check_running = False
        down = not state.get("reachable", True)
        if down == getattr(self, "_net_down", None):
            return
        self._net_down = down
        if down:
            if self.brain.get_settings().get("auto_offline"):
                self.brain.set_setting("offline", True)
                self._auto_offline_applied = True
                self._append_system(
                    "[yellow]API unreachable — switched to offline (local qwen). "
                    "/offline toggles back.[/yellow]"
                )
            else:
                self._append_system(
                    "[yellow]API unreachable — /offline for local qwen, or check "
                    "the network.[/yellow]"
                )
        else:
            if getattr(self, "_auto_offline_applied", False):
                self.brain.set_setting("offline", False)
                self._auto_offline_applied = False
                self._append_system("[green]API reachable again — back online.[/green]")
            else:
                self._append_system("[green]API reachable again.[/green]")
        self._refresh_status()

    def _conv_signature(self):
        try:
            convs = self.brain.conversations()
            return (
                len(convs),
                tuple((c.get("conv"), c.get("count"), c.get("last_ts")) for c in convs),
            )
        except Exception:
            return None

    def _chat(self) -> VerticalScroll:
        return self.query_one("#chat-scroll", VerticalScroll)

    def _scroll_end(self) -> None:
        self._chat().scroll_end(animate=False)

    def _append_system(self, text: str) -> None:
        self._chat().mount(Static(text, classes="msg-sys"))
        self._scroll_end()

    def _append_user(self, text: str, editable: bool = True) -> None:
        self._last_user_message = text
        self._mount_msg_box(text, kind="user", editable=editable)
        self._scroll_end()

    def _append_ai(self, answer: str, contexts: str = "") -> None:
        self._last_answer = answer
        box = self._mount_msg_box(answer, kind="ai")
        self._last_a_widgets = [box]
        self._scroll_end()

    def _mount_msg_box(self, text: str, kind: str, editable: bool = True):
        """Mount a message bubble (right for you, left for the brain) with copy/edit buttons.

        Returns the outer alignment row; its child ``.msg-box`` carries the bubble.
        """
        bubble = (
            Static(text, classes="msg-user")
            if kind == "user"
            else Markdown(text, classes="msg-ai")
        )
        buttons = []
        copy = Button("copy", classes="mini-btn", tooltip="copy this message")
        copy._action = "copy"
        copy._msg_kind = kind
        copy._msg_text = text
        buttons.append(copy)
        if kind == "user" and editable:
            edit = Button("edit", classes="mini-btn", tooltip="edit & re-ask")
            edit._action = "edit"
            edit._msg_kind = kind
            edit._msg_text = text
            buttons.append(edit)
        row = Horizontal(*buttons, classes=f"msg-actions msg-actions-{kind}")
        box = Vertical(bubble, row, classes=f"msg-box msg-box-{kind}")
        box._msg_kind = kind
        box._msg_text = text
        outer = Horizontal(box, classes=f"msg-row msg-row-{kind}")
        outer._msg_kind = kind
        outer._msg_text = text
        outer._msg_box = box
        outer._bubble = bubble
        outer._actions = row
        chat = self._chat()
        if len(chat.children) > 150:
            for _ in range(50):
                first = chat.children[0]
                if getattr(first, "id", None) == "typing":
                    break
                try:
                    first.remove()
                except Exception:
                    break
            if chat.children:
                chat.mount(
                    Static("[dim]…earlier messages trimmed[/dim]", classes="msg-sys"),
                    before=chat.children[0],
                )
        chat.mount(outer)
        return outer

    def _outer_for(self, box):
        """Map an inner ``.msg-box`` to the chat child row that contains it."""
        if box is None:
            return None
        for child in self._chat().children:
            if child is box or getattr(child, "_msg_box", None) is box:
                return child
        return box

    @staticmethod
    def _find_msg_box(widget):
        for node in widget.ancestors_with_self:
            if "msg-box" in node.classes:
                return node
        return None

    def _truncate_view_after(self, box) -> int:
        """Remove a message row and everything after it. Returns turns removed."""
        chat = self._chat()
        removed_turns = 0
        truncating = False
        for child in list(chat.children):
            if truncating:
                if getattr(child, "_msg_kind", None) == "user":
                    removed_turns += 1
                child.remove()
            elif child is box or (getattr(child, "_msg_box", None) is box):
                truncating = True
                removed_turns = 1
                child.remove()
        self._last_q_widget = None
        self._last_a_widgets = []
        return removed_turns

    def _copy_message(self, btn: Button) -> None:
        text = getattr(btn, "_msg_text", "") or ""
        if not text:
            return
        try:
            self.copy_to_clipboard(text)
        except Exception as exc:
            self._append_system(f"[red]copy failed: {exc}[/red]")
            return
        from brain_core import _telemetry_log_feedback

        _telemetry_log_feedback("copy", str(text)[:120])
        old = btn.label
        btn.label = "✓"
        btn.set_class(True, "copied")
        self.set_timer(1.4, lambda: self._reset_btn(btn, old))
        self.query_one("#input", TextArea).focus()

    @staticmethod
    def _reset_btn(btn: Button, old) -> None:
        btn.set_class(False, "copied")
        btn.label = old

    def _edit_message(self, btn: Button) -> None:
        if self._busy:
            self.action_stop_thinking()
        box = self._find_msg_box(btn)
        if box is None:
            return
        text = getattr(btn, "_msg_text", "") or ""
        from brain_core import _telemetry_log_feedback

        _telemetry_log_feedback("reask", str(text)[:120])
        removed = self._truncate_view_after(box)
        self._pending_edit = True
        self._pending_edit_removals = removed
        inp = self.query_one("#input", TextArea)
        inp.text = text
        inp.focus()
        self._append_system("[dim]editing — press enter to re-ask[/]")

    async def _health_worker(self):
        """Quiet library health check on startup; warnings go to the status line."""
        try:
            results = await self.brain.health()
            fails = [name for name, ok, _ in results if not ok]
            if fails:
                self._append_system(
                    f"[yellow]health: {len(fails)} warning(s) — run /health[/yellow]"
                )
        except Exception:
            pass

    async def _backfill_worker(self):
        """Summarize recent history entries missing a summary (background)."""
        try:
            from brain_core import _backfill_summaries

            await _backfill_summaries(limit=20)
        except Exception:
            pass
        try:
            self._refresh_history_sidebar()
        except Exception:
            pass

    def _refresh_history_sidebar(self) -> None:
        convs = self.brain.conversations()
        self._convs = list(convs)
        try:
            from brain_core import _current_conv_id

            active = _current_conv_id()
        except Exception:
            active = None
        rows = list(reversed(convs))
        if active and not any(c.get("conv") == active for c in convs):
            rows.insert(0, {"conv": active, "count": 0, "last_ts": "", "summary": "new conversation"})
        self._displayed_convs = rows
        lv = self.query_one("#history-list", ListView)
        lv.clear()
        for c in rows:
            label = (c.get("summary") or _short_summary(c.get("question") or "") or "…")
            marker = "● " if c.get("conv") == active else ""
            ts = (c.get("last_ts") or "")[11:16]
            children = [Label(f"{marker}{ts}  {label}", classes="hist-label")]
            if c.get("count"):
                children.append(
                    _DelLabel(lambda cid=c.get("conv"): self._delete_conv_id(cid), classes="hist-del")
                )
            row = ListItem(Horizontal(*children))
            row._conv_id = c.get("conv")
            lv.append(row)

    # ---------- input ----------

    def action_submit_input(self) -> None:
        inp = self.query_one("#input", TextArea)
        text = inp.text.strip()
        if not text:
            return
        # Drag-and-drop: dragging a file onto the terminal pastes its path.
        # If the submitted text is just an existing file path, attach it.
        if "\n" not in text and len(text) < 512:
            from pathlib import Path

            p = Path(text.strip().strip("\"'")).expanduser()
            if p.is_file():
                inp.clear()
                self._append_system(f"[dim]drop detected:[/dim] {p}")
                self._attach_file(p)
                return
        inp.clear()
        if self._pending_confirm:
            kind = self._pending_confirm
            self._pending_confirm = None
            if text.lower() in ("yes", "y", "yeah", "yep", "confirm", "do it", "sure", "ok", "okay", "go"):
                if kind == "heal":
                    self.run_worker(self._do_heal(major=True), group="aux")
                else:
                    self._start_index()
            else:
                self._append_system("[dim]cancelled[/]")
            return
        if self._pending_edit:
            self._pending_edit = False
            n = getattr(self, "_pending_edit_removals", 1)
            for _ in range(n):
                try:
                    self.brain.delete_last_history()
                except Exception:
                    break
            self._ask(text)
            return
        if text.startswith("/"):
            self._run_command(text)
        elif self._is_index_request(text):
            self._append_user(text)
            self._pending_confirm = "index"
            self._append_system(
                "[dim]This will index your library. Confirm? (yes/no)[/]"
            )
        else:
            self._ask(text)
        self._set_suggestions_visible(False)

    @on(TextArea.Changed)
    def _on_input_changed(self) -> None:
        self._refresh_suggestions()

    def _refresh_suggestions(self) -> None:
        try:
            ta = self.query_one("#input", TextArea)
        except Exception:
            return
        line = ta.text.split("\n")[-1]
        if not line.startswith("/") or line in COMMANDS:
            self._set_suggestions_visible(False)
            return
        prefix = line[1:]
        matches = [c for c in COMMANDS if c.startswith("/" + prefix)]
        lv = self.query_one("#suggestions", ListView)
        if not matches:
            self._set_suggestions_visible(False)
            return
        lv.clear()
        for cmd in matches:
            item = ListItem(Label(cmd))
            item._cmd = cmd
            lv.append(item)
        lv.index = 0
        self._set_suggestions_visible(True)

    def _set_suggestions_visible(self, visible: bool) -> None:
        if self._suggestions_visible == visible:
            return
        self._suggestions_visible = visible
        try:
            lv = self.query_one("#suggestions", ListView)
            lv.set_class(visible, "visible")
        except Exception:
            pass

    def _suggestion_move(self, delta: int) -> None:
        if not self._suggestions_visible:
            return
        lv = self.query_one("#suggestions", ListView)
        items = list(lv.children)
        if not items:
            return
        cur = lv.index or 0
        lv.index = (cur + delta) % len(items)

    def _suggestion_accept(self) -> None:
        if not self._suggestions_visible:
            return
        lv = self.query_one("#suggestions", ListView)
        items = list(lv.children)
        idx = lv.index or 0
        if idx >= len(items):
            return
        cmd = getattr(items[idx], "_cmd", "")
        if not cmd:
            return
        try:
            ta = self.query_one("#input", TextArea)
            lines = ta.text.split("\n")
            line = lines[-1]
            parts = line.split(" ", 1)
            new_line = cmd + (" " + parts[1] if len(parts) > 1 else "")
            lines[-1] = new_line
            ta.text = "\n".join(lines)
            try:
                ta.cursor_position = ta.document.end
            except Exception:
                pass
        except Exception:
            pass
        self._set_suggestions_visible(False)
        self.query_one("#input", TextArea).focus()

    @staticmethod
    def _is_index_request(text: str) -> bool:
        return bool(re.search(r"\b(index|reindex|re-index)\b", text, re.I)) and any(
            k in text.lower()
            for k in ("book", "text", "file", "library", "vault", "doc", "everything", "all")
        )

    # ---------- asking ----------

    def _ask(self, question: str) -> None:
        q = self._mount_msg_box(question, kind="user", editable=True)
        self._last_q_widget = q
        self._last_question = question
        self._last_user_message = question
        self._request_queue.append(question)
        self._ensure_queue()

    def _ensure_queue(self) -> None:
        if self._queue_active:
            self._refresh_queue_status()
            return
        self._queue_active = True
        self._queue_gen += 1
        gen = self._queue_gen
        self._set_busy(True, "thinking…")
        self._queue_worker = self.run_worker(self._process_queue(gen), group="ask")

    async def _process_queue(self, gen: int) -> None:
        """Serial request processor: one answer at a time, in order.

        Owns the busy/typing lifecycle for the WHOLE queue, so the widgets are
        mounted and removed exactly once per drain — no duplicate-id races.
        """
        try:
            while self._request_queue:
                question = self._request_queue.pop(0)
                self._refresh_queue_status()
                worker = self.run_worker(self._do_ask(question), group="ask-request")
                self._active_request = worker
                try:
                    await worker.wait()
                except Exception:
                    pass
                self._active_request = None
        finally:
            if gen == self._queue_gen:
                self._queue_active = False
                self._set_busy(False)
                self.brain._progress = None

    def _refresh_queue_status(self) -> None:
        n = len(self._request_queue)
        self._progress_msg = f"{n} queued" if n else ""
        if self._typing_indicator is not None:
            try:
                self._typing_indicator.update(f"answering… ({n} queued)" if n else "·")
            except Exception:
                pass
        if self._busy:
            try:
                self.query_one("#input", TextArea).placeholder = (
                    f"answering… ({n} queued)" if n else "thinking…"
                )
            except Exception:
                pass

    async def _do_ask(self, question: str) -> None:
        acc = ""
        outer = None
        markdown = None
        last_render = 0.0
        _ask_t0 = time.time()
        self.brain._progress = self._on_progress
        self._think_md = None
        self._think_panel = None
        self._think_acc = ""
        self._think_last = 0.0
        self._think_anchor = None
        self._think_collapsed = False
        try:
            # mount an empty answer bubble immediately so the wait is visible
            outer = self._mount_msg_box("…", kind="ai")
            self._think_anchor = outer
            self._last_a_widgets = [outer]
            markdown = getattr(outer, "_bubble", None)
            async for text in self.brain.ask_stream(question):
                acc = text
                if text and self._think_panel is not None and not self._think_collapsed:
                    # The answer has started — tuck the thinking away.
                    try:
                        self._think_panel.collapsed = True
                    except Exception:
                        pass
                    self._think_collapsed = True
                now = time.time()
                if markdown is not None and (not acc or now - last_render >= 0.25):
                    markdown.update(_style_invented(acc) or "…")
                    last_render = now
                    self._scroll_end()
            res = self.brain._last_stream_result or {}
            if res.get("served_local"):
                self._append_system(
                    "[yellow]deepseek unreachable — answered with local qwen[/yellow]"
                )
            self._last_served_info = {
                "model": res.get("served_model") or "",
                "thinking_s": res.get("t_thinking") or 0.0,
                "content_s": res.get("t_content") or 0.0,
                "reasoning_chars": len(res.get("reasoning") or ""),
                "tokens_in": res.get("tokens_in") or 0,
                "tokens_out": res.get("tokens_out") or 0,
                "cost_usd": res.get("cost_usd") or 0.0,
                "route_reason": res.get("route_reason") or "",
                "kind": res.get("kind") or "",
            }
            answer = res.get("answer") or acc or _no_answer_line()
            clean = _clean_markers(answer)
            if markdown is not None and answer:
                markdown.update(_style_invented(answer))
            refs = res.get("refs") or []
            self._last_answer = clean
            if outer is not None:
                outer._msg_text = clean
                outer._msg_box._msg_text = clean
                actions = getattr(outer, "_actions", None)
                for btn in getattr(actions, "children", []) or []:
                    if getattr(btn, "_action", None) == "copy":
                        btn._msg_text = clean
            self._scroll_end()
            reasoning = (res.get("reasoning") or "").strip()
            if reasoning:
                if self._think_panel is not None and self._think_md is not None:
                    disp = self._think_tail()
                    self._think_md.update(disp)
                    self._think_panel.title = f"thinking ({len(self._think_acc):,} chars)"
                else:
                    disp = reasoning[:6000]
                    if len(reasoning) > 6000:
                        disp += "\n\n_…(truncated)_"
                    think = Collapsible(
                        Markdown(disp, classes="msg-sys"),
                        title=f"thinking ({len(reasoning)} chars)",
                        classes="thinking",
                        collapsed=True,
                    )
                    self._chat().mount(think)
                    self._last_a_widgets.append(think)
            self._scroll_end()
            self._mount_elapsed(_ask_t0, outer, self._last_served_info)
            self._refresh_history_sidebar()
        except asyncio.CancelledError:
            stopped = (acc or "…") + "\n\n_[stopped]_"
            if outer is not None and markdown is not None:
                markdown.update(stopped)
            if outer is not None:
                outer._msg_text = (acc or "…") + "\n\n[stopped]"
                outer._msg_box._msg_text = outer._msg_text
            self._mount_elapsed(_ask_t0, outer)
        except Exception as exc:
            if outer is not None and markdown is not None:
                markdown.update(acc or f"…\n\n_[error: {exc}]_")
            self._append_system(f"[red]error:[/red] {exc}")

    def _mount_elapsed(self, t0: float, anchor, info=None) -> None:
        """A small dim stat line under an answer bubble.

        Shows thinking time and total time; the model name is included only
        when the show_model setting is on."""
        try:
            settings = self.brain.get_settings()
            if not settings.get("show_meta", True):
                return
            info = info or {}
            dt = round(time.time() - t0, 1)
            parts = []
            model = info.get("model") or ""
            if model and settings.get("show_model", True):
                parts.append(model)
            think = info.get("thinking_s") or 0.0
            if think > 0:
                parts.append(f"thought {think:.0f}s")
            parts.append(f"took {dt}s")
            label = "· " + " · ".join(parts)
            caption = Static(label, classes="msg-sys")
            if anchor is not None:
                self._chat().mount(caption, after=anchor)
            else:
                self._chat().mount(caption)
            self._scroll_end()
        except Exception:
            pass

    def action_stop_thinking(self) -> None:
        w = self._active_request
        if w is not None and not getattr(w, "is_finished", True):
            from brain_core import _telemetry_log_feedback

            _telemetry_log_feedback("stop", self._last_question or "")
            w.cancel()
            self._append_system("[dim]stopped — queued questions will still run[/dim]")
        elif self._queue_active:
            self._append_system(f"[dim]{len(self._request_queue)} queued — waiting[/dim]")
        else:
            self._append_system("[dim]nothing is running[/dim]")

    def action_escape_handler(self) -> None:
        if self._suggestions_visible:
            self._set_suggestions_visible(False)
        elif self._busy:
            self.action_stop_thinking()
        else:
            self._pending_edit = False
            self._pending_edit_removals = 0
        self.query_one("#input", TextArea).focus()

    def _remove_last_turn(self) -> None:
        if self._last_q_widget is not None:
            try:
                self._last_q_widget.remove()
            except Exception:
                pass
        for w in self._last_a_widgets:
            try:
                w.remove()
            except Exception:
                pass
        self._last_q_widget = None
        self._last_a_widgets = []

    def _cmd_edit(self) -> None:
        if self._busy:
            self.action_stop_thinking()
        if not self._last_question:
            self._append_system("[dim]nothing to edit yet[/]")
            return
        self._remove_last_turn()
        self._pending_edit = True
        self._pending_edit_removals = 1
        inp = self.query_one("#input", TextArea)
        inp.text = self._last_question
        inp.focus()
        self._append_system(
            "[dim]editing your last message — press enter to re-ask[/]"
        )

    def _stop_typing(self) -> None:
        if self._typing_timer is not None:
            self._typing_timer.stop()
            self._typing_timer = None
        if self._typing_indicator is not None:
            try:
                self._typing_indicator.remove()
            except Exception:
                pass
            self._typing_indicator = None
        self._progress_msg = ""

    def _on_progress(self, msg) -> None:
        if isinstance(msg, tuple) and len(msg) == 2 and msg[0] == "think":
            self._on_thinking(msg[1])
            return
        self._progress_msg = msg
        if self._typing_indicator is not None:
            self._typing_indicator.update(msg)

    def _on_thinking(self, text: str) -> None:
        """Stream the reasoning model's thinking live, above the answer bubble."""
        if not text:
            return
        self._think_acc += text
        now = time.time()
        if self._think_panel is None:
            md = Markdown("…", classes="msg-sys")
            panel = Collapsible(md, title="thinking…", classes="thinking", collapsed=False)
            self._think_md = md
            self._think_panel = panel
            anchor = self._think_anchor
            chat = self._chat()
            if anchor is not None:
                try:
                    chat.mount(panel, before=anchor)
                except Exception:
                    chat.mount(panel)
            else:
                chat.mount(panel)
        if self._think_md is not None and now - self._think_last >= 0.25:
            disp = self._think_tail()
            self._think_md.update(disp)
            try:
                self._think_panel.title = f"thinking ({len(self._think_acc):,} chars)"
            except Exception:
                pass
            self._think_last = now

    def _think_tail(self) -> str:
        """The latest thinking window — keeps scrolling instead of freezing
        at the head once the stream outgrows the panel."""
        cap = 12000
        acc = self._think_acc
        if len(acc) <= cap:
            return acc
        return "…(earlier thinking)…\n\n" + acc[-cap:]

    def _set_busy(self, busy: bool, placeholder: str = "") -> None:
        self._busy = busy
        inp = self.query_one("#input", TextArea)
        if busy:
            inp.placeholder = placeholder
            self._typing_dot_idx = 0
            self._progress_msg = ""
            # Idempotent: sweep any leftover indicator so a second mount can
            # never raise DuplicateIds, whatever race left it behind.
            for w in list(self._chat().query("#typing")):
                try:
                    w.remove()
                except Exception:
                    pass
            self._stop_typing()
            self._typing_indicator = Static("·", id="typing")
            self._chat().mount(self._typing_indicator)
            self._scroll_end()
            self._typing_timer = self.set_interval(0.35, self._tick_typing)
        else:
            self._stop_typing()
            inp.placeholder = "ask mentat…  (type /help)"

    def _tick_typing(self) -> None:
        if self._typing_indicator is not None:
            if self._progress_msg:
                return  # progress text shown instead of the dots
            self._typing_dot_idx = (self._typing_dot_idx + 1) % len(self._typing_dots)
            self._typing_indicator.update(self._typing_dots[self._typing_dot_idx])

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
            "settings": self._open_settings,
            "model": lambda: self._cmd_model(arg),
            "lens": lambda: self._cmd_lens(arg),
            "voice": lambda: self._cmd_voice(arg),
            "health": lambda: self._cmd_health(),
            "refresh": lambda: self._cmd_refresh(),
            "remember": lambda: self._cmd_remember(arg),
            "search": lambda: self._cmd_search(arg),
            "find": lambda: self._cmd_find(arg),
            "graph": lambda: self._cmd_graph(arg),
            "verify": self._cmd_verify,
            "offline": lambda: self._cmd_offline(arg),
            "stats": self._cmd_stats,
            "heal": self._cmd_heal,
            "edit": lambda: self._cmd_edit(),
            "forget": lambda: self._cmd_forget(arg),
            "index": lambda: self._cmd_index(),
            "history": lambda: self._cmd_history(),
            "copy": self.action_copy_last,
            "copy-user": self.action_copy_user,
            "attach": lambda: self._cmd_attach(arg),
            "docs": lambda: self._cmd_docs(),
            "detach": lambda: self._cmd_detach(arg),
            "write": lambda: self._cmd_write(arg),
            "served": lambda: self._cmd_served(),
            "reload": lambda: self._cmd_reload(),
            "inventory": lambda: self._cmd_inventory(),
            "freq": lambda: self._cmd_freq(arg),
        }
        fn = handlers.get(cmd)
        if fn is None:
            self._append_system(f"[yellow]unknown command:[/yellow] /{cmd}  (try /help)")
            return
        self._append_system(f"/{cmd} {arg}".strip())
        fn()

    def _cmd_inventory(self) -> None:
        try:
            data = _library_profiles()
        except Exception as exc:
            self._append_system(f"[red]inventory failed: {exc}[/red]")
            return
        rows = data.get("works") or []
        if not rows:
            self._append_system("[yellow]nothing indexed yet — /index first[/yellow]")
            return
        t = data.get("totals") or {}
        lines = ["[b]library inventory[/b]", ""]
        for w in rows[:22]:
            lines.append(
                f"  {w['work'][:58]:60} chunks {w['chunks']:>6,} · "
                f"chapters {w['chapters']:>4,} · words {w['words']:>9,}"
            )
        if len(rows) > 22:
            lines.append(f"  … and {len(rows) - 22} more works")
        lines.append("")
        lines.append(
            f"[b]totals:[/b] {len(rows)} works · {t.get('chunks', 0):,} chunks · "
            f"{t.get('chapters', 0):,} story chapters · "
            f"{t.get('apparatus', 0):,} apparatus · {t.get('words', 0):,} words"
        )
        self._append_system("\n".join(lines))

    def _cmd_freq(self, arg: str) -> None:
        if not arg:
            self._append_system("[yellow]usage: /freq <word or phrase>[/yellow]")
            return
        try:
            rows = _term_frequency(arg)
        except Exception as exc:
            self._append_system(f"[red]freq failed: {exc}[/red]")
            return
        hits = [r for r in rows if r["story"] or r["apparatus"]]
        if not hits:
            self._append_system(f"[yellow]no occurrences of {arg!r} in the library[/yellow]")
            return
        lines = [f"[b]frequency:[/b] {arg}", ""]
        total = 0
        for r in hits[:18]:
            lines.append(
                f"  {r['work'][:56]:58} story {r['story']:>6,}"
                + (f"  (+{r['apparatus']:,} apparatus)" if r["apparatus"] else "")
            )
            total += r["story"]
        if len(hits) > 18:
            lines.append(f"  … and {len(hits) - 18} more works")
        lines.append("")
        lines.append(f"[b]{total:,}[/b] occurrences in story text")
        self._append_system("\n".join(lines))

    def _cmd_status(self) -> None:
        try:
            new, changed, removed, current = self.brain._scan_changes()
        except Exception as exc:
            self._append_system(f"[red]{exc}[/red]")
            return
        manifest = len(_load_manifest())
        pending = len(new) + len(changed)
        self._status_pending = pending
        self._status_docs = manifest
        self._update_status()
        self._append_system(
            f"indexed documents: [b]{manifest}[/b] · pending: [b]{pending}[/b]"
            f"\nvault: {KNOWLEDGE_ROOT}"
        )

    def _cmd_settings(self) -> None:
        s = self.brain.get_settings()
        lines = "\n".join(f"  [b]{k}[/b]: {v}" for k, v in s.items())
        self._append_system(f"settings:\n{lines}")

    def _open_settings(self) -> None:
        self.push_screen(SettingsScreen())

    def _cmd_served(self) -> None:
        """Reveal which model actually served the last answer, with timings + cost."""
        info = getattr(self, "_last_served_info", None) or {}
        if not info.get("model"):
            self._append_system("[dim]no answer yet — ask something first[/dim]")
            return
        cost = info.get("cost_usd") or 0.0
        tokens = (info.get("tokens_in") or 0, info.get("tokens_out") or 0)
        reason = info.get("route_reason") or ""
        line = (
            f"last answer served by [b]{info['model']}[/b] — "
            f"thinking {info.get('thinking_s', 0):.1f}s · writing "
            f"{info.get('content_s', 0):.1f}s · {info.get('reasoning_chars', 0):,} "
            f"reasoning chars"
        )
        if tokens[0] or tokens[1]:
            line += f" · {tokens[0]:,} in / {tokens[1]:,} out"
        if cost:
            line += f" · ~${cost:.4f}"
        if reason:
            line += f"\n[dim]route: {reason}[/dim]"
        self._append_system(line)

    def _cmd_reload(self) -> None:
        """Restart the app in place so new code/features apply instantly."""
        import os as _os

        try:
            self.brain.set_setting("auto_reload", self.brain.get_settings().get("auto_reload", False))
        except Exception:
            pass
        self._append_system("[yellow]reloading the app — back in a second[/yellow]")
        self.refresh(repaint=True)
        _os.execv(sys.executable, [sys.executable] + sys.argv)

    def _code_signature(self):
        try:
            from brain_core import PROJECT_ROOT

            return {
                p.name: p.stat().st_mtime_ns
                for p in PROJECT_ROOT.iterdir()
                if p.suffix == ".py"
            }
        except Exception:
            return None

    def _current_conv(self) -> str:
        from brain_core import _current_conv_id

        return _current_conv_id() or ""

    def _attach_file(self, path) -> None:
        from brain_core import _attach_conv_doc, _current_conv_id, extract_text

        try:
            text = extract_text(path)
        except Exception as exc:
            self._append_system(f"[red]could not read {path}: {exc}[/red]")
            return
        name = _attach_conv_doc(_current_conv_id() or "", path.name, text)
        self._append_system(
            f"[green]📎 attached[/green] [b]{name}[/b] to this conversation "
            f"({len(text):,} chars) — I'll consult it when you ask about it."
        )

    def _cmd_attach(self, arg: str) -> None:
        from pathlib import Path

        from brain_core import _current_conv_id

        if arg.strip():
            p = Path(arg.strip().strip("\"'")).expanduser()
            if not p.is_file():
                self._append_system(f"[red]no such file:[/red] {arg}")
                return
            self._attach_file(p)
            return
        try:
            text = subprocess.run(
                ["pbpaste"], capture_output=True, text=True, check=True
            ).stdout
        except Exception:
            text = ""
        if not text.strip():
            self._append_system(
                "[dim]clipboard is empty — use /attach <file path>, or drag a file "
                "onto the terminal and press enter[/dim]"
            )
            return
        from brain_core import _attach_conv_doc

        name = _attach_conv_doc(
            _current_conv_id() or "",
            f"clipboard-{time.strftime('%H%M%S')}.txt",
            text,
        )
        self._append_system(
            f"[green]📎 attached[/green] [b]{name}[/b] from clipboard ({len(text):,} chars)."
        )

    def _cmd_docs(self) -> None:
        from brain_core import _list_conv_docs

        docs = _list_conv_docs(self._current_conv())
        if not docs:
            self._append_system("[dim]no drafts attached to this conversation.[/dim]")
            return
        lines = [f"  [b]{i+1}.[/b] {d['name']} ({d['chars']:,} chars)" for i, d in enumerate(docs)]
        self._append_system("attached drafts:\n" + "\n".join(lines))

    def _cmd_detach(self, arg: str) -> None:
        from brain_core import _detach_conv_doc, _list_conv_docs

        docs = _list_conv_docs(self._current_conv())
        if not docs:
            self._append_system("[dim]nothing attached.[/dim]")
            return
        name = None
        if arg.strip().isdigit():
            i = int(arg.strip()) - 1
            if 0 <= i < len(docs):
                name = docs[i]["name"]
        else:
            name = arg.strip()
        if not name:
            self._append_system("usage: /detach <n>  (or /detach <filename>)")
            return
        if _detach_conv_doc(self._current_conv(), name):
            self._append_system(f"[dim]detached:[/dim] {name}")
        else:
            self._append_system(f"[red]no draft named[/red] {name}")

    def _cmd_write(self, arg: str) -> None:
        from pathlib import Path

        if not (self._last_answer and str(self._last_answer).strip()):
            self._append_system("[dim]no answer to write yet[/dim]")
            return
        if not arg.strip():
            out_dir = Path.home() / "Documents" / "second-brain-drafts"
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / f"draft-{time.strftime('%Y%m%d-%H%M%S')}.md"
        else:
            path = Path(arg.strip().strip("\"'")).expanduser()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(self._last_answer))
        except Exception as exc:
            self._append_system(f"[red]write failed: {exc}[/red]")
            return
        self._append_system(f"[green]✎ saved last answer to[/green] {path}")

    def _cmd_model(self, arg: str) -> None:
        if not arg:
            s = self.brain.get_settings()
            self._append_system(f"model: [b]{model_label(s.get('model') or '')}[/b]")
            self._append_system(
                "options: deepseek-flash (v4.1) · deepseek-think (pro) · qwen (local) · qwen-deep (local reasoning)"
            )
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

    def _cmd_voice(self, arg: str) -> None:
        arg = (arg or "").strip().lower()
        if not arg:
            s = self.brain.get_settings()
            self._append_system(
                f"voice: [b]{s.get('voice', 'default')}[/b]  "
                f"options: {' · '.join(VOICE_PRESETS)}"
            )
            return
        try:
            self.brain.set_setting("voice", arg)
            self._append_system(f"[green]voice set to {arg}[/green]")
            self._refresh_status()
        except Exception as exc:
            self._append_system(f"[red]error:[/red] {exc}")

    def _cmd_health(self) -> None:
        self.run_worker(self._do_health(), group="aux")

    def _cmd_refresh(self) -> None:
        """Re-read the library from disk (picks up external changes)."""
        try:
            from brain_core import _refresh_caches

            _refresh_caches()
            self._refresh_status()
            self._refresh_history_sidebar()
            self._render_header()
            self._append_system("[green]refreshed — library re-read from disk[/green]")
        except Exception as exc:
            self._append_system(f"[red]error:[/red] {exc}")

    async def _do_health(self) -> None:
        try:
            results = await self.brain.health()
            fails = [n for n, ok, _ in results if not ok]
            if fails:
                self._append_system("[red]health failures:[/red] " + ", ".join(fails))
            else:
                self._append_system(f"[green]health: all {len(results)} checks ok[/green]")
        except Exception as exc:
            self._append_system(f"[red]error:[/red] {exc}")

    def _cmd_remember(self, arg: str) -> None:
        if not arg:
            self._append_system("usage: /remember <fact>  [--topic name]")
            return
        topic = "default"
        if "--topic" in arg:
            arg, _, topic = arg.partition("--topic")
            topic = topic.strip() or "default"
        self.run_worker(self._do_remember(arg.strip(), topic), group="aux")

    async def _do_remember(self, text: str, topic: str) -> None:
        try:
            await self.brain.remember(text, topic=topic)
            self._append_system(f"[green]remembered[/green] → {topic}")
            self._refresh_history_sidebar()
        except Exception as exc:
            self._append_system(f"[red]error:[/red] {exc}")

    def _cmd_search(self, arg: str) -> None:
        if not arg:
            self._append_system("usage: /search <phrase>  (exact full-text search across all books)")
            return
        self.run_worker(self._do_search(arg), group="aux")

    def _cmd_find(self, arg: str) -> None:
        if not arg:
            self._append_system(
                "usage: /find <half-remembered words>  "
                "(fuzzy quote hunt across all books)"
            )
            return
        self._ask(f"find: {arg}")

    def _cmd_stats(self) -> None:
        """Compact research diary: questions, spend, kinds, statuses, signals."""
        try:
            from brain_core import _telemetry_conn, _telemetry_init
            import time as _t

            _telemetry_init()
            conn = _telemetry_conn()
            n_asks = conn.execute("SELECT count(*) FROM asks").fetchone()[0]
            day = _t.strftime("%Y-%m-%d")
            today = conn.execute(
                "SELECT coalesce(round(sum(cost_usd), 4), 0) FROM asks "
                "WHERE substr(ts, 1, 10) = ?", (day,),
            ).fetchone()[0]
            total = conn.execute(
                "SELECT coalesce(round(sum(cost_usd), 4), 0) FROM asks"
            ).fetchone()[0]
            kinds = conn.execute(
                "SELECT kind, count(*) FROM asks WHERE kind IS NOT NULL AND kind != '' "
                "GROUP BY kind ORDER BY 2 DESC LIMIT 6"
            ).fetchall()
            statuses = conn.execute(
                "SELECT status, count(*) FROM asks GROUP BY status"
            ).fetchall()
            signals = conn.execute(
                "SELECT kind, count(*) FROM feedback GROUP BY kind ORDER BY 2 DESC LIMIT 10"
            ).fetchall()
            conn.close()
            lines = [
                f"[b]diary[/b] — {n_asks} questions · spend today ${today:.4f} · all-time ${total:.4f}",
                "kinds: " + (", ".join(f"{k}:{c}" for k, c in kinds) or "—"),
                "statuses: " + ", ".join(f"{s}:{c}" for s, c in statuses),
                "signals: " + ", ".join(f"{k}:{c}" for k, c in signals),
            ]
            self._append_system("\n".join(lines))
        except Exception as exc:
            self._append_system(f"[red]stats failed: {exc}[/red]")

    def _cmd_heal(self) -> None:
        self.run_worker(self._do_heal(major=False), group="aux")

    async def _do_heal(self, major: bool) -> None:
        try:
            from brain_core import self_heal_run

            result = await self_heal_run(allow_major=major)
        except Exception as exc:
            self._append_system(f"[red]heal failed: {exc}[/red]")
            return
        for q in result.get("quips") or []:
            self._append_system(f"[yellow]{q}[/yellow]")
        fixed = result.get("fixed") or []
        pending = result.get("pending") or []
        failed = result.get("failed") or []
        notes = result.get("notes") or []
        if not (fixed or pending or failed or notes):
            self._append_system("[green]all systems whole — nothing to heal[/green]")
            return
        for f in fixed:
            self._append_system(f"[green]fixed:[/green] {f['issue']} — {f['detail']}")
        for f in failed:
            self._append_system(f"[red]could not fix:[/red] {f['issue']} — {f['detail']}")
        for n in notes:
            self._append_system(f"[dim]note:[/dim] {n['issue']} — {n['detail']}")
        for p in pending:
            self._append_system(f"[yellow]needs your call:[/yellow] {p['issue']} — {p['detail']}")
        if pending and not major and not self._busy and not self._queue_active:
            self._pending_confirm = "heal"
            self._append_system("[yellow]A major repair is proposed above. Approve? (yes/no)[/yellow]")

    async def _auto_heal(self) -> None:
        try:
            from brain_core import self_heal_run

            result = await self_heal_run(allow_major=False)
        except Exception:
            return
        finally:
            self._heal_running = False
        if not result.get("issues"):
            return
        for q in result.get("quips") or []:
            self._append_system(f"[yellow]{q}[/yellow]")
        for f in result.get("fixed") or []:
            self._append_system(f"[green]fixed:[/green] {f['issue']} — {f['detail']}")
        for n in result.get("notes") or []:
            self._append_system(f"[dim]note:[/dim] {n['issue']} — {n['detail']}")
        pending = result.get("pending") or []
        if (
            pending
            and self.brain.get_settings().get("self_heal") == "full"
            and not self._busy
            and not self._queue_active
        ):
            self._pending_confirm = "heal"
            self._append_system("[yellow]A major repair is proposed. Approve? (yes/no)[/yellow]")

    def _cmd_offline(self, arg: str) -> None:
        """Toggle local-only mode: no API, local qwen for everything."""
        current = bool(self.brain.get_settings().get("offline"))
        if arg:
            new = str(arg).strip().lower() in ("on", "true", "1", "yes")
        else:
            new = not current
        self.brain.set_setting("offline", new)
        if new:
            self._append_system(
                "[b]offline mode on[/b] — search stays local; answers use local qwen."
            )
        else:
            self._append_system(
                "[b]offline mode off[/b] — API tiers available again."
            )
        self._net_down = None
        self._auto_offline_applied = False
        self._refresh_status()

    def _cmd_graph(self, arg: str) -> None:
        if not arg:
            self._append_system("usage: /graph <name>  (what co-occurs with a name)")
            return
        try:
            from brain_core import _graph_related

            info = _graph_related(arg)
        except Exception as exc:
            self._append_system(f"[red]graph unavailable: {exc}[/red]")
            return
        if not info["count"]:
            self._append_system(
                f"[yellow]'{arg}' is not in the entity graph[/yellow] "
                "(build with `mentat graph --build`)"
            )
            return
        lines = [f"[b]{info['entity']}[/b] — {info['count']} chunks"]
        for name, cnt in info["related"]:
            lines.append(f"  ~ {name} ({cnt})")
        for book, cnt in info["books"][:5]:
            lines.append(f"  · {book} ({cnt})")
        self._append_system("\n".join(lines))

    def _cmd_verify(self) -> None:
        self.run_worker(self._do_verify(), group="aux")

    async def _do_verify(self) -> None:
        try:
            from verify import run_suite

            results = await asyncio.to_thread(run_suite, True, False)
        except Exception as exc:
            self._append_system(f"[red]verify failed to run: {exc}[/red]")
            return
        passed = sum(1 for r in results if r["status"] == "PASS")
        lines = [f"[b]verify (quick): {passed}/{len(results)} passed[/b]"]
        for r in results:
            mark = "PASS" if r["status"] == "PASS" else "FAIL"
            lines.append(f"  [{mark}] {r['check']}: {r['detail'][:80]}")
        self._append_system("\n".join(lines))

    async def _do_search(self, phrase: str) -> None:
        try:
            results = await asyncio.to_thread(self.brain.search, phrase)
            if not results:
                self._append_system(
                    f"no exact matches for [b]{phrase}[/b] — try fewer words or a different phrase."
                )
            else:
                self._append_system(f"[b]{len(results)} match(es)[/b] for [b]{phrase}[/b]:")
                for r in results[:20]:
                    self._append_user(f"{r['source']}", editable=False)
                    self._append_ai(f"> {r['excerpt']}")
        except Exception as exc:
            self._append_system(f"[red]error:[/red] {exc}")

    def _start_index(self) -> None:
        """Run indexing as a background task so chat keeps working."""
        if self._index_worker is not None and not self._index_worker.is_finished:
            self._append_system("[dim]an index is already running in the background[/]")
            return
        self._append_system("[dim]indexing started in the background — keep chatting[/]")
        self._index_worker = self.run_worker(self._do_index(), group="index")

    def _cmd_index(self) -> None:
        self._start_index()

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
            self._index_worker = None
            self._refresh_status()

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

    def _clear_chat(self, start_new: bool = True) -> None:
        if self._active_request is not None and not getattr(self._active_request, "is_finished", True):
            self._active_request.cancel()
        if self._queue_worker is not None and not getattr(self._queue_worker, "is_finished", True):
            self._queue_worker.cancel()
        self._request_queue.clear()
        self._queue_active = False
        self._queue_gen += 1
        self._set_busy(False)
        self._chat().remove_children()
        if start_new:
            try:
                self.brain.new_conversation()
                self._refresh_history_sidebar()
            except Exception:
                pass
        self._append_system(
            "[b]what wisdom do you seek…?[/b]  [dim]/help for commands[/dim]"
        )

    # ---------- actions / palette ----------

    def action_clear_chat(self) -> None:
        self._clear_chat()

    def action_load_history(self) -> None:
        self._refresh_history_sidebar()
        self._append_system("history refreshed (sidebar).")

    def action_focus_input(self) -> None:
        self.query_one("#input", TextArea).focus()

    def action_paste_clipboard(self) -> None:
        try:
            text = subprocess.run(
                ["pbpaste"], capture_output=True, text=True, check=True
            ).stdout
        except Exception:
            return
        if text:
            self.query_one("#input", TextArea).insert(text)

    def action_copy_last(self) -> None:
        if not self._last_answer:
            self._append_system("[dim]no answer to copy yet[/]")
            return
        try:
            subprocess.run(
                ["pbcopy"], input=self._last_answer.encode("utf-8"), check=True
            )
            self._append_system("[dim]last answer copied to clipboard[/]")
        except Exception as exc:
            self._append_system(f"[red]copy failed: {exc}[/red]")

    def action_copy_user(self) -> None:
        if not self._last_user_message:
            self._append_system("[dim]no message of yours to copy yet[/]")
            return
        try:
            subprocess.run(
                ["pbcopy"], input=self._last_user_message.encode("utf-8"), check=True
            )
            self._append_system("[dim]your last message copied to clipboard[/]")
        except Exception as exc:
            self._append_system(f"[red]copy failed: {exc}[/red]")

    def action_copy(self) -> None:
        """⌘C: copy selected text if any, otherwise the last answer."""
        selected = None
        try:
            selected = self.screen.get_selected_text()
        except Exception:
            selected = None
        if selected:
            self.copy_to_clipboard(selected)
        else:
            self.action_copy_last()

    def copy_to_clipboard(self, text: str) -> None:
        """Make ⌘C (Textual selection copy) write to the real macOS clipboard."""
        self._clipboard = text
        try:
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
        except Exception:
            super().copy_to_clipboard(text)

    @property
    def clipboard(self) -> str:
        """System clipboard: in-app copy first, otherwise read from macOS pbpaste."""
        if self._clipboard:
            return self._clipboard
        try:
            return subprocess.run(
                ["pbpaste"], capture_output=True, text=True, check=True
            ).stdout
        except Exception:
            return ""

    @on(ListView.Selected)
    def _on_history_selected(self, event: ListView.Selected) -> None:
        # Swallow only the startup auto-highlight; real clicks always work.
        if not getattr(self, "_hist_ready", False):
            return
        conv_id = getattr(event.item, "_conv_id", None)
        if not conv_id:
            return
        if self._busy:
            self.action_stop_thinking()
        self.brain.open_conversation(conv_id)
        entries = self.brain.history(limit=500)
        self._clear_chat(start_new=False)
        shown = entries[-12:]
        if len(shown) < len(entries):
            self._append_system(f"[dim]…{len(entries) - len(shown)} earlier turns hidden[/dim]")
        for e in shown:
            self._append_user(e.get("question", "…"))
            self._append_ai(e.get("answer", "…"), e.get("contexts", ""))
        self._refresh_history_sidebar()
        self.query_one("#input", TextArea).focus()

    @on(Button.Pressed)
    def _on_button(self, event: Button.Pressed) -> None:
        btn = event.button
        bid = btn.id or ""
        if bid == "btn-settings":
            self._open_settings()
            return
        if "mini-btn" in btn.classes:
            action = getattr(btn, "_action", "")
            if action == "copy":
                self._copy_message(btn)
            elif action == "edit":
                self._edit_message(btn)
            return
        if bid == "btn-new":
            self._clear_chat()
            self.query_one("#input", TextArea).focus()

    def _delete_conv_id(self, conv_id: str) -> None:
        if not conv_id:
            return
        rows = list(self._convs)
        row = next((r for r in rows if r.get("conv") == conv_id), None)
        removed = self.brain.delete_conversation(conv_id)
        q = " ".join(
            ((row or {}).get("summary") or (row or {}).get("question") or "…").split()
        )[:40]
        self._append_system(f"[dim]forgot conversation:[/] {q} ({removed} turns)")
        self._refresh_history_sidebar()

    def _cmd_forget(self, arg: str) -> None:
        try:
            n = int(arg.strip())
        except ValueError:
            self._append_system("usage: /forget <n>  (1 = most recent conversation)")
            return
        convs = list(reversed(self._convs))
        if n < 1 or n > len(convs):
            self._append_system(f"only {len(convs)} conversation(s) saved.")
            return
        conv_id = convs[n - 1].get("conv")
        self.brain.delete_conversation(conv_id)
        q = " ".join((convs[n - 1].get("summary") or convs[n - 1].get("question") or "…").split())[:40]
        self._append_system(f"[dim]forgot conversation:[/] {q}")
        self._refresh_history_sidebar()

    def action_search_commands(self) -> None:
        self.search_commands(
            [
                SimpleCommand("New chat (clear view)", self._clear_chat, "Clear the current conversation view"),
                SimpleCommand("Stop current answer", self.action_stop_thinking, "Stop the in-progress answer (escape)"),
                SimpleCommand("Ask brain to index", self._cmd_index, "Index new/changed files in the background"),
                SimpleCommand("Index status", self._cmd_status, "What is indexed, what is pending"),
                SimpleCommand("Show settings", self._cmd_settings, "Current settings"),
                SimpleCommand("Switch model", lambda: self._cmd_model(""), "Show current answer model"),
                SimpleCommand("Copy last answer", self.action_copy_last, "Copy the last answer (/copy)"),
                SimpleCommand("Copy your last message", self.action_copy_user, "Copy your last sent message (/copy-user)"),
                SimpleCommand("Search the books", lambda: self._cmd_search(""), "Exact full-text search (/search <phrase>)"),
                SimpleCommand("Find a half-remembered quote", lambda: self._cmd_find(""), "Fuzzy quote hunt (/find <words>)"),
                SimpleCommand("Entity graph", lambda: self._cmd_graph(""), "What co-occurs with a name (/graph <name>)"),
                SimpleCommand("Run verification", self._cmd_verify, "Quick verification suite (/verify)"),
                SimpleCommand("Toggle offline mode", lambda: self._cmd_offline(""), "Local qwen only, no API (/offline)"),
                SimpleCommand("Research diary", self._cmd_stats, "Questions, spend, kinds, signals (/stats)"),
                SimpleCommand("Self-repair", self._cmd_heal, "Detect + fix broken subsystems (/heal)"),
                SimpleCommand("Edit last message", self._cmd_edit, "Edit your last sent message and re-ask (/edit)"),
                SimpleCommand("Forget a conversation", lambda: self._cmd_forget(""), "Delete a past conversation (/forget <n>)"),
                SimpleCommand("Remember a fact", lambda: self._cmd_remember(""), "Store a permanent fact"),
                SimpleCommand("Quit", self.exit, "Exit the app"),
            ]
        )


HELP_TEXT = """[b]commands[/b]
  <just type>              just ask — answers come from your library, books first
  /search <phrase>         exact full-text search across all books (command+F)
  /find <half-remembered>  hunt a half-remembered quote (fuzzy + exact, quotes back)
  /graph <name>           what co-occurs with a name across the library
  /verify                 run the quick verification suite (results in the diary)
  /offline [on|off]       toggle offline mode (local qwen only, no API)
  /stats                  the research diary (questions, spend, kinds, signals)
  /heal                   run self-repair (detect + fix, quips included)
  /edit                    edit your last sent message, then enter to re-ask
  /index                   start indexing in the background (chat keeps working)
  /forget <n>              delete conversation #n (1 = most recent)
  /status                  what is indexed / pending
  /settings                open the settings page (also the ⚙ button, bottom-left)
  /model <name>            switch answer model (deepseek-flash · deepseek-think · qwen · qwen-deep)
  /lens <name>             set a lens (from vault/lenses/); /lens --clear to clear
  /voice <name>           switch writing voice (default · dune · prophet)
  /health                 run library health checks
  /refresh                re-read the library from disk (pick up external changes)
  /attach <file>          attach a draft to this conversation (or drag a file onto the terminal)
  /docs                   list the drafts attached to this conversation
  /detach <n>             remove an attached draft
  /write <path>           save the last answer to a file
  /served                 show which model served the last answer + timings
  /reload                 restart the app in place (apply new code/features)
  /remember <fact>         permanently remember a fact [--topic name]
  /copy                    copy the last answer to the clipboard
  /copy-user               copy your last sent message to the clipboard
  /history                 recent questions
  /inventory               what's in the index — chunks, chapters, words per book
  /freq <word|phrase>      exact occurrence count per book
  /clear                   new chat
  /quit                    exit

[b]tip[/b]  click ✕ in the sidebar to delete a conversation. Type / then tab/arrows to autocomplete.
          every message has [b]copy[/b] / [b]edit[/b] buttons underneath it — click instead of shortcuts.
          📎 attaches a working draft to this conversation (drag a file onto the terminal and press enter).

[b]keys[/b]  ctrl+shift+C copy (selection, else last answer) · ctrl+shift+V paste
          ⌘C / ⌘V also work when the terminal passes them through
          enter send · shift+enter = new line in the input
          ctrl+y copy last answer · ctrl+shift+y copy your message · escape stop / focus
          ctrl+n new chat · ctrl+q quit"""


COMMANDS = [
    "/help",
    "/ask",
    "/search",
    "/find",
    "/graph",
    "/verify",
    "/offline",
    "/stats",
    "/heal",
    "/edit",
    "/index",
    "/forget",
    "/status",
    "/settings",
    "/model",
    "/lens",
    "/voice",
    "/health",
    "/refresh",
    "/attach",
    "/docs",
    "/detach",
    "/write",
    "/served",
    "/reload",
    "/remember",
    "/copy",
    "/copy-user",
    "/history",
    "/inventory",
    "/freq",
    "/clear",
    "/quit",
]


def main() -> None:
    from brain_core import _acquire_app_lock, _app_lock_holder_pid

    lock = _acquire_app_lock()
    if lock is None:
        pid = _app_lock_holder_pid()
        where = f" (pid {pid})" if pid else ""
        print(
            f"another instance of Mentat is already running{where} — "
            "close it, or run `mentat kill` to stop it, then try again."
        )
        sys.exit(1)
    global _APP_LOCK
    _APP_LOCK = lock
    MentatApp().run()


_APP_LOCK = None


if __name__ == "__main__":
    main()
