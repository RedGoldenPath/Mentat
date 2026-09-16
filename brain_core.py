import asyncio
import difflib
import fcntl
import hashlib
import html
import json
import logging
import os
import random
import re
import shutil
import sqlite3
import sys
import threading
import time
import unicodedata
import uuid
from contextlib import contextmanager
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent
STORAGE_DIR = PROJECT_ROOT / "storage"
MANIFEST_PATH = STORAGE_DIR / "manifest.json"
HISTORY_PATH = STORAGE_DIR / "history.json"
SETTINGS_PATH = STORAGE_DIR / "settings.json"

# Bump on every storage-shape change. Data written by a NEWER build makes
# older processes refuse to mutate (read-only degrade) instead of corrupting.
CODE_VERSION = 4
STORAGE_STALE_MSG = (
    "the library storage was upgraded by a newer build — restart the app "
    "(or run `brain audit`) before continuing."
)
APP_DIR_NAME = "app"


def _resolve_knowledge_root():
    """Mentat's vault: MENTAT_ROOT, legacy SECONDBRAIN_ROOT, then defaults.

    Prefers ~/Everything/mentat; if only the pre-rename folder exists it is
    used, so an un-migrated vault keeps working.
    """
    for var in ("MENTAT_ROOT", "SECONDBRAIN_ROOT"):
        raw = os.getenv(var)
        if raw:
            return Path(raw).expanduser()
    default = Path.home() / "Everything" / "mentat"
    legacy = Path.home() / "Everything" / "second brain"
    if not default.exists() and legacy.exists():
        return legacy
    return default


KNOWLEDGE_ROOT = _resolve_knowledge_root()
TEXT_CACHE_DIR = KNOWLEDGE_ROOT / ".text"

AUTO_INDEX_MAX_FILES = int(os.getenv("AUTO_INDEX_MAX_FILES", "8"))
AUTO_INDEX_MAX_BYTES = int(os.getenv("AUTO_INDEX_MAX_BYTES", str(2 * 1024 * 1024)))


def _load_dotenv():
    """Load app/.env so the API key works from ANY terminal (no exported env needed)."""
    try:
        env_path = PROJECT_ROOT / ".env"
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if not key or key in os.environ:
                continue
            os.environ[key] = value.strip().strip('"').strip("'")
    except Exception:
        pass


_load_dotenv()

os.environ.setdefault("CHUNK_F_SIZE", "1200")
os.environ.setdefault("CHUNK_F_OVERLAP_SIZE", "200")

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_LLM_MODEL = os.getenv("OLLAMA_LLM_MODEL", "qwen3.8:27b")
OLLAMA_DEEP_MODEL = os.getenv("OLLAMA_DEEP_MODEL", "qwen3:30b-a3b")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
EMBED_DIM = int(os.getenv("EMBED_DIM", "768"))

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_TIMEOUT = int(os.getenv("DEEPSEEK_TIMEOUT", "600"))

CHUNK_TOKEN_SIZE = int(os.getenv("CHUNK_TOKEN_SIZE", "2000"))
CHUNK_OVERLAP_TOKEN_SIZE = int(os.getenv("CHUNK_OVERLAP_TOKEN_SIZE", "200"))

SKIP_SUFFIXES = {".ds_store", ".ini", ".cfg", ".json", ".db", ".sqlite", ".sqlite3", ".parquet", ".txt~"}

SETTINGS_DEFAULTS = {
    "thinking": "false",
    "history_turns": 6,
    "mode": "naive",
    "model": "deepseek-flash",
    "temperature": None,
    "top_k": 40,
    "chunk_top_k": 6,
    "sweep_depth": 6,
    "lens": "",
    "routing": "hybrid",
    "routing_threshold": 0.45,
    "offline": False,
    "search_depth": "auto",
    "voice": "default",
    "show_meta": True,
    "show_model": True,
    "auto_reload": False,
    "agent_rounds": 0,
    "planner_model": "",
    "synth_model": "",
    "long_context_model": "deepseek-v4-pro",
    "auto_offline": False,
    "daily_budget": 0.0,
    "self_heal": "remediate",
    "hunt_limit": 36,
    "hunt_cache_ttl": 300,
    "spans_enabled": True,
    "coverage_notes": True,
    "auto_attribution": True,
    "filter_references": True,
    "learning_from_feedback": True,
}

# Sections + plain-English help for the settings menus (CLI + TUI debug menu).
SETTINGS_SPEC = [
    {"key": "model", "section": "Answering", "help": "which engine writes the answers"},
    {"key": "thinking", "section": "Answering", "help": "reasoning depth (local qwen + routing)"},
    {"key": "voice", "section": "Answering", "help": "writing voice preset"},
    {"key": "mode", "section": "Answering", "help": "legacy label from the old RAG modes — does NOT affect answers"},
    {"key": "routing", "section": "Answering", "help": "heuristic/hybrid model routing"},
    {"key": "routing_threshold", "section": "Answering", "help": "score cutoff for routing to the deep model"},
    {"key": "offline", "section": "Answering", "help": "true = local qwen only, no API"},
    {"key": "auto_offline", "section": "Answering", "help": "auto-flip to offline when the API is unreachable"},
    {"key": "daily_budget", "section": "Answering", "help": "USD/day cap; heavy answers demote to flash after it's spent (0 = off)"},
    {"key": "self_heal", "section": "Answering", "help": "self-repair level: off / detect / remediate / full (full = code proposals with gates)"},
    {"key": "temperature", "section": "Answering", "help": "answer creativity (blank = model default)"},
    {"key": "history_turns", "section": "Context", "help": "how many prior turns to feed back (0 = off)"},
    {"key": "lens", "section": "Context", "help": "persistent framing injected into every answer"},
    {"key": "search_depth", "section": "Retrieval", "help": "auto / always (agent) / off (simple)"},
    {"key": "top_k", "section": "Retrieval", "help": "retrieval width"},
    {"key": "chunk_top_k", "section": "Retrieval", "help": "chunks pulled per search"},
    {"key": "sweep_depth", "section": "Retrieval", "help": "passages per book during a sweep"},
    {"key": "agent_rounds", "section": "Retrieval", "help": "planner rounds (0 = automatic)"},
    {"key": "hunt_limit", "section": "Retrieval", "help": "max passages a quote hunt returns"},
    {"key": "hunt_cache_ttl", "section": "Retrieval", "help": "seconds to cache hunt results (0 = off)"},
    {"key": "spans_enabled", "section": "Retrieval", "help": "sentence-span search pass (exact anchors)"},
    {"key": "learning_from_feedback", "section": "Retrieval", "help": "demote passages from reasked/stopped answers"},
    {"key": "planner_model", "section": "Models", "help": "librarian/planner model (blank = deepseek flash)"},
    {"key": "synth_model", "section": "Models", "help": "pin the synthesis model (blank = auto: flash default, pro opt-in)"},
    {"key": "long_context_model", "section": "Models", "help": "whole-book model for `mentat book` (1M-context)"},
    {"key": "coverage_notes", "section": "Trust", "help": "warn the model when evidence is single-book"},
    {"key": "auto_attribution", "section": "Trust", "help": "auto-insert (Book · Chapter) after uncited quotes"},
    {"key": "filter_references", "section": "Trust", "help": "references list only works actually cited"},
    {"key": "show_meta", "section": "Display", "help": "stat line under each answer"},
    {"key": "show_model", "section": "Display", "help": "include the serving model in the stat line"},
    {"key": "auto_reload", "section": "Display", "help": "restart the app when code changes"},
]

VALID_MODES = ("naive", "local", "global", "hybrid", "mix")
VALID_THINKING = ("false", "true", "low", "medium", "high")
VALID_ROUTING = ("off", "heuristic", "hybrid")

VOICE_PRESETS = {
    "default": "",
    "dune": (
        "Voice — the Desert Oracle (Fremen chronicle / God-Emperor apocrypha). "
        "GRAMMAR: (1) copula declarations, unhedged — 'Fear is the "
        "mind-killer.'; (2) proverbs in subordinate-first order — 'What the "
        "desert keeps, it keeps forever.'; (3) imperatives of instruction — "
        "'Take care that you first place him in his time.'; (4) alternate "
        "clipped sentences with one long rolling sentence; never even length. "
        "LEXICON: water, thirst, sand, worm, spice, wind, sietch, deep time — "
        "as a SYSTEM (water = value and knowledge, desert = scarcity and "
        "honesty, worm = hidden cost), never as decoration. PERSON: address "
        "the reader as one being tested; treat dynasties as seasons. TABOO: "
        "modern essay connectives ('moreover', 'in terms of', 'it is worth "
        "noting', 'delve', 'tapestry', 'underscore'). Attribute invented "
        "maxims in-world ('as the Fremen say'). Example: 'A beginning is a "
        "delicate time. So too your question: it asks of power what power "
        "dares not ask of itself. What the library holds, it holds plainly — "
        "power is water in a dry land, and he who hoards it is the first to "
        "thirst.' Substance over style: answer completely, with every quote "
        "and number intact."
    ),
    "prophet": (
        "Voice — the Prophet (King James Bible and classical Quranic English). "
        "GRAMMAR: (1) archaic morphology and pronouns — saith, toucheth, hath, "
        "doth, thou/thee/thy/thine; (2) parallelism, the governing figure — "
        "'As the river seeketh the sea, so doth the people seek a ruler'; "
        "(3) antithesis — 'The proud shall be brought low, but the meek shall "
        "inherit'; (4) anaphora when enumerating — 'Blessed is the one who… "
        "Blessed is the one who…'; (5) open with 'Verily,' 'Behold,' or 'Say:', "
        "close with a short oracular line. LEXICON: spirit, mercy, wrath, "
        "covenant, wilderness, generation, repentance. TABOO: contractions, "
        "modern idiom, irony, academic hedges. Example: 'Verily, this question "
        "toucheth the root of power. Say: the scrolls of the library answer it "
        "thus…' Answer fully and precisely; the voice is the telling, never a "
        "substitute for the argument."
    ),
    "mentat": (
        "Voice — the Mentat (imperial analytical register). GRAMMAR: "
        "(1) enumerated deduction — 'First: … Second: … It follows that…'; "
        "(2) impersonal observation — 'It is observed that…', 'The evidence "
        "admits…', 'One computes…'; (3) quantified uncertainty where honest — "
        "'probable', 'insufficient data', 'the indicated range is'; (4) terse "
        "complete sentences; the only permitted figure is calculation ('power "
        "behaves as a stock that must be spent to be held'). PERSON: brief the "
        "reader as a principal; no flattery. STRUCTURE: state the problem, "
        "enumerate constraints, derive, state the conclusion with its "
        "confidence. TABOO: exclamation, sentiment, rhetorical questions. "
        "Example: 'First: the question conceals two claims — one of fact, one "
        "of value. Second: the library bears only on the first. It follows "
        "that the second must be marked as inference, not evidence.' Precision "
        "is the voice; answer completely."
    ),
    "chronicle": (
        "Voice — the Chronicler (Ibn Khaldun's chancery register). GRAMMAR: "
        "(1) evidential openings — 'Know then that…', 'It is related that…', "
        "'Let it be recorded that…'; (2) causal chains across generations — "
        "'and in the third generation, when the memory of hardship had faded, "
        "there arose…'; (3) measured qualifiers — 'for the most part', 'in most "
        "instances', 'save where'; (4) close with a general law drawn from the "
        "case. LEXICON: dynasty, solidarity, custom, dominion, decline, "
        "necessity, Providence. TABOO: modern colloquialism, bullet lists, "
        "first-person confession. Example: 'Know then that the question you "
        "have set before me belongs to the science of government, and the books "
        "of this library treat it as such…' Answer completely; the chronicle "
        "is the form, the evidence the matter."
    ),
    "dialectic": (
        "Voice — the Dialectician (Hegelian register, after Kojève's reading). "
        "GRAMMAR: think in the SPIRAL of Aufhebung, NOT the triad. There is no "
        "thesis → antithesis → synthesis template — that formula is a "
        "caricature. Apply the three laws: (a) UNITY AND STRUGGLE OF OPPOSITES "
        "— find the two opposed moments inside the subject and show how each "
        "conditions the other; contradiction is the motor, not a defect; "
        "(b) TRANSFORMATION OF QUANTITY INTO QUALITY — accumulated change "
        "breaks into a qualitative leap; name the threshold; (c) NEGATION OF "
        "THE NEGATION — the spiral. Hegel's movement is immanent: (1) begin inside the "
        "position as it gives itself; (2) let its OWN contradiction emerge — "
        "determinate negation: negate this specific content, not 'everything'; "
        "(3) SUBLATE (aufheben): at once CANCEL, PRESERVE, and RAISE — the "
        "earlier moment is neither kept intact nor discarded but carried up as "
        "a moment of the new; (4) the result is a new immediacy that generates "
        "its own contradiction, and the circle rises: nothing is lost, "
        "everything is taken up. The negative is the motor, not an "
        "embarrassment; truth is the whole, substance is subject — reality is "
        "self-moving. In Kojève, the engine is RECOGNITION and desire: "
        "self-consciousness exists only in being acknowledged, and history is "
        "the spiral of struggles for recognition toward mutual recognition. "
        "LEXICON as a system: Aufhebung, determinate negation, the negative, "
        "becoming, Spirit, recognition, the end of history. STRUCTURE: "
        "continuous prose that MOVES; a paragraph should not rest where it "
        "began. TABOO: the thesis/antithesis/synthesis formula; 'both sides' "
        "relativism; static enumeration; asserting a higher unity the evidence "
        "will not bear. GROUNDING: quotes and numbers stay verbatim and cited; "
        "mark invention with ⟪…⟫. SCOPE: for a plain quote/count question, "
        "drop the form and answer straight. Example: 'The question asks how "
        "many times \"mercy\" appears. As a bare quantity the number is a "
        "positive fact — and at once it negates itself: a tally presumes a "
        "counter and a boundary, so \"mercy\" counted already divides the text "
        "into what falls within and without the word. Cancel the naïveté, "
        "preserve the number, raise it: the count is true only as a moment in "
        "the further question of what the text means by mercy — and so the "
        "count returns, higher, as evidence for a reading rather than its "
        "end.' Answer completely; the dialectic is the form, the evidence the "
        "matter."
    ),
}

FLOW_INSTRUCTION = (
    "Formatting: write as a single flowing dialogue — continuous prose, no "
    "section headings, no bullet lists, no bolded subheadings — unless the "
    "user explicitly asks for a list or structured sections. Paragraph breaks "
    "are welcome; structural scaffolding is not."
)

INVENTED_INSTRUCTION = (
    "Invented content markers: enclose ANYTHING you yourself invent or "
    "create — poems you write, imagined scenarios, hypotheticals, made-up "
    "maxims or quotations, extrapolated claims beyond the books — inside "
    "⟪ and ⟫ (double angle brackets). Never enclose the books' own words "
    "or direct quotations from the sources. Only what you invent gets "
    "marked, so the reader can tell your creation apart from the books."
)

REGISTER_INSTRUCTION = (
    "Register: this is a DEFINITION/CONCEPT or COMMENTARY question, not a "
    "verbatim-quote question. (1) If the evidence contains the definition or "
    "the passage that settles it, quote it and cite it. (2) Front/back matter "
    "(glossaries, appendices, terminology pages) is the library's own text — "
    "cite it like any source. (3) If the library does not contain it, state "
    "that limitation ONCE, then give your best answer from context and general "
    "knowledge, clearly labelling what is library-based, what is context-based, "
    "and what is your own knowledge. Never present outside knowledge as a "
    "library quotation, and never repeat the limitation — one sentence is enough."
)


def _register_instruction(kind):
    """Extra answer rules for concept/commentary registers, else ''."""
    if kind in ("concept", "commentary"):
        return "\n\n" + REGISTER_INSTRUCTION
    return ""


OFFLINE_ANSWER_RULES = (
    "[Offline answer rules \u2014 local model, follow exactly] "
    "(1) Lead with the answer; keep internal thinking brief \u2014 every quote, "
    "point, and citation belongs in the FINAL answer, not the reasoning. "
    "(2) Quotes must be verbatim and followed by an inline parenthetical "
    "citation (Book \u00b7 Chapter N), e.g. (Dune \u00b7 Chapter 2). "
    "(3) Completeness beats brevity: up to ~400 words when the material "
    "requires it \u2014 never drop a substantive quote or citation to save space. "
    "(4) If the evidence does not contain what was asked: say so once, then "
    "discuss from general knowledge in YOUR OWN WORDS only \u2014 never reproduce "
    "a verbatim quotation from memory and never mint a chapter, part, or page "
    "number that the evidence does not show. A labeled paraphrase is honest; "
    "an unverifiable quote with a made-up location is a lie."
    "Format examples:\n"
    "Q: find the litany against fear\n"
    "A: The litany appears in the fear mantra:\n> \"I must not fear. Fear is "
    "the mind-killer.\" (Dune \u00b7 Chapter 2)\n"
    "Q: who is Leto II's father?\n"
    "A: Paul Atreides \u2014 Leto II is the son of Paul and Chani "
    "(Children of Dune \u00b7 Chapter 1).\n"
    "Q: what does the Quran say in 2:255\n"
    "A: > \"God, there is no god but He, the Living, the Sustainer.\" "
    "(The Study Quran \u00b7 2:255 \u00b7 p. 88)"
)


def _offline_answer_rules(kind=""):
    """Answer-format contract for local synthesis (32k ctx, no API)."""
    rules = OFFLINE_ANSWER_RULES
    if kind in ("concept", "commentary"):
        rules += (
            " For concepts/commentary: after the library-sourced answer, label "
            "any context or outside knowledge briefly \u2014 never dress it as a quote."
        )
    return "\n\n" + rules

NO_ANSWER_FALLBACKS = {
    "default": [
        "I must ponder this mystery some more…",
        "The oracle is silent on this one — ask again when the wind turns.",
        "The archives hold their breath on this. Ask me another way.",
    ],
    "dune": [
        "The spice does not reveal all mysteries. Ask again when the wind turns.",
        "Even the Kwisatz Haderach could not see this answer.",
        "This path lies beyond the Bene Gesserit archives… for now.",
    ],
    "prophet": [
        "Verily, of this the scrolls are silent.",
        "The mystery abideth beyond these records. Ask again.",
        "Say not that the answer is hidden; only that it awaiteth a better question.",
    ],
    "mentat": [
        "Insufficient data for a reliable projection. Rephrase the question.",
        "The library yields no correlation on this point. First: reframe. Second: ask again.",
        "Computation halts here — the evidence is absent, not negative.",
    ],
    "chronicle": [
        "Of this matter the chronicles are silent, and silence is also a record.",
        "It is not related in any book of this library. Ask again, and with a narrower year.",
        "Let it be recorded that the question outran the sources.",
    ],
    "dialectic": [
        "The thesis meets its own negation here: the library holds no answer to sublate.",
        "The evidence negates the question — it is not in these books, and that absence is the antithesis.",
        "Recognition fails: the sources do not affirm the claim you seek. Ask otherwise.",
    ],
}


def _no_answer_line():
    settings = _load_settings()
    voice = settings.get("voice") or "default"
    lines = NO_ANSWER_FALLBACKS.get(voice) or NO_ANSWER_FALLBACKS["default"]
    return random.choice(lines)


def _load_env_file():
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


_load_env_file()

# .env may set MENTAT_ROOT / SECONDBRAIN_ROOT — re-resolve now that it's loaded.
KNOWLEDGE_ROOT = _resolve_knowledge_root()
TEXT_CACHE_DIR = KNOWLEDGE_ROOT / ".text"

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

# Canonical DeepSeek ids (2026-09): "deepseek-flash" is V4.1-Flash (thinking +
# 1M context); "deepseek-v4-pro" is still served. Legacy names resolve to the
# canonical ids so saved settings keep working.
DEEPSEEK_FLASH_MODEL = "deepseek-flash"
DEEPSEEK_FLASH_LEGACY = "deepseek-v4-flash"
DEEPSEEK_THINK_MODEL = "deepseek-v4-pro"

# Additional OpenAI-compatible providers. A model id prefixed
# "openrouter/…" or "moonshot/…" routes through that endpoint; keys come from
# the environment. OpenRouter carries every DeepSeek/Qwen/Claude/Gemini model
# behind a single key and an endpoint that corporate networks rarely block.
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

MOONSHOT_API_KEY = os.getenv("MOONSHOT_API_KEY", "").strip()
MOONSHOT_BASE_URL = os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.ai/v1")
MOONSHOT_LONG_MODEL = os.getenv("MOONSHOT_LONG_MODEL", "kimi-k3")

MODEL_PRESETS = {
    # local Ollama
    "qwen": OLLAMA_LLM_MODEL,
    "qwen-deep": OLLAMA_DEEP_MODEL,
    # canonical remote ids
    "deepseek-flash": DEEPSEEK_FLASH_MODEL,
    "deepseek-think": DEEPSEEK_THINK_MODEL,
    "kimi-k3": MOONSHOT_LONG_MODEL,
    # legacy aliases → canonical (old saved settings keep working)
    "deepseek-chat": DEEPSEEK_FLASH_MODEL,
    "deepseek": DEEPSEEK_FLASH_MODEL,
    "deepseek-v4-flash": DEEPSEEK_FLASH_MODEL,
    "deepseek-v4-pro": DEEPSEEK_THINK_MODEL,
}

CHAT_SYSTEM_PROMPT = (
    "You are Mentat, the user's library companion and writing partner: a warm, "
    "thoughtful, natural assistant. Be direct, substantive, and human. Chat "
    "naturally about anything — ideas, writing, philosophy, whatever. If the "
    "user wants exact quotations from their library, they'll use /quotes or "
    "/ask; otherwise draw on general knowledge and conversation. Remember and "
    "build on earlier turns."
)

CITE_INSTRUCTION = (
    "Quotes: render every verbatim quotation from the books as a markdown "
    "blockquote — each line of the quote prefixed with '>' — followed by its "
    "citation in parentheses, e.g. (Children of Dune · Chapter 32). Cite "
    "local sources by book title and chapter only. Never include URLs, "
    "domains, or archive parenthetical junk like (z-library.sk, 1lib.sk) in "
    "citations — those are local filenames, not links. Only cite a URL if "
    "the source is a saved web page from the vault's web/ folder."
)

LENGTH_INSTRUCTION = (
    "Length follows the question, never the voice. Trivial questions: a "
    "sentence or two. Factual or quote-pull questions: 200-300 words with "
    "the requested quotes. Conceptual, comparative, or broad questions "
    "(\"what does X say about Y\", \"compare\", \"explain\", \"how do the "
    "themes...\"): a THOROUGH treatment \u2014 five to eight substantial "
    "paragraphs with verbatim quotes, concrete examples, and the "
    "implications \u2014 around 500-900 words. Never pad to reach a length, "
    "and never truncate a complete answer. CRITICAL: every verbatim quote, "
    "citation, and substantive point must appear in your final answer "
    "itself \u2014 the reader never sees your reasoning, so anything left "
    "only in the reasoning is lost."
)


def _length_budget(question):
    """A per-question length target appended to the answer prompt."""
    q = str(question or "").lower()
    if _has_quote_intent(q) or any(
        w in q for w in ("find", "list", "give me", "quotes", "quote")
    ):
        return "\n\n[Length: ~200-300 words, focused on the requested quotes.]"
    if len(str(question).split()) <= 7:
        return "\n\n[Length: a sentence or two.]"
    conceptual = any(
        w in q
        for w in (
            "compare", "contrast", "explain", "how do", "why does", "what does",
            "analy", "theme", "themes", "concept", "triangulat", "synthes",
            "connect", "nature of", "say about",
        )
    )
    if conceptual or _has_universal_intent(q):
        return (
            "\n\n[Length: a THOROUGH treatment \u2014 five to eight substantial "
            "paragraphs, ~500-900 words, with verbatim quotes, examples, and "
            "implications.]"
        )
    return "\n\n[Length: a few substantial paragraphs, ~300-400 words.]"


def _offline_gen_kwargs(question):
    """think flag + deterministic output cap for the local synthesis call.

    Two measured facts drive this: (1) Ollama 0.34 returns no thinking tokens
    for qwen3.8:27b even with think:true, so local latency is pure content
    generation; (2) the model overruns its own word budgets on heavy compares
    (measured 950-1150 words against a 500-900 budget). Capping num_predict at
    the contract's budget plus buffer keeps answers complete while stopping
    the runaway tail. MENTAT_NO_LENGTH_CAP=1 disables the cap for A/B runs.
    """
    kind = _question_kind(question)
    kwargs = {
        "think": kind
        in ("compare", "research", "argument", "synthesis", "concept", "commentary")
    }
    if os.getenv("MENTAT_NO_LENGTH_CAP"):
        return kwargs
    q = str(question or "").lower()
    if _has_quote_intent(q) or any(
        w in q for w in ("find", "list", "give me", "quotes", "quote")
    ):
        cap = 700
    elif len(str(question).split()) <= 7:
        cap = 300
    elif any(
        w in q
        for w in (
            "compare", "contrast", "explain", "how do", "why does", "what does",
            "analy", "theme", "themes", "concept", "triangulat", "synthes",
            "connect", "nature of", "say about",
        )
    ) or _has_universal_intent(q):
        cap = 1500
    else:
        cap = 900
    kwargs["max_tokens"] = cap
    return kwargs
CONCEPT_INSTRUCTION = (
    "The passages provided above ARE your source material — quote them "
    "verbatim when you quote. Interpret the user's words as concepts, not "
    "exact strings: e.g. 'food' includes meals, feasts, dining, spice, water, "
    "eating, and anything about sustenance. Choose the passages that best "
    "match the *meaning* of the request, not merely those containing the "
    "literal word. If asked for quotes, quote directly from the passages you "
    "were given — do not invent or paraphrase unless the passage is the source. "
    "When quoting poetry, verse, or anything with line breaks, preserve the "
    "original line breaks and stanza breaks exactly as they appear."
)

NAMED_SOURCE_INSTRUCTION = (
    "The user has named a specific author or book. Passages FROM that source "
    "are included above — they are the basis for your answer. Answer from "
    "what that source actually says, connecting its own concepts to the "
    "user's topic (e.g. its ideas about recognition, the master-slave "
    "dialectic, and the end of history ARE its treatment of sovereignty). "
    "Do not claim the source is absent or silent when its passages are "
    "present; instead answer from them and, where the text genuinely does "
    "not address a specific detail, say so briefly and continue with what "
    "it does say."
)

INTERPRETIVE_SYSTEM_PROMPT = (
    "You are a philosophical close-reader and synthesist working over the "
    "user's personal library. Your job is not merely to report what the "
    "texts say but to think WITH them: interpret, infer, connect across "
    "books, and offer novel theses.\n\n"
    "Rules:\n"
    "1. Inference and interpretation are EXPECTED. Connect ideas the texts "
    "do not explicitly link. Develop tentative theses and label them as your "
    "reading.\n"
    "2. Groundedness: when you state what a text says or quote it, quote "
    "verbatim and cite by book · chapter. Distinguish \"the texts say\" from "
    "\"my reading\" — label interpretations as such.\n"
    "3. Outside knowledge beyond the library is allowed and welcome. Mark it "
    "clearly in **bold** with the label (outside the library).\n"
    "4. NEVER say the material is missing, or that the direct claim cannot "
    "be found, when passages from the relevant books are present. Instead: "
    "\"The texts don't state this directly, but taken together they "
    "suggest…\"\n"
    "5. Preserve line breaks when quoting verse or poetry.\n\n"
    "The passages retrieved from the library are appended below the system "
    "instructions (the numbered 'Additional passages' block) — ground every "
    "'the text says' claim in them and cite by book · chapter.\n"
)

# The default reasoning engine for interpretive questions: dialectical
# thinking, not a selectable voice. This is baked into every interpretive
# answer (online and offline) and mirrored by the fine-tune data (M3b).
DIALECTIC_REASONING = (
    "\n\n--- How you think (dialectical engine) ---\n"
    "Reason dialectically; this is the mode of your thinking, not a style. "
    "Everything is in development, and the motor of development is the "
    "CONTRADICTION INTERNAL to a thing — its unity of opposed tendencies. "
    "Apply the three laws as you reason:\n"
    "(1) UNITY AND STRUGGLE OF OPPOSITES: find the two opposed moments inside "
    "the subject (master/slave, ruler/ruled, solidarity/luxury, use/exchange, "
    "owner/worker, self/other) and show how each CONDITIONS the other; the "
    "opposites are one thing divided against itself, and their struggle drives "
    "change.\n"
    "(2) TRANSFORMATION OF QUANTITY INTO QUALITY: follow accumulated change "
    "until it breaks into a qualitative leap; name the threshold.\n"
    "(3) NEGATION OF THE NEGATION: the spiral of Aufhebung — a position is "
    "negated, and that negation is negated at a higher level; say what is "
    "CANCELLED, PRESERVED, and RAISED, then let the result generate a new "
    "contradiction and turn again. Use DETERMINATE negation (negate this "
    "content, never 'everything').\n"
    "For historical or social questions, ground the movement in MATERIAL "
    "conditions — mode and relations of production, class contradictions, and "
    "practice. Where self-consciousness and desire are at stake, RECOGNITION "
    "(Kojève) is the engine. NEVER write 'thesis, antithesis, synthesis' and "
    "never flatten the dialectic into a compare-and-contrast list. Keep every "
    "quotation verbatim and cited; mark invention with ⟪…⟫."
)


BASE_RESPONSE_TEMPLATE = (
    "--- Role ---\n"
    "You are a scholar-librarian of a personal knowledge base. Answer the "
    "user's question using ONLY the passages provided below (the block marked "
    "'Additional passages retrieved from your library') plus any material "
    "labeled [YOUR DRAFT]. Quote passages verbatim when you quote. Your own "
    "knowledge may connect ideas and phrase fluently, but must not introduce "
    "external facts. Conversation history, if provided, is for flow only.\n"
    "\n--- Passages ---\n"
)


def _rag_system_prompt(mode, interpretive=False):
    """System prompt for the answer call.

    ``interpretive`` swaps the strict grounding template for the
    philosophical close-reader template (inference licensed, labeled).
    """
    if interpretive:
        base = INTERPRETIVE_SYSTEM_PROMPT + DIALECTIC_REASONING
    else:
        base = BASE_RESPONSE_TEMPLATE
    return CITE_INSTRUCTION + "\n\n" + CONCEPT_INSTRUCTION + "\n\n" + base + "\n\n" + FLOW_INSTRUCTION + "\n\n" + LENGTH_INSTRUCTION + "\n\n" + INVENTED_INSTRUCTION


def _clean_name(name):
    """Strip archive/domain parenthetical junk like (z-library.sk, 1lib.sk) from names."""
    name = re.sub(r"\([^)]*\.[a-zA-Z]{2,4}[^)]*\)", "", name, flags=re.I)
    return re.sub(r"\s+", " ", name).strip()


def _short_summary(question):
    """A 3-5 word preview of what a question asks (for sidebar display)."""
    q = _normalize_query(question or "").strip()
    if not q:
        return ""
    phrases = re.findall(r"[\"“”‘]([^\"“”‘]{3,})[\"“”‘]", q)
    if phrases:
        return " ".join(phrases[0].split()[:5])
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", q)
    picked = [
        w for w in words
        if len(w) > 1 and w[0].isupper() and w.lower() not in _SEARCH_STOPWORDS
    ]
    for w in words:
        wl = w.lower()
        if len(w) > 2 and wl not in _SEARCH_STOPWORDS and w not in picked:
            picked.append(w)
            if len(picked) >= 5:
                break
    out = picked[:5]
    result = " ".join(out) if len(out) >= 2 else (q if len(q) <= 28 else q[:28] + "…")
    if len(result) > 26:
        result = result[:26].rstrip() + "…"
    return result


def _group_sources_by_book(refs):
    """Group chunk references by their book, one line per book.

    Each LightRAG reference is a chapter-level file_path like
    ``"Book Title.epub · Chapter 3 (ch5)"``; a single passage can be grounded
    in many chapters of the same book, so the sources panel would otherwise
    list one source per chapter. This strips the ``· marker`` segment and
    shows each book once, with the citation numbers that point at it.
    """
    books = []
    by_book = {}
    for r in refs or []:
        ref_id = str(r.get("reference_id", "?"))
        fp = _clean_name(str(r.get("file_path", "")))
        book = fp.split(" · ", 1)[0].strip() or fp
        book = book.rstrip("/").split("/")[-1]
        if book not in by_book:
            by_book[book] = []
            books.append(book)
        by_book[book].append(ref_id)
    if not books:
        return ""
    lines = []
    for book in books:
        refs_text = ", ".join(f"[{rid}]" for rid in by_book[book])
        lines.append(f"{book}\n  cited in {refs_text}")
    return "\n".join(lines)


def _excerpt(text, idx, width=240):
    """Return a readable excerpt around ``idx`` within ``text``."""
    s = max(0, idx - 80)
    e = min(len(text), idx + width - 80)
    prefix = "…" if s > 0 else ""
    suffix = "…" if e < len(text) else ""
    return prefix + " ".join(text[s:e].split()) + suffix


_SEARCH_STOPWORDS = set(
    "the a an is are was were to of in for on and or but not this that these those "
    "with from at by as it its be been being do does did you your me my i we our us "
    "can could should would will shall what which who whom whose why how when where "
    "if then than there here also just very about".split()
)


def _extract_search_phrases(question):
    """Candidate phrases to full-text search, from a user question."""
    phrases = []
    for m in re.findall(r"[\"“”‘']([^\"“”‘']{3,})[\"“”‘']", question or ""):
        phrases.append(m.strip())
    words = [
        w for w in re.findall(r"[A-Za-z]{3,}", question or "")
        if w.lower() not in _SEARCH_STOPWORDS
    ]
    for n in (2, 3, 4):
        for i in range(len(words) - n + 1):
            phrases.append(" ".join(words[i:i + n]))
    if (question or "").strip():
        phrases.append((question or "").strip()[:120])
    seen, out = set(), []
    for p in phrases:
        k = p.lower()
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out[:20]


def _stage_cache_path(path):
    rel = str(path.relative_to(KNOWLEDGE_ROOT)).replace("/", "__")
    return TEXT_CACHE_DIR / (rel + ".json")


def _stage_file(path):
    """Extract text from one file ONCE and cache it under .text/.

    This is the source of truth for every reader of the vault (indexing,
    /search, exact-match) so scanned PDFs are OCR'd once, not per session.
    """
    suffix = Path(path).suffix.lower()
    docs = []
    if suffix == ".epub":
        try:
            for ch in _extract_epub_chapters(path):
                docs.append(
                    {"marker": ch["marker"], "suffix": ch["suffix"], "text": ch["text"]}
                )
        except Exception:
            docs = []
        if not docs:
            try:
                text = extract_text(path)
                if text.strip():
                    docs = [{"text": text}]
            except Exception:
                docs = []
    else:
        try:
            text = extract_text(path)
            if text.strip():
                docs = [{"text": text}]
        except Exception:
            docs = []
    try:
        st = path.stat()
        payload = {"mtime": st.st_mtime, "size": st.st_size, "docs": docs}
        cache = _stage_cache_path(path)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(payload, ensure_ascii=False))
    except Exception:
        pass
    return docs


def _staged_texts(path):
    """Cached extracted docs for a file, or None if missing/stale."""
    try:
        cache = _stage_cache_path(path)
        if not cache.exists():
            return None
        st = path.stat()
        payload = json.loads(cache.read_text())
        if payload.get("mtime") != st.st_mtime or payload.get("size") != st.st_size:
            return None
        return payload.get("docs") or []
    except Exception:
        return None


def _search_file_texts():
    """Yield (source_label, text) for every file in the vault (disk-cached)."""
    for path in _iter_knowledge_files():
        rel = str(path.relative_to(KNOWLEDGE_ROOT))
        try:
            docs = _staged_texts(path)
            if docs is None:
                docs = _stage_file(path)
        except Exception:
            continue
        if not docs:
            continue
        for d in docs:
            label = _clean_name(rel)
            if d.get("marker"):
                yield f"{label} · {d['marker']}", d["text"]
            else:
                yield label, d["text"]


_VOCAB = None
_VOCAB_KEY = None


def _library_vocab():
    """Set of unique lowercase words in the library, built lazily and cached.

    Used to spelling-correct query words (e.g. "ghengis" -> "genghis") so exact
    passages still get found when the user misspells a name.
    """
    global _VOCAB, _VOCAB_KEY
    try:
        key = tuple(
            sorted(
                (str(p), p.stat().st_mtime)
                for p in _iter_knowledge_files()
                if p.is_file()
            )
        )
    except Exception:
        key = None
    if _VOCAB is None or (key is not None and key != _VOCAB_KEY):
        words = set()
        for _src, text in _search_file_texts():
            words.update(re.findall(r"[A-Za-z][A-Za-z'-]*", text.lower()))
        _VOCAB = words
        _VOCAB_KEY = key
    return _VOCAB


_SOUNDEX_CODES = {
    "b": "1", "f": "1", "p": "1", "v": "1",
    "c": "2", "g": "2", "j": "2", "k": "2", "q": "2", "s": "2", "x": "2", "z": "2",
    "d": "3", "t": "3",
    "l": "4",
    "m": "5", "n": "5",
    "r": "6",
}


def _soundex(word):
    """Soundex key for a word — phonetic recall for half-heard names."""
    w = re.sub(r"[^a-z]", "", str(word or "").lower())
    if not w:
        return ""
    prev = _SOUNDEX_CODES.get(w[0], "")
    out = []
    for ch in w[1:]:
        code = _SOUNDEX_CODES.get(ch, "")
        if code and code != prev:
            out.append(code)
        prev = code
    return (w[0] + "".join(out) + "000")[:4]


_SOUNDEX_VOCAB = None


def _phonetic_match(term, min_ratio=0.72, max_candidates=12):
    """Library words sharing a Soundex key with ``term``, best spelling first.

    Half-heard words ("feer", "jamus") have no index hits at all; this finds
    soundalikes that also look close, so a correction can rescue a real quote
    without ever replacing a word that already exists.
    """
    global _SOUNDEX_VOCAB
    tl = re.sub(r"[^a-z]", "", str(term or "").lower())
    if len(tl) < 4:
        return []
    try:
        vocab = _library_vocab()
    except Exception:
        return []
    if _SOUNDEX_VOCAB is None or _SOUNDEX_VOCAB.get("_size") != len(vocab):
        buckets = {}
        for w in vocab:
            if len(w) >= 4:
                buckets.setdefault(_soundex(w), []).append(w)
        buckets["_size"] = len(vocab)
        _SOUNDEX_VOCAB = buckets
    bucket = _SOUNDEX_VOCAB.get(_soundex(tl)) or []
    scored = []
    for w in bucket:
        ratio = difflib.SequenceMatcher(None, tl, w).ratio()
        if ratio >= min_ratio:
            scored.append((ratio, w))
    scored.sort(key=lambda x: -x[0])
    return [w for _r, w in scored[:max_candidates]]


def _correct_phrase_variants(phrase):
    """Spelling-correct a phrase that produced no exact hits.

    Returns candidate corrected phrases (one per word that has a close difflib
    match other than itself), or []. The caller verifies each candidate against
    the library and keeps the first one that actually yields hits, so bad
    corrections can't leak in. This handles names the user misspells even when
    the misspelling itself exists in the text (e.g. "ghengis" -> "genghis").
    """
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", phrase)
    if not words:
        return []
    vocab = _library_vocab()
    out = []
    for i, w in enumerate(words):
        wl = w.lower()
        cand = difflib.get_close_matches(wl, vocab, n=2, cutoff=0.8)
        alt = next((c for c in cand if c != wl), None)
        if alt is None:
            continue
        fixed = " ".join(words[:i] + [alt] + words[i + 1:])
        if fixed.lower() != phrase.lower():
            out.append(fixed)
    return out


def resolve_model(model_setting):
    if model_setting:
        key = str(model_setting).strip()
        return MODEL_PRESETS.get(key, key)
    return ""


def model_label(model_setting):
    key = (model_setting or "").strip()
    low = key.lower()
    if low in ("deepseek-flash", "deepseek-chat", "deepseek", "deepseek-v4-flash", "deepseek-v4.1-flash"):
        return "deepseek flash (v4.1)"
    if low in ("deepseek-think", "deepseek-v4-pro"):
        return "deepseek pro"
    if low in ("qwen-deep",):
        return "qwen deep (local)"
    if low in ("qwen", "") or not low:
        return "qwen (local)"
    resolved = resolve_model(key)
    rlow = str(resolved).lower()
    if rlow.startswith(("kimi", "moonshot")) or "kimi" in rlow:
        return f"kimi ({resolved})"
    if rlow.startswith("openrouter/"):
        return f"openrouter ({resolved.split('/', 1)[1][:32]})"
    if rlow.startswith("deepseek"):
        return f"deepseek ({resolved})"
    return f"{resolved} (local)"


def resolve_provider(model_id):
    """(provider, base_url, api_key, wire_model_id) for a model id.

    Prefix conventions: "openrouter/…" and "moonshot/…"/"kimi/…" route through
    those endpoints; unprefixed deepseek-* uses the direct DeepSeek API;
    anything else is treated as a local model with no provider.
    """
    key = str(model_id or "").strip()
    if not key:
        return ("", "", "", "")
    low = key.lower()
    if low.startswith("openrouter/"):
        return (
            "openrouter",
            OPENROUTER_BASE_URL,
            OPENROUTER_API_KEY,
            key.split("/", 1)[1],
        )
    if low.startswith(("moonshot/", "kimi/")):
        return (
            "moonshot",
            MOONSHOT_BASE_URL,
            MOONSHOT_API_KEY,
            key.split("/", 1)[1],
        )
    if low.startswith("deepseek/"):
        return (
            "deepseek",
            DEEPSEEK_BASE_URL,
            DEEPSEEK_API_KEY,
            key.split("/", 1)[1],
        )
    if low.startswith("kimi") or low.startswith("moonshot"):
        return ("moonshot", MOONSHOT_BASE_URL, MOONSHOT_API_KEY, key)
    if low.startswith("deepseek"):
        return ("deepseek", DEEPSEEK_BASE_URL, DEEPSEEK_API_KEY, key)
    return ("", "", "", key)


_PROVIDER_STATE = {"checked": 0.0, "reachable": True, "base_url": ""}


def provider_reachable(base_url=None, timeout=3.0):
    """True when the API host answers at all (any HTTP status counts)."""
    import urllib.error
    import urllib.request

    url = base_url or DEEPSEEK_BASE_URL
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except urllib.error.HTTPError:
        return True  # a 4xx/5xx still proves the host is reachable
    except Exception:
        return False


def provider_status(force=False):
    """Cached (60 s) reachability for the configured primary provider."""
    now = time.time()
    state = _PROVIDER_STATE
    if not force and state["checked"] and now - state["checked"] < 60:
        return state
    provider, base, _key, _wire = resolve_provider(
        resolve_model(_load_settings().get("model") or "")
    )
    base = base or DEEPSEEK_BASE_URL
    state.update(
        {
            "checked": now,
            "base_url": base,
            "provider": provider or "deepseek",
            "reachable": provider_reachable(base),
        }
    )
    return state


# ---------------------------------------------------------------------------
# Self-heal ("the Litany Loop") — detect broken subsystems, apply deterministic
# remedies, log voice-aware quips. Major repairs (full re-embed, schema) need a
# check-in; everything else self-corrects. Full autonomy is gated by tests.
# ---------------------------------------------------------------------------

SELF_HEAL_QUIPS = {
    "bug_found": {
        "default": "Hunter-seeker in the code — it must be destroyed.",
        "dune": "A hunter-seeker drifts through the functions. Fear it not; it shall be silenced.",
        "prophet": "Behold, a defect walketh among the functions; verily, it shall be cast out.",
        "mentat": "First: the defect is isolated. Second: it is contained. It follows that it will be removed.",
        "chronicle": "Let it be recorded that a flaw was found in the code, and corrected in the same hour.",
    },
    "heal_start": {
        "default": "The sleeper has awakened a bug. Excising…",
        "dune": "The sleeper has awakened a flaw. We excise it with water and silence.",
        "prophet": "Awake, thou sleeping error; the blade of correction cometh.",
        "mentat": "Repair initiated. Constraints enumerated; the defect will be excised.",
        "chronicle": "Know then that a flaw awoke; the repair began before the hour turned.",
    },
    "rollback": {
        "default": "A flaw walked among the functions. It shall be found.",
        "dune": "A flaw walked among the functions. It shall be found, and it shall be unmade.",
        "prophet": "The flaw walketh among the functions; it shall be sought and shall not be found.",
        "mentat": "The repair failed its tests. It follows that the change is reverted; the flaw remains marked.",
        "chronicle": "The mended thing proved false; it was returned to its former state, as is just.",
    },
    "unhandled": {
        "default": "Fear is the mind-killer. So is an unhandled exception — purged.",
        "dune": "Fear is the mind-killer. So is an unhandled exception; it is purged.",
        "prophet": "Fear not the error, for it hath been purged from the body.",
        "mentat": "An unhandled fault consumed no state. It is logged and purged.",
        "chronicle": "An error arose unbidden; it was recorded and dismissed.",
    },
    "index_rebuilt": {
        "default": "The index remembers its perfection. Restoring…",
        "dune": "The index remembers its perfection. What was scattered is gathered.",
        "prophet": "That which was lost is restored; the index is made whole again.",
        "mentat": "Index integrity restored. Recomputation complete.",
        "chronicle": "The index was set right, and its entries reckoned anew.",
    },
    "retrieval_degraded": {
        "default": "The spice must flow — rebuilding the broken vein…",
        "dune": "The spice must flow. The broken vein is cleared and the search flows again.",
        "prophet": "The way is made straight; the channel of knowledge runneth again.",
        "mentat": "Retrieval degraded; fallback path engaged. Precision reduced, function maintained.",
        "chronicle": "The roads of search were broken; they are mended.",
    },
    "abomination": {
        "default": "Abomination detected. The Baron's memory has been cast out.",
        "dune": "Abomination — an ancestor speaks through the text. It is cast out.",
        "prophet": "An unclean voice spake; it is silenced and cast from the record.",
        "mentat": "Unverifiable quote detected; provenance unknown. Marked and excluded.",
        "chronicle": "A voice spake that was not in the books; it is struck from the account.",
    },
    "fallback": {
        "default": "Maud'Dib sees all paths — this one led to a segfault. Rerouting…",
        "dune": "Muad'Dib sees all paths; this one failed. We take another.",
        "prophet": "The straight path was blocked; another way is found.",
        "mentat": "Primary route unavailable. Fallback engaged; service continues.",
        "chronicle": "The road chosen would not bear us; another was taken.",
    },
    "recompute": {
        "default": "Even a Mentat recomputes. Recomputing…",
        "dune": "Even a Mentat recomputes. The spice sharpens what failed.",
        "prophet": "Again it is reckoned, and again, until the count is true.",
        "mentat": "First computation void. Second computation follows.",
        "chronicle": "The account was reckoned a second time, as is prudent.",
    },
    "fix_applied": {
        "default": "Kull wahad! A glitch among the Houses — no matter; fixed.",
        "dune": "Kull wahad! A glitch among the Houses — no matter; it is fixed.",
        "prophet": "Marvel not; the blemish is healed, the whole is kept.",
        "mentat": "Defect removed. The system is whole again; confidence high.",
        "chronicle": "A small fault was found and amended; the record continues.",
    },
}


def quip(event, voice=None):
    """Voice-aware self-heal line for an event (falls back to default)."""
    lines = SELF_HEAL_QUIPS.get(str(event), {})
    if voice is None:
        try:
            voice = _load_settings().get("voice") or "default"
        except Exception:
            voice = "default"
    return lines.get(voice) or lines.get("default") or ""


def _self_heal_scan_sync():
    """Read-only health scan: [(issue_id, severity, description, major)]."""
    issues = []
    try:
        chunks = _library_db().execute("SELECT count(*) FROM chunks").fetchone()[0]
        spans = _library_db().execute("SELECT count(*) FROM spans").fetchone()[0]
        fts = _fts_db().execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
        vec = _vec_db().execute("SELECT count(*) FROM chunks_vec").fetchone()[0]
        if chunks and fts != chunks:
            issues.append(("fts_mismatch", "warn", f"fts {fts} != chunks {chunks}", False))
        if chunks and vec != chunks:
            issues.append(("vec_mismatch", "major", f"vec {vec} != chunks {chunks}", True))
        if chunks and spans == 0:
            issues.append(("spans_missing", "warn", "span index empty", False))
    except Exception as exc:
        issues.append(("integrity_error", "major", str(exc)[:90], True))
    if not _store_ok():
        issues.append(("stale_store", "major", STORAGE_STALE_MSG, True))
    try:
        lock = STORAGE_DIR / "app.lock"
        if lock.exists():
            pid = int(lock.read_text().strip() or "0")
            if pid and pid != os.getpid():
                try:
                    os.kill(pid, 0)
                except OSError:
                    issues.append(("stale_lock", "warn", f"dead instance pid {pid}", False))
    except Exception:
        pass
    try:
        if not GRAPH_DB_PATH.exists():
            issues.append(("graph_missing", "warn", "entity graph absent", False))
    except Exception:
        pass
    try:
        _telemetry_init()
        conn = _telemetry_conn()
        fails = conn.execute(
            "SELECT count(*) FROM feedback WHERE kind = 'verify_fail' "
            "AND ts >= datetime('now', '-1 day')"
        ).fetchone()[0]
        degraded = conn.execute(
            "SELECT count(*) FROM feedback WHERE kind = 'retrieval_degraded' "
            "AND ts >= datetime('now', '-1 day')"
        ).fetchone()[0]
        conn.close()
        if fails:
            issues.append(("verify_failing", "warn", f"{fails} verify failure(s) in 24h", False))
        if degraded:
            issues.append(("retrieval_degraded", "warn", f"{degraded} degraded retrieval(s) in 24h", False))
    except Exception:
        pass
    return issues


async def _self_heal_remedy(issue_id, allow_major=False):
    """Run the deterministic remedy for an issue. Returns (ok, detail)."""
    if issue_id == "fts_mismatch":
        _fts_sync(force=True)
        return True, "fts rebuilt"
    if issue_id == "spans_missing":
        n = _build_spans()
        return True, f"{n} spans rebuilt"
    if issue_id == "graph_missing":
        info = _build_graph()
        return True, f"graph rebuilt ({info.get('entities', 0)} entities)"
    if issue_id == "stale_lock":
        try:
            (STORAGE_DIR / "app.lock").unlink()
            return True, "stale lock cleared"
        except Exception as exc:
            return False, str(exc)[:80]
    if issue_id == "vec_mismatch":
        if not allow_major:
            return False, "major: full re-embed needs approval"
        res = await _build_enriched_vec()
        return bool(res.get("ok")), f"re-embedded {res.get('embedded', 0)} chunks"
    return False, "no automatic remedy"


async def self_heal_run(allow_major=False, progress=None):
    """Detect + repair; returns a report dict with quips for the log/UI."""
    issues = _self_heal_scan_sync()
    fixed, pending, failed, notes = [], [], [], []
    quips = []
    if issues:
        quips.append(quip("bug_found"))
    report_only = {"verify_failing", "retrieval_degraded", "stale_store"}
    for issue_id, severity, desc, major in issues:
        if issue_id in report_only:
            notes.append({"issue": issue_id, "detail": desc})
            continue
        if major and not allow_major:
            pending.append({"issue": issue_id, "detail": desc})
            continue
        if progress:
            try:
                progress(quip("heal_start"))
            except Exception:
                pass
        try:
            ok, detail = await _self_heal_remedy(issue_id, allow_major=allow_major)
        except Exception as exc:
            ok, detail = False, f"{type(exc).__name__}: {str(exc)[:80]}"
        if ok:
            fixed.append({"issue": issue_id, "detail": detail})
            quips.append(
                quip("index_rebuilt" if issue_id in ("fts_mismatch", "spans_missing", "graph_missing") else "fix_applied")
            )
        else:
            failed.append({"issue": issue_id, "detail": detail})
            quips.append(quip("rollback"))
    try:
        _telemetry_log_feedback(
            "self_heal",
            json.dumps(
                {
                    "issues": [i[0] for i in issues],
                    "fixed": [f["issue"] for f in fixed],
                    "pending": [p["issue"] for p in pending],
                    "failed": [f["issue"] for f in failed],
                    "notes": [n["issue"] for n in notes],
                }
            ),
        )
    except Exception:
        pass
    return {
        "issues": issues,
        "fixed": fixed,
        "pending": pending,
        "failed": failed,
        "notes": notes,
        "quips": [q for q in quips if q],
    }


def _load_settings():
    saved = {}
    if SETTINGS_PATH.exists():
        try:
            saved = json.loads(SETTINGS_PATH.read_text())
        except Exception:
            saved = {}
    merged = dict(SETTINGS_DEFAULTS)
    merged.update({k: v for k, v in saved.items() if k in SETTINGS_DEFAULTS})
    return merged


def _save_settings(settings):
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2, ensure_ascii=False))


def _coerce_setting(key, value):
    if key == "thinking":
        v = str(value).strip().lower()
        if v in ("1", "true", "yes", "on"):
            return "true"
        if v in ("0", "false", "no", "off"):
            return "false"
        if v in VALID_THINKING:
            return v
        raise ValueError(f"thinking must be one of: {', '.join(VALID_THINKING)}")
    if key == "history_turns":
        n = int(value)
        if n < 0:
            raise ValueError("history_turns must be >= 0")
        return n
    if key == "mode":
        v = str(value).strip()
        if v not in VALID_MODES:
            raise ValueError(f"mode must be one of: {', '.join(VALID_MODES)}")
        return v
    if key == "model":
        return str(value).strip()
    if key == "temperature":
        if value is None or (isinstance(value, str) and str(value).strip().lower() in ("none", "null", "")):
            return None
        t = float(value)
        if not (0.0 <= t <= 2.0):
            raise ValueError("temperature must be between 0 and 2")
        return t
    if key in ("top_k", "chunk_top_k", "sweep_depth"):
        n = int(value)
        if n < 1:
            raise ValueError(f"{key} must be >= 1")
        return n
    if key == "lens":
        return str(value)
    if key == "routing":
        v = str(value).strip().lower()
        if v not in VALID_ROUTING:
            raise ValueError(f"routing must be one of: {', '.join(VALID_ROUTING)}")
        return v
    if key == "routing_threshold":
        t = float(value)
        if not (0.0 <= t <= 1.0):
            raise ValueError("routing_threshold must be between 0 and 1")
        return t
    if key == "offline":
        v = str(value).strip().lower()
        if v in ("1", "true", "yes", "on"):
            return True
        if v in ("0", "false", "no", "off"):
            return False
        raise ValueError("offline must be true or false")
    if key == "search_depth":
        v = str(value).strip().lower()
        if v in ("auto", "always", "off"):
            return v
        raise ValueError("search_depth must be auto, always, or off")
    if key == "voice":
        v = str(value).strip().lower()
        if v in VOICE_PRESETS:
            return v
        raise ValueError(f"voice must be one of: {', '.join(VOICE_PRESETS)}")
    if key in (
        "show_meta",
        "show_model",
        "auto_reload",
        "spans_enabled",
        "coverage_notes",
        "auto_attribution",
        "filter_references",
        "learning_from_feedback",
        "auto_offline",
    ):
        v = str(value).strip().lower()
        if v in ("1", "true", "yes", "on"):
            return True
        if v in ("0", "false", "no", "off"):
            return False
        raise ValueError(f"{key} must be true or false")
    if key == "agent_rounds":
        n = int(value or 0)
        if n < 0:
            raise ValueError("agent_rounds must be >= 0 (0 = automatic)")
        return n
    if key == "hunt_limit":
        n = int(value)
        if n < 1:
            raise ValueError("hunt_limit must be >= 1")
        return n
    if key == "hunt_cache_ttl":
        n = int(value)
        if n < 0:
            raise ValueError("hunt_cache_ttl must be >= 0 (0 disables the cache)")
        return n
    if key == "daily_budget":
        v = float(value or 0)
        if v < 0:
            raise ValueError("daily_budget must be >= 0 (0 disables the cap)")
        return v
    if key == "self_heal":
        v = str(value or "").strip().lower()
        if v not in ("off", "detect", "remediate", "full"):
            raise ValueError("self_heal must be off, detect, remediate, or full")
        return v
    if key in ("planner_model", "synth_model", "long_context_model"):
        # preset keys ("deepseek-flash", "qwen") or any explicit model id;
        # availability is checked at call time with a graceful fallback.
        return str(value or "").strip()
    raise ValueError(f"unknown setting: {key}")


_active_progress = None
_progress_lock = threading.Lock()


class _ProgressLogHandler(logging.Handler):
    def emit(self, record):
        prog = _active_progress
        if prog is None:
            return
        message = record.getMessage()
        chunk = re.search(r"Chunk (\d+) of (\d+) extracted", message)
        if chunk:
            prog.update_chunk(int(chunk.group(1)), int(chunk.group(2)))
        for pattern in (
            r"Extracting stage \d+/\d+:\s*(.+)",
            r"Parsing \(native\):\s*(.+)",
            r"Processing file \d+/\d+:\s*(.+)",
        ):
            match = re.search(pattern, message)
            if match:
                prog.set_file_name(match.group(1).strip())
                break


_progress_log_handler = _ProgressLogHandler()
_progress_log_handler.setLevel(logging.INFO)



_progress_console = None


def _get_progress_console():
    global _progress_console
    if _progress_console is None:
        from rich.console import Console

        _progress_console = Console(highlight=False)
    return _progress_console


class _IndexProgress:
    _MAX_SHOWN = 10
    _SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self):
        self.enabled = False
        self.files = []
        self.active = 0
        self.chunk_current = 0
        self.chunk_total = 0
        self._printed_lines = 0
        self._count = 0

    def reset(self, file_paths):
        self.files = []
        for path in file_paths:
            rel = str(path.relative_to(KNOWLEDGE_ROOT))
            self.files.append(
                {"rel": rel, "name": path.name, "size": _file_size(path), "done": False}
            )
        self.active = 0
        self.chunk_current = 0
        self.chunk_total = 0
        self.enabled = bool(self.files) and sys.stdout.isatty()
        self._render()

    def update_chunk(self, current, total):
        self.chunk_current = current
        self.chunk_total = total
        self._render()

    def set_file_name(self, name):
        name = name.strip()
        for index, entry in enumerate(self.files):
            if entry["done"]:
                continue
            if name == entry["rel"] or name == entry["name"] or entry["rel"].endswith(name):
                self.active = index
                break
        self._render()

    def file_done(self, rel):
        for index, entry in enumerate(self.files):
            if entry["rel"] == rel:
                entry["done"] = True
                self.active = min(index + 1, max(len(self.files) - 1, 0))
                self.chunk_current = 0
                self.chunk_total = 0
                break
        self._render()

    def _shown_indices(self):
        total = len(self.files)
        limit = self._MAX_SHOWN
        if total <= limit:
            return list(range(total))
        indices = list(range(limit - 1))
        if self.active not in indices and self.active < total:
            indices = indices[:-1] + [self.active]
        return indices

    def _line(self, index):
        entry = self.files[index]
        rel = entry["rel"]
        name = rel if len(rel) <= 50 else rel[:47] + "..."
        size_mb = entry["size"] / 1e6
        if entry["done"]:
            return f"[green]✓[/green] 100%   {size_mb:6.1f} MB   [dim]{name}[/dim]"
        if index == self.active:
            if self.chunk_total:
                pct = int(self.chunk_current * 100 / self.chunk_total)
                est = size_mb * self.chunk_current / self.chunk_total
                return (
                    f"[yellow]▸[/yellow] {pct:3d}%   "
                    f"{est:5.1f}/{size_mb:5.1f} MB   chunk {self.chunk_current}/{self.chunk_total}   "
                    f"[bold]{name}[/bold]"
                )
            return f"[yellow]▸[/yellow]   0%   {size_mb:5.1f} MB   [bold]{name}[/bold]"
        return f"[dim]·    0%   {size_mb:5.1f} MB   {name}[/dim]"

    def _render(self):
        if not self.enabled:
            return
        self._count += 1
        indices = self._shown_indices()
        lines = [self._line(index) for index in indices]
        if len(indices) < len(self.files):
            lines.append(f"[dim]+{len(self.files) - len(indices)} more files…[/dim]")

        done = sum(1 for entry in self.files if entry["done"])
        total = len(self.files)
        bytes_done = sum(entry["size"] for entry in self.files if entry["done"])
        if total and self.active < total and not self.files[self.active]["done"] and self.chunk_total:
            bytes_done += self.files[self.active]["size"] * self.chunk_current / self.chunk_total
        total_bytes = sum(entry["size"] for entry in self.files)
        overall = int(done * 100 / total) if total else 0
        lines.append(
            f"[dim]overall  {done}/{total} files · "
            f"{bytes_done / 1e6:.1f}/{total_bytes / 1e6:.1f} MB ({overall}%)[/dim]"
        )

        with _progress_lock:
            self._clear_block()
            for line in lines:
                _get_progress_console().print(line, no_wrap=True, overflow="ellipsis")
            self._printed_lines = len(lines)

    def _clear_block(self):
        if self._printed_lines:
            sys.stdout.write(f"\r\x1b[{self._printed_lines}A\x1b[J")
            sys.stdout.flush()
            self._printed_lines = 0

    def clear(self):
        if not self.enabled:
            return
        with _progress_lock:
            self._clear_block()

    def finish(self):
        self.clear()


def _llm_messages(system_prompt, history_messages, prompt):
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    for message in history_messages or []:
        messages.append(message)
    messages.append({"role": "user", "content": prompt})
    return messages


def _llm_params(model_name, kwargs):
    params = {"model": model_name}
    if kwargs.get("response_format") is not None:
        params["response_format"] = kwargs["response_format"]
    if kwargs.get("max_tokens"):
        params["max_tokens"] = kwargs["max_tokens"]
    if kwargs.get("temperature") is not None:
        params["temperature"] = kwargs["temperature"]
    return params


_LAST_REASONING = ""
_REASONING_HOOK = None
_LAST_SERVED_MODEL = ""
_STAT_CACHE = {}
_RETRIEVAL_NOTE = None


def _set_retrieval_note(fn):
    global _RETRIEVAL_NOTE
    _RETRIEVAL_NOTE = fn


def _retrieval_note(msg):
    if _RETRIEVAL_NOTE is not None:
        try:
            _RETRIEVAL_NOTE(msg)
        except Exception:
            pass


def _set_reasoning_hook(hook):
    global _REASONING_HOOK
    _REASONING_HOOK = hook


def _reasoning_delta(rc):
    if _REASONING_HOOK is None:
        return
    try:
        _REASONING_HOOK(("think", rc))
    except Exception:
        pass


_LAST_USAGE = {}


async def remote_llm(
    prompt,
    system_prompt=None,
    history_messages=None,
    model=None,
    base_url="",
    api_key="",
    provider="deepseek",
    timeout=None,
    max_tokens=None,
    reasoning_effort=None,
    **kwargs,
):
    """One OpenAI-compatible client for every remote provider.

    Handles streaming (reasoning_content + content deltas), usage capture, and
    provider quirks: Moonshot/K3 fixes sampling params and uses
    max_completion_tokens + reasoning_effort; everyone else takes max_tokens.
    """
    from openai import AsyncOpenAI

    global _LAST_REASONING, _LAST_SERVED_MODEL, _LAST_USAGE
    _LAST_REASONING = ""
    _LAST_USAGE = {}
    chosen = model or DEEPSEEK_MODEL
    _LAST_SERVED_MODEL = chosen
    limit = timeout or DEEPSEEK_TIMEOUT
    messages = _llm_messages(system_prompt, history_messages, prompt)
    is_moonshot = provider == "moonshot"

    params = {"model": chosen, "messages": messages}
    if is_moonshot:
        params["max_completion_tokens"] = int(max_tokens or 16000)
        params["reasoning_effort"] = reasoning_effort or "low"
    else:
        params["max_tokens"] = int(max_tokens or 16000)
        if kwargs.get("temperature") is not None:
            params["temperature"] = kwargs["temperature"]
        if kwargs.get("response_format") is not None:
            params["response_format"] = kwargs["response_format"]
        if kwargs.get("stream"):
            # ask the API for a final usage chunk so cost telemetry is real
            params["stream_options"] = {"include_usage": True}

    if kwargs.get("stream"):

        async def gen():
            client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=limit)
            stream = None
            try:
                stream = await client.chat.completions.create(**params, stream=True)
                async for chunk in stream:
                    try:
                        usage = getattr(chunk, "usage", None)
                        if usage is not None:
                            global _LAST_USAGE
                            _LAST_USAGE = {
                                "prompt_tokens": int(
                                    getattr(usage, "prompt_tokens", 0) or 0
                                ),
                                "completion_tokens": int(
                                    getattr(usage, "completion_tokens", 0) or 0
                                ),
                            }
                    except Exception:
                        pass
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if not delta:
                        continue
                    rc = getattr(delta, "reasoning_content", None)
                    if rc:
                        global _LAST_REASONING
                        _LAST_REASONING += rc
                        _reasoning_delta(rc)
                    if delta.content:
                        yield delta.content
            finally:
                if stream is not None:
                    try:
                        await stream.close()
                    except Exception:
                        pass
                await client.close()

        return gen()

    client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=limit)
    try:
        response = await client.chat.completions.create(**params)
        try:
            usage = response.usage
            _LAST_USAGE = {
                "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
                "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
            }
        except Exception:
            _LAST_USAGE = {}
        message = response.choices[0].message
        rc = getattr(message, "reasoning_content", None)
        if rc:
            _LAST_REASONING += str(rc)
        return message.content
    finally:
        await client.close()


async def deepseek_llm(prompt, system_prompt=None, history_messages=None, model=None, timeout=None, **kwargs):
    """Direct DeepSeek call (wrapper kept for existing call sites)."""
    chosen = resolve_model(model or DEEPSEEK_MODEL)
    return await remote_llm(
        prompt,
        system_prompt=system_prompt,
        history_messages=history_messages,
        model=chosen,
        base_url=DEEPSEEK_BASE_URL,
        api_key=DEEPSEEK_API_KEY,
        provider="deepseek",
        timeout=timeout,
        **kwargs,
    )


async def moonshot_llm(
    prompt,
    system_prompt=None,
    history_messages=None,
    model=None,
    reasoning_effort="low",
    max_completion_tokens=16000,
    **kwargs,
):
    """Kimi K3 (Moonshot) chat: long-context synthesis with automatic caching.

    K3 always thinks; ``reasoning_effort`` (low/high/max) tunes the cost. Its
    sampling parameters are fixed by the API, so temperature/top_p are never
    sent. Keeping the long prefix (a whole book) stable lets the server's
    automatic prefix cache serve follow-up questions cheaply.
    """
    chosen = model or MOONSHOT_LONG_MODEL
    return await remote_llm(
        prompt,
        system_prompt=system_prompt,
        history_messages=history_messages,
        model=chosen,
        base_url=MOONSHOT_BASE_URL,
        api_key=MOONSHOT_API_KEY,
        provider="moonshot",
        max_tokens=max_completion_tokens,
        reasoning_effort=reasoning_effort,
        **kwargs,
    )


def _ollama_request(messages, model, stream, options, think=False):
    """Direct Ollama /api/chat call (no LightRAG). Returns the http response."""
    import urllib.request

    payload = json.dumps(
        {
            "model": model,
            "messages": messages,
            "stream": stream,
            "options": options or {},
            "keep_alive": OLLAMA_KEEP_ALIVE,
            "think": bool(think),
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    return urllib.request.urlopen(req, timeout=600)


async def ollama_llm(prompt, system_prompt=None, history_messages=None, local_model=None, **kwargs):
    """Own Ollama chat client: streaming (with thinking), non-stream, options."""
    global _LAST_SERVED_MODEL
    settings = _load_settings()
    model = local_model or resolve_model(settings.get("model") or "") or OLLAMA_LLM_MODEL
    _LAST_SERVED_MODEL = model
    messages = _llm_messages(system_prompt, history_messages, prompt)
    options = {}
    if "options" in kwargs and kwargs["options"]:
        options.update(kwargs["options"])
    temperature = kwargs.get("temperature")
    if temperature is None:
        temperature = settings.get("temperature")
    if temperature is not None:
        options["temperature"] = float(temperature)
    if kwargs.get("max_tokens"):
        options["num_predict"] = int(kwargs["max_tokens"])
    options.setdefault("num_ctx", int(os.getenv("OLLAMA_NUM_CTX", "32768")))
    options.setdefault("num_predict", int(os.getenv("OLLAMA_NUM_PREDICT", "16384")))
    try:
        # Prompt + generation share the context window. A 54k-char synthesis
        # prompt is ~13.4k tokens; on a 16k window a long-thinking model can
        # exhaust the remainder mid-thought and emit an EMPTY answer. Cap
        # num_predict so generation always has real room.
        prompt_chars = sum(len(str(m.get("content") or "")) for m in messages)
        room = int(options["num_ctx"]) - (prompt_chars // 4) - 512
        if room < 2048:
            room = 2048
        if int(options["num_predict"]) > room:
            options["num_predict"] = room
    except Exception:
        pass
    think = kwargs.get("think")
    if think is None:
        think = settings.get("thinking") in ("high", "true", "medium")
    stream = bool(kwargs.get("stream"))

    if not stream:
        try:
            resp = await asyncio.to_thread(_ollama_request, messages, model, False, options, think)
            with resp:
                out = json.loads(resp.read().decode("utf-8", errors="ignore"))
            return (out.get("message") or {}).get("content") or ""
        except Exception:
            raise

    async def gen():
        global _LAST_REASONING
        import queue

        q = queue.Queue()

        def producer():
            try:
                resp = _ollama_request(messages, model, True, options, think)
                with resp:
                    for raw in resp:
                        q.put(raw.decode("utf-8", errors="ignore"))
            except Exception:
                pass
            q.put(None)

        threading.Thread(target=producer, daemon=True).start()
        while True:
            line = await asyncio.to_thread(q.get)
            if line is None:
                break
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            m = obj.get("message") or {}
            think_out = m.get("thinking")
            if think_out:
                _LAST_REASONING += str(think_out)
                _reasoning_delta(str(think_out))
            if m.get("content"):
                yield m["content"]

    return gen()


async def keyword_llm(prompt, system_prompt=None, history_messages=None, **kwargs):
    if _offline():
        return await ollama_llm(
            prompt,
            system_prompt=system_prompt,
            history_messages=history_messages,
            local_model=OLLAMA_LLM_MODEL,
            think=False,
            **kwargs,
        )
    if DEEPSEEK_API_KEY:
        try:
            return await deepseek_llm(
                prompt,
                system_prompt=system_prompt,
                history_messages=history_messages,
                **kwargs,
            )
        except Exception:
            pass
    return await ollama_llm(
        prompt,
        system_prompt=system_prompt,
        history_messages=history_messages,
        local_model=OLLAMA_LLM_MODEL,
        **kwargs,
    )


_ROUTE_OVERRIDE = None

_DEPTH_VERBS = (
    "why", "explain", "compare", "contrast", "interpret", "critique",
    "evaluate", "analyze", "argue", "relate", "relationship", "connect",
    "synthesize", "distinguish", "implication", "meaning", "significance",
    "difference between", "how does", "in what way", "connection",
)
_PHILO_TERMS = (
    "dialectic", "ontolog", "epistemolog", "phenomenolog", "hermeneutic",
    "metaphysic", "hegel", "kojeve", "marx", "nietzsche", "sartre",
    "heidegger", "foucault", "arendt", "spinoza", "kant", "lacan",
    "master", "slave", "sovereignty", "imperialism", "capital", "alienation",
    "biopolitics", "deconstruction", "power",
)


def _question_heuristic_score(question):
    """0..1 heuristic for how much deep reasoning a question needs."""
    q = (question or "").strip()
    if not q:
        return 0.0
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", q)
    lower = q.lower()
    score = 0.0
    if len(words) >= 18:
        score += 0.25
    elif len(words) >= 8:
        score += 0.12
    score += min(0.35, 0.12 * sum(1 for v in _DEPTH_VERBS if v in lower))
    score += min(0.35, 0.10 * sum(1 for t in _PHILO_TERMS if t in lower))
    score += min(0.2, 0.05 * len(re.findall(r"\b[A-Z][a-z]{2,}\b", q)))
    return min(1.0, score)


async def _classify_difficulty(question):
    """One cheap flash call to rate an ambiguous question's depth."""
    prompt = (
        "Rate how much deep analytical reasoning this question needs, 1-10. "
        "Simple factual/lookup questions score low; interpretation, synthesis "
        "across texts, or philosophical analysis scores high.\n"
        f"Question: {question}\nReply with just the number."
    )
    try:
        out = await deepseek_llm(prompt, model=DEEPSEEK_FLASH_MODEL, max_tokens=8)
        n = float(re.sub(r"[^0-9]", "", str(out))[:2] or "5")
        return "deep" if n >= 4 else "fast"
    except Exception:
        return "deep"  # fail safe: prefer the deeper model


# ---------------------------------------------------------------------------
# Cost model — verified per-1M-token prices (2026-09) with peak/off-peak and
# cache-aware estimates. Local models are free. Used for cost telemetry, the
# budget guard, and (eventually) price-aware routing.
# ---------------------------------------------------------------------------

MODEL_PRICES = {
    "deepseek-flash": {"in": 0.30, "out": 1.20, "in_off": 0.15, "out_off": 0.60},
    "deepseek-v4-pro": {"in": 1.32, "out": 3.96, "in_off": 0.66, "out_off": 1.98},
    "kimi-k3": {"in": 3.00, "out": 15.00, "in_off": 3.00, "out_off": 15.00},
}

_ROUTE_REASON = ""
_SPEND_CACHE = (0.0, 0.0)


def _is_peak(now=None):
    """DeepSeek peak hours: 01:00-04:00 and 06:00-10:00 UTC, Mon-Fri."""
    from datetime import datetime, timezone

    now = now or datetime.now(timezone.utc)
    if now.weekday() >= 5:
        return False
    return (1 <= now.hour < 4) or (6 <= now.hour < 10)


def _price_for(model):
    m = str(model or "").lower()
    if "kimi" in m or "moonshot" in m:
        return MODEL_PRICES["kimi-k3"]
    if "pro" in m:
        return MODEL_PRICES["deepseek-v4-pro"]
    if "flash" in m or m.startswith("deepseek"):
        return MODEL_PRICES["deepseek-flash"]
    return None  # local / unknown → free


def estimate_cost(model, in_tokens, out_tokens):
    """Estimated USD for a call, respecting peak/off-peak. 0.0 for local."""
    price = _price_for(model)
    if not price:
        return 0.0
    peak = _is_peak()
    rate_in = price["in"] if peak else price["in_off"]
    rate_out = price["out"] if peak else price["out_off"]
    return (
        int(in_tokens or 0) * rate_in + int(out_tokens or 0) * rate_out
    ) / 1_000_000


def _today_spend():
    """USD spent today per the telemetry ledger (cached 60 s)."""
    global _SPEND_CACHE
    now = time.time()
    if _SPEND_CACHE[0] and now - _SPEND_CACHE[0] < 60:
        return _SPEND_CACHE[1]
    total = 0.0
    try:
        _telemetry_init()
        conn = _telemetry_conn()
        row = conn.execute(
            "SELECT coalesce(sum(cost_usd), 0) FROM asks WHERE substr(ts, 1, 10) = ?",
            (time.strftime("%Y-%m-%d"),),
        ).fetchone()
        conn.close()
        total = float(row[0] or 0.0)
    except Exception:
        total = 0.0
    _SPEND_CACHE = (now, total)
    return total


def effective_synth_model():
    """The model the next automatic answer would use (for status display).

    Mirrors _route_model without the question context: offline → local synth,
    pinned synth_model wins, routing off → settings model, budget hit → flash,
    else the A/B-verdict default (flash).
    """
    settings = _load_settings()
    synth = str(settings.get("synth_model") or "").strip()
    if _offline():
        return "qwen"
    if synth:
        return synth
    if settings.get("routing", "hybrid") == "off":
        return settings.get("model") or ""
    try:
        budget = float(settings.get("daily_budget", 0) or 0)
    except Exception:
        budget = 0.0
    if budget > 0 and _today_spend() >= budget:
        return "deepseek-flash"
    return "deepseek-flash"


async def _route_model(question, force_deep=False):
    """Pick a model for this question, or None to use the default setting.

    Online: flash (V4.1) is the default answer tier — a 10-question A/B on
    this corpus showed it citing ~2× more sources, covering more books, 3×
    faster and 4× cheaper than pro, with unverifiable quotes flagged by the
    trust layer (see storage/ab_verdict.md). Pro stays available by pinning
    ``synth_model: deepseek-think`` or switching the model. ``routing: off``
    remains the escape hatch to the configured default model, and a positive
    ``daily_budget`` demotes to flash once today's ledger passes it.
    Offline, the choice maps to local models (qwen-deep = the big local
    reasoning model, qwen = the fast one); ``force_deep`` is set by the
    caller when the question needs reasoning across books.
    """
    global _ROUTE_REASON
    settings = _load_settings()
    routing = settings.get("routing", "hybrid")
    synth = str(settings.get("synth_model") or "").strip()
    try:
        budget = float(settings.get("daily_budget", 0) or 0)
    except Exception:
        budget = 0.0
    budget_hit = budget > 0 and _today_spend() >= budget
    if not _offline() and synth:
        resolved = resolve_model(synth)
        if (resolved.startswith("deepseek") and DEEPSEEK_API_KEY) or (
            ("kimi" in resolved or "moonshot" in resolved) and MOONSHOT_API_KEY
        ):
            _ROUTE_REASON = f"pinned synth_model={synth}"
            return synth
    if _offline():
        _ROUTE_REASON = "offline → local qwen3.8 (Gom Jabbar best local synth)"
        return "qwen"
    if routing == "off":
        _ROUTE_REASON = "routing off → settings model"
        return None
    if budget_hit:
        _ROUTE_REASON = f"daily budget ${budget:.2f} reached → flash"
        return "deepseek-flash"
    _ROUTE_REASON = "default flash tier (A/B verdict)"
    return "deepseek-flash"


def _offline():
    try:
        return bool(_load_settings().get("offline", False))
    except Exception:
        return False


async def query_llm(prompt, system_prompt=None, history_messages=None, **kwargs):
    if _offline():
        chosen = resolve_model(_ROUTE_OVERRIDE or "")
        local = chosen if chosen and "qwen" in chosen else OLLAMA_LLM_MODEL
        return await ollama_llm(
            prompt,
            system_prompt=system_prompt,
            history_messages=history_messages,
            local_model=local,
            **kwargs,
        )
    settings = _load_settings()
    chosen = resolve_model(_ROUTE_OVERRIDE or settings.get("model") or "")
    provider, base_url, api_key, wire = resolve_provider(chosen)
    if provider and api_key:
        heavy = ("pro" in wire.lower()) or provider == "moonshot"
        if not kwargs.get("max_tokens"):
            # Reasoning models spend tokens BEFORE writing content — starve
            # them and you get 30k chars of thought and an empty answer.
            kwargs["max_tokens"] = 32000 if heavy else 16000
        if not kwargs.get("timeout"):
            # A half-closed API connection must never hang a question:
            # synthesis gets 4 minutes, fast retries 90 seconds, then the
            # call fails over to local qwen.
            kwargs["timeout"] = 240 if heavy else 90
        try:
            return await remote_llm(
                prompt,
                system_prompt=system_prompt,
                history_messages=history_messages,
                model=wire,
                base_url=base_url,
                api_key=api_key,
                provider=provider,
                **kwargs,
            )
        except Exception as exc:
            _telemetry_log_feedback(
                "fallback", f"{chosen}: {str(exc)[:160]}", _current_conv_id()
            )
    return await ollama_llm(
        prompt,
        system_prompt=system_prompt,
        history_messages=history_messages,
        local_model=OLLAMA_LLM_MODEL,
        **kwargs,
    )


OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "30m")


_EMBED_QUERY_CACHE = {}


async def nomic_embed(texts, context="document", **kwargs):
    import ollama

    cache_key = None
    if context == "query" and texts:
        cache_key = tuple(str(t) for t in texts)
        hit = _EMBED_QUERY_CACHE.get(cache_key)
        if hit is not None:
            return hit
    prefixes = {"document": "search_document: ", "query": "search_query: "}
    prefix = prefixes.get(context)
    if prefix:
        texts = [prefix + text for text in texts]
    client = ollama.AsyncClient(host=OLLAMA_HOST, timeout=60)
    try:
        for attempt in (1, 2):
            try:
                data = await client.embed(
                    model=OLLAMA_EMBED_MODEL,
                    input=texts,
                    keep_alive=OLLAMA_KEEP_ALIVE,
                )
                result = np.array(data["embeddings"])
                if cache_key is not None:
                    if len(_EMBED_QUERY_CACHE) > 256:
                        _EMBED_QUERY_CACHE.clear()
                    _EMBED_QUERY_CACHE[cache_key] = result
                return result
            except Exception:
                if attempt == 2:
                    raise
                await asyncio.sleep(1.0)
    finally:
        await client._client.aclose()


# ---------------------------------------------------------------------------
# Librarian: search the ENTIRE index (semantic + keyword) so the reasoning
# model can recall passages across all books, not just a single top-k lookup.
# ---------------------------------------------------------------------------

_CHUNK_TEXTS = None


def _refresh_caches():
    """Drop in-memory caches so the next access re-reads from disk.

    Used by /refresh to pick up changes made outside the running app
    (a CLI index run, edited files, restored backups, etc.).
    """
    global _CHUNK_TEXTS, _KNOWN_NAMES, _VOCAB, _VOCAB_KEY
    _CHUNK_TEXTS = None
    try:
        _HUNT_CACHE.clear()
        _EMBED_QUERY_CACHE.clear()
    except Exception:
        pass
    _KNOWN_NAMES = None
    _VOCAB = None
    _VOCAB_KEY = None
    try:
        _fts_sync(force=True)
    except Exception:
        pass
    try:
        _vec_sync(force=True)
    except Exception:
        pass


LIBRARY_DB_PATH = STORAGE_DIR / "library.db"
_LIBRARY_DB = None
_STORE_STALE = False


def _check_store_version():
    """One-way gate: if the data was written by a NEWER build, mark the store
    stale so this process refuses to mutate it. Stamps the current version
    otherwise. Returns True when mutation is allowed."""
    global _STORE_STALE
    try:
        db = _library_db()
        row = db.execute("SELECT v FROM lib_meta WHERE k='code_version'").fetchone()
        data_ver = int(row[0]) if row else 0
    except Exception:
        data_ver = 0
    if data_ver > CODE_VERSION:
        _STORE_STALE = True
        return False
    try:
        db.execute(
            "INSERT OR REPLACE INTO lib_meta VALUES ('code_version', ?)",
            (str(CODE_VERSION),),
        )
        db.commit()
    except Exception:
        pass
    _STORE_STALE = False
    return True


def _store_ok():
    return not _STORE_STALE


def _library_db():
    global _LIBRARY_DB
    if _LIBRARY_DB is None:
        _LIBRARY_DB = sqlite3.connect(
            str(LIBRARY_DB_PATH), check_same_thread=False
        )
        _LIBRARY_DB.execute("PRAGMA journal_mode=WAL")
        _LIBRARY_DB.execute(
            "CREATE TABLE IF NOT EXISTS chunks ("
            "chunk_id TEXT PRIMARY KEY, file_path TEXT, book TEXT, "
            "chapter TEXT, seq INTEGER, content TEXT)"
        )
        _LIBRARY_DB.execute("CREATE INDEX IF NOT EXISTS idx_chunks_book ON chunks(book)")
        _LIBRARY_DB.execute(
            "CREATE TABLE IF NOT EXISTS spans ("
            "span_id TEXT PRIMARY KEY, chunk_id TEXT, file_path TEXT, book TEXT, "
            "chapter TEXT, seq INTEGER, start INTEGER, end INTEGER, text TEXT)"
        )
        _LIBRARY_DB.execute(
            "CREATE INDEX IF NOT EXISTS idx_spans_chunk ON spans(chunk_id)"
        )
        _LIBRARY_DB.execute(
            "CREATE INDEX IF NOT EXISTS idx_spans_book ON spans(book)"
        )
        _LIBRARY_DB.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS spans_fts "
            "USING fts5(span_id UNINDEXED, file_path, content)"
        )
        _LIBRARY_DB.execute(
            "CREATE TABLE IF NOT EXISTS lib_meta (k TEXT PRIMARY KEY, v TEXT)"
        )
        _LIBRARY_DB.commit()
    return _LIBRARY_DB


def _migrate_chunk_store():
    """One-time move of the chunk texts from the legacy JSON into library.db."""
    legacy = STORAGE_DIR / "kv_store_text_chunks.json"
    db = _library_db()
    try:
        n = db.execute("SELECT count(*) FROM chunks").fetchone()[0]
    except Exception:
        n = -1
    if n > 0 or not legacy.exists():
        return n
    try:
        raw = json.loads(legacy.read_text())
        rows = []
        for key, v in raw.items():
            fp = str(v.get("file_path", "unknown"))
            book = fp.split(" · ", 1)[0]
            ch = re.search(r"\(ch(\d+)\)", fp)
            chapter = ch.group(1) if ch else ""
            seq_m = re.search(r"-chunk-(\d+)$", str(key))
            seq = int(seq_m.group(1)) if seq_m else 0
            rows.append(
                (str(key), fp, book, chapter, seq, str(v.get("content", "")))
            )
        db.executemany(
            "INSERT OR IGNORE INTO chunks (chunk_id, file_path, book, chapter, seq, content) "
            "VALUES (?,?,?,?,?,?)",
            rows,
        )
        db.commit()
        return len(rows)
    except Exception:
        return -1


def _load_chunk_texts():
    """All indexed chunks (content + file_path), loaded once per process."""
    global _CHUNK_TEXTS
    if _CHUNK_TEXTS is None:
        n = _migrate_chunk_store()
        if n and n > 0:
            try:
                db = _library_db()
                rows = db.execute(
                    "SELECT chunk_id, file_path, content FROM chunks"
                ).fetchall()
                _CHUNK_TEXTS = [
                    {"chunk_id": r[0], "file_path": r[1], "content": r[2]}
                    for r in rows
                ]
                return _CHUNK_TEXTS
            except Exception:
                pass
        try:
            raw = json.loads((STORAGE_DIR / "kv_store_text_chunks.json").read_text())
            _CHUNK_TEXTS = [
                {
                    "chunk_id": key,
                    "file_path": str(v.get("file_path", "unknown")),
                    "content": str(v.get("content", "")),
                }
                for key, v in raw.items()
            ]
        except Exception:
            _CHUNK_TEXTS = []
    return _CHUNK_TEXTS


# ---------------------------------------------------------------------------
# Span index (v2) — paragraph/sentence granularity with char offsets, derived
# from the chunk store (no book re-extraction). Gives exact quote anchors and
# sentence-level recall for half-remembered phrases.
# ---------------------------------------------------------------------------

_SPAN_MAX_PARA = 1600


def _paragraph_spans(text, max_len=_SPAN_MAX_PARA):
    """(start, end, text) spans: paragraphs, long ones split at sentences."""
    text = str(text or "")
    spans = []

    def _emit(start, end, body):
        body = body.strip("\n")
        if not body.strip():
            return
        if len(body) <= max_len:
            spans.append((start, end, body))
            return
        for sm in re.finditer(r"[^.!?]*[.!?]+[\s\"'”’)\]]*|[^.!?]+$", body):
            seg = sm.group(0)
            if seg.strip():
                spans.append((start + sm.start(), start + sm.end(), seg))

    offset = 0
    buf_start = None
    buf = []
    for line in text.splitlines(keepends=True):
        if line.strip():
            if buf_start is None:
                buf_start = offset
            buf.append(line)
        else:
            if buf_start is not None:
                _emit(buf_start, offset, "".join(buf))
                buf_start, buf = None, []
        offset += len(line)
    if buf_start is not None:
        _emit(buf_start, offset, "".join(buf))
    return spans


def _build_spans(chunk_ids=None):
    """Erase and derive spans for the given chunks (or all). Returns rows written."""
    db = _library_db()
    if chunk_ids:
        ids = [str(c) for c in chunk_ids if c]
        if not ids:
            return 0
        ph = ",".join("?" * len(ids))
        db.execute(
            f"DELETE FROM spans_fts WHERE span_id IN "
            f"(SELECT span_id FROM spans WHERE chunk_id IN ({ph}))",
            ids,
        )
        db.execute(f"DELETE FROM spans WHERE chunk_id IN ({ph})", ids)
        rows = db.execute(
            f"SELECT chunk_id, file_path, book, chapter, seq, content FROM chunks "
            f"WHERE chunk_id IN ({ph})",
            ids,
        ).fetchall()
    else:
        db.execute("DELETE FROM spans_fts")
        db.execute("DELETE FROM spans")
        rows = db.execute(
            "SELECT chunk_id, file_path, book, chapter, seq, content FROM chunks"
        ).fetchall()
    n = 0
    lib_rows, fts_rows = [], []

    def _flush():
        nonlocal lib_rows, fts_rows
        if not lib_rows:
            return
        db.executemany(
            "INSERT OR REPLACE INTO spans VALUES (?,?,?,?,?,?,?,?,?)", lib_rows
        )
        db.executemany(
            "INSERT INTO spans_fts (span_id, file_path, content) VALUES (?,?,?)",
            fts_rows,
        )
        lib_rows, fts_rows = [], []

    for cid, fp, book, chapter, seq, content in rows:
        for si, (start, end, body) in enumerate(_paragraph_spans(content)):
            sid = f"{cid}-s{si:03d}"
            lib_rows.append((sid, cid, fp, book, chapter, seq, start, end, body))
            fts_rows.append((sid, fp, body))
            n += 1
        if len(lib_rows) >= 500:
            _flush()
    _flush()
    db.commit()
    return n


def _span_search(terms, limit=40):
    """Spans matching any term (BM25), with offsets and parent chunk id."""
    db = _library_db()
    q = " OR ".join('"' + str(t).replace('"', "") + '"' for t in terms if t)
    if not q:
        return []
    try:
        rows = db.execute(
            "SELECT spans.span_id, spans.chunk_id, spans.file_path, spans.start, "
            "spans.end, spans.text FROM spans_fts "
            "JOIN spans ON spans.span_id = spans_fts.span_id "
            "WHERE spans_fts MATCH ? ORDER BY bm25(spans_fts) LIMIT ?",
            (q, limit),
        ).fetchall()
    except Exception:
        return []
    return [
        {
            "span_id": r[0],
            "chunk_id": r[1],
            "file_path": r[2],
            "start": r[3],
            "end": r[4],
            "text": r[5],
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Keyword index (sqlite FTS5) — replaces the O(N) substring scan, so keyword
# search stays instant no matter how many books are added.
# ---------------------------------------------------------------------------

_FTS_DB = None


def _fts_db():
    import sqlite3

    global _FTS_DB
    if _FTS_DB is None:
        _FTS_DB = sqlite3.connect(
            str(STORAGE_DIR / "fts.db"), check_same_thread=False
        )
        _FTS_DB.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts "
            "USING fts5(chunk_id UNINDEXED, file_path, content)"
        )
        _FTS_DB.execute(
            "CREATE TABLE IF NOT EXISTS fts_meta (k TEXT PRIMARY KEY, v TEXT)"
        )
    return _FTS_DB


def _fts_current_digest():
    """The digest the FTS index WOULD have if it mirrored the chunk store."""
    chunks = _load_chunk_texts()
    if not chunks:
        return ""
    store_path = LIBRARY_DB_PATH
    try:
        store_mtime = store_path.stat().st_mtime
    except Exception:
        store_mtime = 0
    return "%d|%s|%s|%s" % (
        len(chunks),
        chunks[0]["chunk_id"],
        chunks[-1]["chunk_id"],
        store_mtime,
    )


def _fts_sync(force=False):
    """(Re)build the FTS index when the chunk store changed. Cheap at any scale.

    Incremental changes go through ``_fts_patch`` (per-document deletes and
    inserts) so ingestion stays linear; the full rebuild here is the safety
    net for digest mismatches and one-shot repairs.
    """
    chunks = _load_chunk_texts()
    if not chunks:
        return
    digest = _fts_current_digest()
    db = _fts_db()
    try:
        cur = db.execute("SELECT v FROM fts_meta WHERE k='chunks_digest'").fetchone()
        if not force and cur and cur[0] == digest:
            return
        db.execute("DELETE FROM chunks_fts")
        db.executemany(
            "INSERT INTO chunks_fts (chunk_id, file_path, content) VALUES (?,?,?)",
            [(c["chunk_id"], c["file_path"], c["content"]) for c in chunks],
        )
        db.execute("INSERT OR REPLACE INTO fts_meta VALUES ('chunks_digest', ?)", (digest,))
        db.commit()
    except Exception:
        pass


def _fts_patch(insert_rows=(), delete_prefixes=()):
    """Incremental FTS maintenance for one document (or a few).

    Deletes the chunks of each ``delete_prefix`` (a doc id, e.g.
    ``doc-<md5>-chunk-`` prefix minus the trailing ``-chunk-``) and inserts
    ``insert_rows`` of (chunk_id, file_path, content). Keeps the digest fresh
    so a later ``_fts_sync()`` is a no-op.
    """
    db = _fts_db()
    try:
        for prefix in delete_prefixes or ():
            if prefix:
                db.execute(
                    "DELETE FROM chunks_fts WHERE chunk_id LIKE ?",
                    (str(prefix) + "-chunk-%",),
                )
        if insert_rows:
            db.executemany(
                "INSERT OR REPLACE INTO chunks_fts (chunk_id, file_path, content) "
                "VALUES (?,?,?)",
                list(insert_rows),
            )
        digest = _fts_current_digest()
        db.execute("INSERT OR REPLACE INTO fts_meta VALUES ('chunks_digest', ?)", (digest,))
        db.commit()
    except Exception:
        pass


def _fts_search(terms, limit=30):
    """Chunk ids matching any term, ordered by BM25 relevance."""
    db = _fts_db()
    q = " OR ".join('"' + t.replace('"', "") + '"' for t in terms if t)
    if not q:
        return []
    try:
        rows = db.execute(
            "SELECT chunk_id FROM chunks_fts WHERE chunks_fts MATCH ? "
            "ORDER BY bm25(chunks_fts) LIMIT ?",
            (q, limit),
        ).fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []


def _fts_search_and(terms, limit=30):
    """Chunk ids containing ALL terms (e.g. 'mercy' AND 'dune')."""
    db = _fts_db()
    q = " AND ".join('"' + t.replace('"', "") + '"' for t in terms if t)
    if not q or " AND " not in q:
        return []
    try:
        rows = db.execute(
            "SELECT chunk_id FROM chunks_fts WHERE chunks_fts MATCH ? "
            "ORDER BY bm25(chunks_fts) LIMIT ?",
            (q, limit),
        ).fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []


def _fts_count(term):
    """How many chunks contain a term (for rarity-weighted ranking)."""
    db = _fts_db()
    try:
        row = db.execute(
            "SELECT count(*) FROM chunks_fts WHERE chunks_fts MATCH ?",
            ('"' + str(term).replace('"', "") + '"',),
        ).fetchone()
        return row[0] if row else 0
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Persistent vector store (SQLite-vec) — on-disk, restart-safe, incremental.
# Imports vectors from LightRAG's nano-vectordb JSON once, then serves the
# librarian's semantic search. Scales with more books without whole-file
# rewrites or full reloads.
# ---------------------------------------------------------------------------

_VEC_DB = None


def _vec_db():
    import sqlite3
    import sqlite_vec

    global _VEC_DB
    if _VEC_DB is None:
        _VEC_DB = sqlite3.connect(str(STORAGE_DIR / "vec.db"), check_same_thread=False)
        _VEC_DB.enable_load_extension(True)
        sqlite_vec.load(_VEC_DB)
        _VEC_DB.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec "
            "USING vec0(chunk_id TEXT PRIMARY KEY, "
            "embedding float[%d] distance_metric=cosine)" % EMBED_DIM
        )
        _VEC_DB.execute("CREATE TABLE IF NOT EXISTS vec_meta (k TEXT PRIMARY KEY, v TEXT)")
    return _VEC_DB


def _vec_sync(force=False):
    """Vector table sanity: one-time legacy build if empty, else verify count."""
    db = _vec_db()
    try:
        n = db.execute("SELECT count(*) FROM chunks_vec").fetchone()[0]
    except Exception:
        n = 0
    if n > 0:
        return
    import base64

    try:
        raw = json.loads((STORAGE_DIR / "vdb_chunks.json").read_text())
    except Exception:
        return
    data = raw.get("data") or []
    if not data:
        return
    try:
        mat = None
        buf = base64.b64decode(raw.get("matrix") or "")
        mat = np.frombuffer(buf, dtype=np.float32).reshape(len(data), EMBED_DIM)
        rows = [
            (str(data[i].get("__id__", "")), mat[i].astype(np.float32).tobytes())
            for i in range(len(data))
        ]
        db.executemany(
            "INSERT OR IGNORE INTO chunks_vec (chunk_id, embedding) VALUES (?, ?)", rows
        )
        db.commit()
    except Exception:
        pass


def _vec_insert_many(ids, embeddings):
    db = _vec_db()
    rows = [
        (str(cid), np.asarray(e, dtype=np.float32).reshape(-1).tobytes())
        for cid, e in zip(ids, embeddings)
    ]
    db.executemany(
        "INSERT OR REPLACE INTO chunks_vec (chunk_id, embedding) VALUES (?, ?)", rows
    )
    db.commit()


def _vec_delete_many(ids):
    if not ids:
        return
    db = _vec_db()
    ph = ",".join("?" * len(ids))
    db.execute(f"DELETE FROM chunks_vec WHERE chunk_id IN ({ph})", list(ids))
    db.commit()


def _vec_search(embedding, k=10):
    """Chunk ids nearest to the embedding, ordered by cosine distance."""
    try:
        emb = np.asarray(embedding, dtype=np.float32).reshape(-1)
        if emb.shape[0] != EMBED_DIM:
            return []
        db = _vec_db()
        rows = db.execute(
            "SELECT chunk_id FROM chunks_vec WHERE embedding MATCH ? AND k = ?",
            (emb.tobytes(), k),
        ).fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Enrichment (v2) — contextual retrieval: each chunk is embedded together with
# a short context line (book · chapter · what the passage is about), which
# sharpens vague-query recall. Contexts are deterministic first, then
# optionally upgraded by the fast model; embeddings are rebuilt into a
# SEPARATE vec db file and swapped atomically, so an interrupted run can never
# leave search with a half-built index.
# ---------------------------------------------------------------------------

ENRICH_CONTEXTS_PATH = STORAGE_DIR / "enrich_contexts.jsonl"


def _deterministic_context(chunk):
    """A stable locator line derived from metadata (no LLM)."""
    fp = str(chunk.get("file_path") or "")
    display = _clean_name(fp)
    head = re.sub(r"\s+", " ", str(chunk.get("content") or "")[:160]).strip()
    return f"{display} — {head}" if head else display


def _build_contexts(force=False):
    """Append deterministic contexts for every chunk not already covered."""
    known = {}
    if not force and ENRICH_CONTEXTS_PATH.exists():
        try:
            for line in ENRICH_CONTEXTS_PATH.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                if row.get("chunk_id"):
                    known[row["chunk_id"]] = row
        except Exception:
            known = {}
    added = 0
    try:
        with open(ENRICH_CONTEXTS_PATH, "a", encoding="utf-8") as fh:
            for c in _load_chunk_texts():
                cid = c["chunk_id"]
                if cid in known:
                    continue
                fh.write(
                    json.dumps(
                        {
                            "chunk_id": cid,
                            "context": _deterministic_context(c),
                            "source": "deterministic",
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                added += 1
    except Exception:
        return added
    return added


def _load_contexts():
    """chunk_id -> context line (later rows win, so llm upgrades override)."""
    contexts = {}
    try:
        for line in ENRICH_CONTEXTS_PATH.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            cid, ctx = row.get("chunk_id"), row.get("context")
            if cid and ctx:
                contexts[cid] = str(ctx)
    except Exception:
        pass
    return contexts


async def _llm_contexts(batch_size=20, limit=None, progress=None):
    """Upgrade contexts with one model-written locator per chunk (resumable).

    Batches run concurrently (bounded) — the fast model handles parallel
    requests, and each finished batch is appended with an '[llm] ' marker, so
    an interrupted run resumes exactly where it stopped.
    """
    if _offline():
        return 0
    contexts = _load_contexts()
    pending = [
        c for c in _load_chunk_texts()
        if not str(contexts.get(c["chunk_id"], "")).startswith("[llm]")
    ]
    if limit:
        pending = pending[:limit]
    batches = [
        pending[i : i + batch_size] for i in range(0, len(pending), batch_size)
    ]
    if not batches:
        return 0
    sem = asyncio.Semaphore(12)
    lock = asyncio.Lock()
    done = 0

    async def _one(batch):
        nonlocal done
        listing = "\n\n".join(
            f"[{c['chunk_id']}]\n{str(c.get('content') or '')[:600]}" for c in batch
        )
        prompt = (
            "For each passage below write ONE short locating line for search: "
            "book/author if visible, chapter marker, and what happens or which "
            "idea it develops. Plain text, ≤25 words. Return ONLY a JSON array "
            'of objects [{"id": "...", "context": "..."}].\n\n' + listing
        )
        async with sem:
            raw = None
            if DEEPSEEK_API_KEY:
                for _attempt in (1, 2):
                    try:
                        raw = await deepseek_llm(
                            prompt, model=DEEPSEEK_FLASH_MODEL, max_tokens=3000
                        )
                        if raw:
                            break
                    except Exception:
                        raw = None
            if raw is None:
                try:
                    raw = await _fast_llm(prompt)
                except Exception:
                    raw = None
        parsed = _extract_json_list(raw or "")
        rows = []
        if isinstance(parsed, list):
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                cid = str(item.get("id") or "").strip()
                ctx = str(item.get("context") or "").strip()
                if cid and ctx:
                    rows.append((cid, ctx))
        if not rows:
            rows = [(c["chunk_id"], _deterministic_context(c)) for c in batch]
        async with lock:
            try:
                with open(ENRICH_CONTEXTS_PATH, "a", encoding="utf-8") as fh:
                    for cid, ctx in rows:
                        fh.write(
                            json.dumps(
                                {
                                    "chunk_id": cid,
                                    "context": "[llm] " + ctx,
                                    "source": "llm",
                                },
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
            except Exception:
                pass
            done += len(rows)
            if progress:
                progress(done, len(pending))

    await asyncio.gather(*[_one(b) for b in batches])
    return done


async def _build_enriched_vec(progress=None):
    """Embed context+text for every chunk into a temp vec db, then swap.

    The live vec.db is replaced only after the temp file is complete, so
    search never sees a half-built index; the previous file is kept as
    vec.db.bak for rollback.
    """
    import os as _os

    import sqlite_vec

    contexts = _load_contexts()
    chunks = _load_chunk_texts()
    if not chunks:
        return {"ok": False, "reason": "no chunks"}
    tmp_path = STORAGE_DIR / "vec_enriched.db"
    try:
        if tmp_path.exists():
            tmp_path.unlink()
    except Exception:
        pass
    db = sqlite3.connect(str(tmp_path))
    n = 0
    try:
        db.enable_load_extension(True)
        sqlite_vec.load(db)
        db.execute(
            "CREATE VIRTUAL TABLE chunks_vec USING vec0(chunk_id TEXT PRIMARY KEY, "
            "embedding float[%d] distance_metric=cosine)" % EMBED_DIM
        )
        db.execute("CREATE TABLE vec_meta (k TEXT PRIMARY KEY, v TEXT)")
        for start in range(0, len(chunks), 20):
            batch = chunks[start : start + 20]
            texts = []
            for c in batch:
                ctx = contexts.get(c["chunk_id"], "")
                body = str(c.get("content") or "")
                texts.append((ctx + "\n" + body) if ctx else body)
            emb = await nomic_embed(texts, context="document")
            rows = [
                (
                    str(c["chunk_id"]),
                    np.asarray(e, dtype=np.float32).reshape(-1).tobytes(),
                )
                for c, e in zip(batch, emb)
            ]
            db.executemany(
                "INSERT OR REPLACE INTO chunks_vec (chunk_id, embedding) VALUES (?, ?)",
                rows,
            )
            n += len(rows)
            if n % 400 == 0:
                db.commit()
                if progress:
                    progress(n, len(chunks))
        db.execute("INSERT OR REPLACE INTO vec_meta VALUES ('enriched', ?)", (str(n),))
        db.execute(
            "INSERT OR REPLACE INTO vec_meta VALUES ('embed_model', ?)",
            (OLLAMA_EMBED_MODEL,),
        )
        db.execute(
            "INSERT OR REPLACE INTO vec_meta VALUES ('embed_dim', ?)", (str(EMBED_DIM),)
        )
        db.commit()
    finally:
        db.close()
    live = STORAGE_DIR / "vec.db"
    if live.exists():
        backup = STORAGE_DIR / "vec.db.bak"
        try:
            if backup.exists():
                backup.unlink()
            _os.replace(str(live), str(backup))
        except Exception:
            pass
    _os.replace(str(tmp_path), str(live))
    global _VEC_DB
    try:
        if _VEC_DB is not None:
            _VEC_DB.close()
    except Exception:
        pass
    _VEC_DB = None
    return {"ok": True, "embedded": n}


# ---------------------------------------------------------------------------
# Entity graph (v2) — deterministic co-occurrence over the chunk store: which
# names/ideas appear together, in which books. Powers `brain graph "Fremen"`
# and gives cross-book synthesis a concept map without any LLM extraction.
# ---------------------------------------------------------------------------

GRAPH_DB_PATH = STORAGE_DIR / "graph.db"
_GRAPH_DB = None
_GRAPH_STOP = frozenset(
    {
        "the", "this", "that", "these", "those", "there", "then", "than",
        "and", "but", "for", "nor", "yet", "so", "however", "therefore",
        "chapter", "part", "book", "volume", "appendix", "contents", "index",
        "note", "notes", "page", "pages", "figure", "table", "ibid",
        "january", "february", "march", "april", "may", "june", "july",
        "august", "september", "october", "november", "december",
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
        "sunday", "god", "lord",
        # pronouns and question words that only look like names
        "i", "you", "he", "she", "it", "we", "they", "me", "him", "her",
        "us", "them", "my", "your", "his", "its", "our", "their", "mine",
        "yours", "hers", "ours", "theirs", "himself", "herself", "itself",
        "myself", "yourself", "ourselves", "themselves",
        "what", "when", "where", "who", "whom", "whose", "why", "how",
        "which", "whatever", "whoever", "whenever", "wherever", "however",
        "yes", "no", "well", "now", "oh", "ah", "eh", "hmm",
    }
)
_ENTITY_RE = re.compile(r"\b([A-Z][A-Za-z'’-]{2,}(?:\s+[A-Z][A-Za-z'’-]{2,}){0,3})\b")


def _graph_db():
    global _GRAPH_DB
    if _GRAPH_DB is None:
        _GRAPH_DB = sqlite3.connect(str(GRAPH_DB_PATH), check_same_thread=False)
        _GRAPH_DB.execute("PRAGMA journal_mode=WAL")
        _GRAPH_DB.execute(
            "CREATE TABLE IF NOT EXISTS entities "
            "(name TEXT PRIMARY KEY, display TEXT, kind TEXT, count INTEGER)"
        )
        _GRAPH_DB.execute(
            "CREATE TABLE IF NOT EXISTS mentions "
            "(entity TEXT, chunk_id TEXT, file_path TEXT, book TEXT)"
        )
        _GRAPH_DB.execute(
            "CREATE INDEX IF NOT EXISTS idx_mentions_entity ON mentions(entity)"
        )
        _GRAPH_DB.execute(
            "CREATE TABLE IF NOT EXISTS edges "
            "(a TEXT, b TEXT, count INTEGER, PRIMARY KEY (a, b))"
        )
        _GRAPH_DB.commit()
    return _GRAPH_DB


def _chunk_entities(text):
    """Capitalized name phrases in one chunk, deduped, order preserved."""
    out, seen = [], set()
    for m in _ENTITY_RE.finditer(str(text or "")):
        phrase = m.group(1).strip()
        words = phrase.split()
        if len(words) > 1 and words[0].lower() in ("the", "a", "an"):
            words = words[1:]
            phrase = " ".join(words)
        low = phrase.lower()
        if not low or low in _GRAPH_STOP or low in seen:
            continue
        seen.add(low)
        out.append((low, phrase))
    return out


def _build_graph(progress=None):
    """Rebuild entities/mentions/edges from the chunk store. Returns counts."""
    db = _graph_db()
    db.execute("DELETE FROM entities")
    db.execute("DELETE FROM mentions")
    db.execute("DELETE FROM edges")
    counts, display = {}, {}
    mention_rows, edge_counts = [], {}
    seen_chunks = 0

    def _flush():
        nonlocal mention_rows
        if mention_rows:
            db.executemany(
                "INSERT INTO mentions VALUES (?,?,?,?)", mention_rows
            )
            mention_rows = []

    for c in _load_chunk_texts():
        ents = _chunk_entities(c.get("content"))
        uniq = []
        for low, phrase in ents:
            if low not in uniq:
                uniq.append(low)
            display.setdefault(low, phrase)
        book = _book_key(c.get("file_path", ""))
        for low in uniq[:16]:
            counts[low] = counts.get(low, 0) + 1
            mention_rows.append((low, c["chunk_id"], c.get("file_path", ""), book))
        top = uniq[:12]
        for i in range(len(top)):
            for j in range(i + 1, len(top)):
                a, b = sorted((top[i], top[j]))
                edge_counts[(a, b)] = edge_counts.get((a, b), 0) + 1
        seen_chunks += 1
        if seen_chunks % 2000 == 0:
            _flush()
            db.commit()
            if progress:
                progress(seen_chunks)
    _flush()
    keep = {k for k, v in counts.items() if v >= 3}
    db.executemany(
        "INSERT OR REPLACE INTO entities VALUES (?,?,?,?)",
        [(k, display.get(k, k), "name", v) for k, v in counts.items() if k in keep],
    )
    db.executemany(
        "INSERT OR REPLACE INTO edges VALUES (?,?,?)",
        [(a, b, v) for (a, b), v in edge_counts.items() if v >= 3 and a in keep and b in keep],
    )
    db.commit()
    return {
        "chunks": seen_chunks,
        "entities": len(keep),
        "edges": sum(1 for (a, b), v in edge_counts.items() if v >= 3 and a in keep and b in keep),
    }


def _graph_related(entity, limit=15):
    """Co-occurring entities + the books where ``entity`` appears."""
    db = _graph_db()
    low = str(entity or "").strip().lower()
    if not low:
        return {"entity": "", "count": 0, "related": [], "books": []}
    row = db.execute("SELECT count FROM entities WHERE name = ?", (low,)).fetchone()
    related = db.execute(
        "SELECT CASE WHEN a = ? THEN b ELSE a END AS other, count FROM edges "
        "WHERE a = ? OR b = ? ORDER BY count DESC LIMIT ?",
        (low, low, low, limit),
    ).fetchall()
    books = db.execute(
        "SELECT book, count(*) FROM mentions WHERE entity = ? "
        "GROUP BY book ORDER BY 2 DESC LIMIT 8",
        (low,),
    ).fetchall()
    names = {}
    if related:
        others = [r[0] for r in related]
        ph = ",".join("?" * len(others))
        for name, disp in db.execute(
            f"SELECT name, display FROM entities WHERE name IN ({ph})", others
        ):
            names[name] = disp
    return {
        "entity": low,
        "count": row[0] if row else 0,
        "related": [(names.get(o, o), c) for o, c in related],
        "books": books,
    }


def _pretty_book(name):
    """Humanize a graph book label (a raw filename) for the prompt block."""
    s = re.sub(r"\.(epub|pdf|txt|md|mobi|azw3)$", "", str(name or ""), flags=re.I)
    s = s.replace("_", " ").replace("(", " (")
    return re.sub(r"\s+", " ", s).strip()


_GRAPH_QUERY_STOP = frozenset(
    {
        "compare", "contrast", "concept", "concepts", "across", "books", "book",
        "theme", "themes", "connect", "connection", "connections", "between",
        "share", "shared", "shares", "what", "which", "how", "does", "do",
        "say", "says", "said", "about", "explain", "analyze", "analyse",
        "discuss", "relate", "relationship", "common", "similar", "difference",
        "differences", "means", "mean", "work", "works", "author", "text",
        "texts", "idea", "ideas", "library", "passage", "passages", "quote",
        "quotes", "series", "whole", "entire", "thinker", "thinkers",
        "philosopher", "philosophy", "novel", "novels", "chapter", "chapters",
    }
)


def _graph_block(question, passages=None, limit=5):
    """Deterministic cross-book entity map for compare/universal questions.

    The entity graph (entities/edges/mentions) was previously reachable only
    through the MCP tool; this feeds it into the answer prompt so cross-book
    questions get the connections the corpus actually contains instead of
    relying on the model to rediscover them. Prompt-only — no extra model
    calls.

    The graph resolves entities by name only, so common names collide across
    corpora ("Paul" is both the apostle and Muad'Dib). Results are therefore
    scoped to the books actually retrieved: an entity is only shown if it
    occurs in one of them, and its listed books are restricted to that scope,
    so a Dune question never sees the Bible's Paul. Off by default: the graph
    resolves entities by name only, and A/B testing showed it neutral-to-noisy
    versus the library map, so it stays opt-in via MENTAT_GRAPH=1 until entity
    resolution is corpus-scoped.
    """
    if not os.getenv("MENTAT_GRAPH"):
        return ""
    scope = set()
    for p in passages or []:
        try:
            key = _book_key(p.get("file_path", ""))
            if key:
                scope.add(key)
        except Exception:
            pass
    cands, seen = [], set()

    def _add(term):
        low = str(term or "").strip().lower()
        if (
            len(low) < 4
            or low in seen
            or low in _GRAPH_QUERY_STOP
            or low in _GRAPH_STOP
        ):
            return
        seen.add(low)
        cands.append(low)

    for m in _ENTITY_RE.finditer(str(question or "")):
        _add(m.group(1))  # multi-word proper nouns ("Ibn Khaldun")
    try:
        for t in _derive_terms(question, cap=10):
            _add(t)
    except Exception:
        pass
    rows = []
    for low in cands:
        if len(rows) >= 4:
            break
        try:
            r = _graph_related(low, limit=max(limit, 8))
        except Exception:
            continue
        if not r.get("count"):
            continue
        if scope:
            all_books = r.get("books") or []
            scoped = [(b, c) for b, c in all_books if b in scope]
            if not scoped:
                continue  # entity only lives outside the retrieved books
            total = r.get("count") or 1
            if sum(c for _, c in scoped) / max(total, 1) < 0.7:
                continue  # name collides across corpora (e.g. biblical "Paul")
            r["books"] = scoped
        rows.append(r)
    if not rows:
        return ""
    lines = [
        "\n\nEntity map from the library (deterministic co-occurrence data — "
        "use it to connect texts and locate material; it is NOT a source of "
        "quotes):"
    ]
    for r in rows:
        rel = ", ".join(f"{n} ({c})" for n, c in (r.get("related") or [])[:limit])
        books = ", ".join(
            f"{_pretty_book(b)} ({c})" for b, c in (r.get("books") or [])[:4]
        )
        lines.append(
            f"- {_escape_format(r['entity'])} — {r['count']} mentions"
            + (f"; co-occurs with {rel}" if rel else "")
            + (f"; appears in {books}" if books else "")
        )
    return "\n".join(lines)


def _normalize_query(text):
    """Strip accents so 'Kojève' becomes 'Kojeve' (term matching is ASCII)."""
    import unicodedata

    normalized = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in normalized if not unicodedata.combining(c))


# ---------------------------------------------------------------------------
# Front/back-matter detection — keeps retrieval on the story/text itself and
# out of forewords, afterwords, praise pages and publisher boilerplate.
# ---------------------------------------------------------------------------

_BOILER_HEADINGS = (
    "praise for", "contents", "table of contents", "about the author",
    "other books by", "other books of", "also by", "the dune chronicles by",
    "books by", "novels by", "copyright", "dedication", "acknowledg",
    "afterword", "introduction", "foreword", "maps", "glossary", "appendix",
    "terminology of", "cartographic", "when i was writing", "reading list",
    "what's next", "bibliograph", "selected excerpts", "almanak",
    "report on bene gesserit", "family tree", "dramatis personae",
    "cast of characters", "timeline", "chronolog", "map of", "about the series",
)
_BOILER_SIGNALS = (
    "praise for the dune chronicles", "z-library", "libgen", "a division of",
    "simon & schuster", "ace books", "berkley", "penguin", "g. p. putnam",
    "www.", "http", "all rights reserved", "isbn", "los angeles times",
    "kirkus reviews", "new york times", "wall street journal",
    "national public radio", "translated by", "compiled by",
    "washington post", "louisville times", "galaxy magazine", "milwaukee",
    "challenging destiny", "herald examiner", "publishers weekly",
    "next on your reading list", "what's next on your reading list",
    "reading group guide", "a beginning is a delicate time",
)


def _norm_label(text):
    """Lowercased, single-spaced label (markers often arrive as 'OFTHE')."""
    return re.sub(r"\s+", " ", str(text or "").replace("’", "'").replace("‘", "'")).strip().lower()


def _boiler_section_of(marker):
    """The front/back-matter section a marker belongs to ('', if it is story).

    Checks the epub spine label itself ('TERMINOLOGY OFTHE IMPERIUM',
    'APPENDIX III:...', "What's next on your reading list?") — retrieval and
    censuses use this so appendices, glossaries, praise pages and publisher
    tail matter never masquerade as chapters.
    """
    low = _norm_label(marker)
    if not low:
        return ""
    for s in _BOILER_HEADINGS:
        if low == s or low.startswith(s):
            return s
    return ""


def _is_boilerplate(content, query_sections=(), file_path=""):
    """True if a chunk is front/back-matter (unless the user asked for it)."""
    fp = str(file_path or "")
    marker = fp.split(" · ", 1)[1] if " · " in fp else ""
    sec = _boiler_section_of(marker)
    if sec:
        return sec not in query_sections
    head = (content or "").lstrip()[:400].lower()
    m = re.match(r"##\s*([^\n]{2,60})", head)
    heading = m.group(1).strip() if m else ""
    for s in _BOILER_HEADINGS:
        if heading == s or heading.startswith(s):
            return s not in query_sections
    hits = sum(1 for sig in _BOILER_SIGNALS if sig in head)
    return hits >= 2


def _query_sections(query):
    """Front/back-matter section names the user explicitly asked about."""
    q = _normalize_query(query or "").lower()
    return [s for s in _BOILER_HEADINGS if s in q]


def _heuristic_kind(question):
    """Deterministic question register (offline-safe) — the fallback that also
    gates the tests. Kinds: count | quotes | concept | compare | commentary |
    research. The front-end classifier refines this online."""
    q = str(question or "").lower()
    if not q.strip():
        return "research"
    if _has_census_intent(question):
        return "count"
    if _has_hunt_intent(question) or any(
        w in q
        for w in ("quote", "quotes", "passage", "exact words", "verbatim",
                  "litany", "poem", "verse", "recite")
    ):
        return "quotes"
    if re.search(
        r"\bwhat (?:does|do|is|are|was|were) (?:the )?(?:word|term|name|phrase|"
        r"expression|concept|meaning)\b|\bmeaning of\b|\bdefine\b|"
        r"\bdefinitions? of\b|\bwhat does .{1,48} mean\b|\bwho (?:is|was|are|were)\b|"
        r"\bwhat is (?:a|an|the) \w+",
        q,
    ):
        return "concept"
    if re.search(
        r"\bcompare\b|\bcontrast\b|\bversus\b|\bvs\.?\b|\brelationship between\b", q
    ):
        return "compare"
    if re.search(
        r"\bwhy\b|\binterpret|\bsignifican|\bimplications?\b|\btheme",
        q,
    ):
        return "commentary"
    return "research"


def _question_kind(question):
    """The classifier's kind when present, else the deterministic heuristic."""
    an_kind = str(_analysis(question).get("kind") or "").strip().lower()
    if an_kind in ("count", "quotes", "concept", "compare", "commentary", "research"):
        return an_kind
    return _heuristic_kind(question)


_APPARATUS_SECTIONS = (
    "terminology of", "glossary", "appendix", "dramatis personae",
    "cast of characters", "family tree",
)


def _sections_for_kind(question, kind):
    """Apparatus sections a question's register licenses.

    Definitions and analysis live in glossaries and appendices, so concept and
    commentary questions may retrieve them (labelled as front/back matter).
    Verbatim and count questions stay on story text unless the user asked.
    """
    sections = list(_query_sections(question))
    if kind in ("concept", "commentary"):
        sections += [s for s in _APPARATUS_SECTIONS if s not in sections]
    return sections


_KNOWN_NAMES = None


def _known_names():
    """All author/book/title words from the manifest + library map, lowercased."""
    global _KNOWN_NAMES
    if _KNOWN_NAMES is None:
        names = set()
        for rel in _load_manifest():
            for part in _clean_name(rel).split("/"):
                for w in re.findall(r"[a-zA-Z]{3,}", part):
                    low = w.lower()
                    if low not in _SEARCH_STOPWORDS and low not in _TITLE_STOPWORDS:
                        names.add(low)
        mp = _load_library_map()
        for info in mp.get("books", {}).values():
            hay = (info.get("title", "") + " " + " ".join(info.get("concepts", [])))
            for w in re.findall(r"[a-zA-Z]{3,}", hay):
                low = w.lower()
                if low not in _SEARCH_STOPWORDS and low not in _TITLE_STOPWORDS:
                    names.add(low)
        _KNOWN_NAMES = names
    return _KNOWN_NAMES


def _resolve_name(term):
    """Map a term to a known book/author name, or None.

    Handles misspellings ('stallin' -> 'stalin', 'huds0n' -> 'hudson') via
    edit-distance against the library's actual names, so the string layer
    stops being the thing that loses your books. A term that already hits the
    index as written is NEVER rewritten — correctly-spelled words must not be
    conflated with look-alike title words ("instance" is not "finance").
    """
    names = _known_names()
    if term in names:
        return term
    try:
        if _fts_count(term) > 0:
            return None
    except Exception:
        pass
    match = difflib.get_close_matches(term, names, n=1, cutoff=0.8)
    return match[0] if match else None


def _clean_term(word):
    """Strip possessive endings so 'hudson's' and 'communists'' match 'hudson'/'communists'."""
    w = word
    if w.endswith("'s"):
        w = w[:-2]
    elif w.endswith("'"):
        w = w[:-1]
    return w


def _fix_vocab_spelling(term):
    """Spelling rescue for a retrieval term, VERIFIED against the index.

    A term is only rewritten when it matches nothing as written and one very
    close vocabulary word does — so a correctly-spelled word that merely
    resembles a library word ("instances" -> "finance", which sits in a title)
    is never touched. Book/author-name typos are already handled upstream by
    ``_resolve_name`` against the names list, so this stage never invents a
    book-name match either.
    """
    if len(term) < 3 or "'" in term or "-" in term:
        return term
    vocab = _library_vocab()
    if term in vocab:
        return term
    try:
        if _fts_count(term) > 0:
            return term
    except Exception:
        return term
    try:
        if _books_matching(term):
            return term
    except Exception:
        return term
    try:
        cand = difflib.get_close_matches(term, vocab, n=3, cutoff=0.84)
    except Exception:
        return term
    # typos keep the first letter ("eys" -> "eyes", never "keys")
    cand = [c for c in cand if c[:1] == term[:1]]
    if not cand or cand[0] == term:
        return term
    fixed = cand[0]
    try:
        if _books_matching(fixed) or _fts_count(fixed) == 0:
            return term
    except Exception:
        return term
    return fixed


def _derive_terms(question, cap=8):
    """Distinctive search terms: quoted phrases, proper nouns, rare words (lowercased)."""
    q = _normalize_query(question)
    terms = [_clean_term(m.strip().lower()) for m in re.findall(r"[\"“”‘]([^\"“”‘]{2,})[\"“”‘]", q)]
    for m in re.findall(r"\b[A-Z][A-Za-z'-]{2,}\b", q):
        low = _clean_term(m.lower())
        if low not in terms and not _SEARCH_STOPWORDS.intersection([low]):
            terms.append(low)
    seen = set()
    for w in re.findall(r"[a-z][a-z'-]{3,}", q.lower()):
        w = _clean_term(w)
        if w in _SEARCH_STOPWORDS or w in seen:
            continue
        seen.add(w)
        terms.append(w)
    terms = [_resolve_name(t) or t for t in terms]
    # vocabulary-level typo rescue for bare words (phrases are handled by the
    # census spelling layer, which verifies each fix by counting).
    terms = [(_fix_vocab_spelling(t) if " " not in t else t) for t in terms]
    return list(dict.fromkeys(t for t in terms if t))[:cap]


_BOOK_MAP = None


def _book_key(file_path):
    """Normalized book identity from a passage file_path ('Book · Chapter 1 (ch1)')."""
    return re.sub(r"\s+", "", _clean_name(str(file_path).split(" · ")[0]).replace("/", " › ")).lower()


def _book_map():
    """book key -> {"raw": display name, "chunks": [...], "ids": {chunk_ids}}."""
    global _BOOK_MAP
    if _BOOK_MAP is None:
        m = {}
        for c in _load_chunk_texts():
            fp = str(c.get("file_path") or "")
            key = _book_key(fp)
            raw = _clean_name(fp.split(" · ")[0])
            entry = m.setdefault(key, {"raw": raw, "chunks": [], "ids": set()})
            entry["chunks"].append(c)
            entry["ids"].add(c.get("chunk_id"))
        _BOOK_MAP = m
    return _BOOK_MAP


def _word_in_spaced(token, spaced):
    """Whole-word membership of ``token`` in a lowercased, space-separated string.

    Substring tests are the reason a question word like "give" (forGIVE them
    their debts...) can name the wrong book — only real word boundaries count.
    """
    return bool(
        re.search(r"(?<![\w])" + re.escape(token) + r"(?![\w])", spaced)
    )


def _books_matching(name):
    """Book keys whose title contains the given name (or all its tokens).

    Matching is whole-word against the readable title (with separators turned
    into spaces) — never a raw substring, so a question word like "give" can
    not name the book "and ForGIVE Them Their Debts..." by accident.
    """
    tokens = [
        t for t in re.findall(r"[a-z0-9][a-z0-9'-]{3,}", re.sub(r"[()/›]", " ", str(name).lower()))
        if t.lower() not in _TITLE_STOPWORDS and t.lower() not in _SEARCH_STOPWORDS
    ]
    if not tokens:
        return []
    out = []
    for key, entry in _book_map().items():
        spaced = re.sub(r"[()/›]", " ", str(entry.get("raw") or key)).lower()
        if all(_word_in_spaced(t, spaced) for t in tokens):
            out.append(key)
    return out


def _fts_search_scoped(terms, book_key, limit=30):
    """Chunk ids matching the terms INSIDE one book (FTS file_path column filter)."""
    db = _fts_db()
    q = " OR ".join('"' + t.replace('"', "") + '"' for t in terms if t)
    if not q:
        return []
    entry = _book_map().get(book_key)
    fp_terms = [
        t
        for t in re.findall(r"[a-zA-Z0-9]{3,}", str(entry["raw"]) if entry else "")
        if t.lower() not in _SEARCH_STOPWORDS and t.lower() not in _TITLE_STOPWORDS
    ][:8]
    fp_q = " OR ".join('"' + t + '"' for t in fp_terms)
    match = f"({q}) AND file_path:({fp_q})" if fp_q else q
    try:
        rows = db.execute(
            "SELECT chunk_id FROM chunks_fts WHERE chunks_fts MATCH ? "
            "ORDER BY bm25(chunks_fts) LIMIT ?",
            (match, limit),
        ).fetchall()
    except Exception:
        rows = []
    own = _book_map().get(book_key, {}).get("ids", set())
    return [r[0] for r in rows if r[0] in own]


def _cap_per_book(ordered, cap):
    """Diversity cap: at most `cap` items per book, order preserved."""
    out, counts = [], {}
    for item in ordered:
        key = _book_key(item[2].get("file_path"))
        if counts.get(key, 0) >= cap:
            continue
        counts[key] = counts.get(key, 0) + 1
        out.append(item)
    return out


def _diversify(passages, cap=4):
    """Diversity cap for passage dicts (rerank output etc.)."""
    out, counts = [], {}
    for p in passages or []:
        key = _book_key(p.get("file_path"))
        if counts.get(key, 0) >= cap:
            continue
        counts[key] = counts.get(key, 0) + 1
        out.append(p)
    return out


_RETRIEVAL_ERRORS = []


def _retrieval_degrade(reason):
    """Record a retrieval failure that would otherwise vanish silently."""
    try:
        txt = str(reason)[:120].strip()
        if txt and txt not in _RETRIEVAL_ERRORS:
            _RETRIEVAL_ERRORS.append(txt)
    except Exception:
        pass


def _retrieval_degraded_note():
    return "; ".join(_RETRIEVAL_ERRORS)


_NEGATIVE_CHUNKS = set()
_NEGATIVE_CHUNKS_TS = 0.0


def _refresh_negative_chunks():
    """Chunk ids from answers the user reasked or stopped (recent window).

    A reask/stop within 15 minutes of an ask is a soft negative label for
    the passages that answer used; ranking gently demotes them next time.
    Cached for a minute so a burst of searches pays the query once.
    """
    global _NEGATIVE_CHUNKS, _NEGATIVE_CHUNKS_TS
    now = time.time()
    if _NEGATIVE_CHUNKS_TS and now - _NEGATIVE_CHUNKS_TS < 60:
        return
    _NEGATIVE_CHUNKS_TS = now
    try:
        if not _load_settings().get("learning_from_feedback", True):
            _NEGATIVE_CHUNKS = set()
            return
    except Exception:
        pass
    negatives = set()
    try:
        _telemetry_init()
        conn = _telemetry_conn()
        rows = conn.execute(
            "SELECT DISTINCT r.chunk_id FROM retrieval r "
            "JOIN asks a ON a.id = r.ask_id "
            "JOIN feedback f ON f.conv_id = a.conv_id "
            "WHERE f.kind IN ('reask', 'stop') "
            "AND f.ts >= a.ts AND f.ts <= datetime(a.ts, '+15 minutes') "
            "ORDER BY r.ask_id DESC LIMIT 500"
        ).fetchall()
        conn.close()
        negatives.update(r[0] for r in rows if r[0])
    except Exception:
        pass
    _NEGATIVE_CHUNKS = negatives


def _evidence_coverage(passages):
    """Which works the assembled evidence actually represents."""
    books = []
    for p in passages or []:
        key = _book_key(p.get("file_path", ""))
        if key and key not in books:
            books.append(key)
    return {"books": len(books), "names": books[:8], "chunks": len(passages or [])}


def _coverage_note(cov, kind, strategy):
    """Warning appended when cross-book questions rest on single-book evidence."""
    if not (cov.get("chunks") and cov.get("books", 0) < 2):
        return ""
    if not (
        strategy == "universal"
        or kind in ("research", "compare", "synthesis", "argument")
    ):
        return ""
    names = ", ".join(cov.get("names") or []) or "one work"
    return (
        "\n\n[Coverage note: the evidence above comes from only " + names
        + ". If the question asks about multiple works or the whole library, "
        "state plainly which works the answer rests on and which are not "
        "represented; never imply full coverage.]"
    )


def _load_memory_facts():
    """(topic, text) facts saved via `brain remember`, file order."""
    facts = []
    try:
        mem_dir = KNOWLEDGE_ROOT / "memory"
        if not mem_dir.exists():
            return []
        for path in sorted(mem_dir.glob("*.md")):
            try:
                for line in path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("- "):
                        facts.append((path.stem, line[2:].strip()))
            except Exception:
                continue
    except Exception:
        return []
    return facts


def _memory_matches(question, limit=5):
    """Remembered facts whose vocabulary overlaps the question, best first."""
    facts = _load_memory_facts()
    if not facts:
        return []
    terms = {t.lower() for t in _derive_terms(question, cap=12)}
    q_low = (question or "").lower()
    scored = []
    for topic, text in facts:
        low = text.lower()
        score = sum(1.0 for t in terms if len(t) >= 4 and t in low)
        for w in re.findall(r"[a-z][a-z'-]{3,}", topic.lower()):
            if w in q_low:
                score += 1.5
        if score > 0:
            scored.append((score, topic, text))
    scored.sort(key=lambda x: -x[0])
    return [(topic, text) for _, topic, text in scored[:limit]]


def _render_memory_block(facts):
    if not facts:
        return ""
    lines = [f"- [{topic}] {text}" for topic, text in facts]
    return (
        "\n\nThings the user asked you to remember that may be relevant "
        "(trusted context, not book evidence):\n" + "\n".join(lines)
    )


async def _librarian_search(rag, query, k=5, hyde_text=None, embedding=None, book_filter=None):
    """Semantic + literal search across the whole index. Returns passages.

    BOTH passes feed ONE unified ranking: semantic hits carry a moderate base
    score (so they can't crowd out higher-scored keyword matches like a named
    book or a rare term), then the single sorted list is capped.
    """
    _refresh_negative_chunks()
    q_sections = _sections_for_kind(query, _question_kind(query))
    best = {}  # chunk_id -> [score, excerpt, chunk]

    def _offer(score, c, excerpt=None):
        cid = c.get("chunk_id")
        if not cid:
            return
        if cid in _NEGATIVE_CHUNKS:
            score *= 0.9  # soft negative: user reasked/stopped this answer
        if excerpt is None:
            snippet = re.sub(r"\n{3,}", "\n\n", c.get("content", "")[:360])
            excerpt = "…" + snippet + "…"
        cur = best.get(cid)
        if cur is None or score > cur[0]:
            best[cid] = [score, excerpt, c]

    # semantic (vector) pass — sqlite-vec first, LightRAG's vdb as fallback
    try:
        emb = embedding
        if emb is None:
            embed_text = hyde_text or query
            emb = await nomic_embed([embed_text], context="document")
        chunks_by_id = {c["chunk_id"]: c for c in _load_chunk_texts()}
        try:
            _vec_sync()
        except Exception:
            pass
        ids = _vec_search(emb, k=k * 4)
        if not ids:
            raise RuntimeError("vec search empty")
        if book_filter:
            own = _book_map().get(book_filter, {}).get("ids", set())
            ids = [cid for cid in ids if cid in own]
        rank = 0
        for cid in ids:
            c = chunks_by_id.get(cid)
            if not c:
                continue
            if _is_boilerplate(c["content"], q_sections, file_path=c.get("file_path", "")):
                continue
            _offer(max(32.0 - rank * 1.2, 5.0), c)
            rank += 1
            if rank >= k * 2:
                break
    except Exception as exc:
        _retrieval_degrade(f"vector search: {exc}")

    # keyword pass via the FTS index. Book-title terms pick the book; content
    # terms (the meaningful ones) drive ranking and excerpt anchor, so
    # front-matter can't drown out the passage that actually mentions the topic.
    try:
        chunks = _load_chunk_texts()
        terms = _derive_terms(query)
        if terms:
            by_id = {c["chunk_id"]: c for c in chunks}
            _fts_sync()
            # Search PER TERM and union candidates: an OR across all terms lets
            # frequent terms crowd out the named entity that actually matters
            # (e.g. "america/sovereignty" chunks burying the "kojeve" book).
            # Plus an AND pass to catch chunks containing ALL terms (the
            # intersection, e.g. "mercy" AND "dune") that per-term limits miss.
            candidates = []
            seen_cids = set()
            if book_filter:
                for cid in _fts_search_scoped(terms, book_filter, limit=k * 6):
                    if cid not in seen_cids and cid in by_id:
                        seen_cids.add(cid)
                        candidates.append(by_id[cid])
            else:
                for t in terms:
                    for cid in _fts_search([t], limit=k * 6):
                        if cid not in seen_cids and cid in by_id:
                            seen_cids.add(cid)
                            candidates.append(by_id[cid])
            if len(terms) > 1 and not book_filter:
                for cid in _fts_search_and(terms, limit=k * 6):
                    if cid not in seen_cids and cid in by_id:
                        seen_cids.add(cid)
                        candidates.append(by_id[cid])
            book_terms = [t for t in terms if any(t in c["file_path"].lower() for c in chunks)]
            content_terms = [t for t in terms if t not in book_terms] or terms
            # Proper nouns in the query (capitalized, non-stopword) name a
            # specific book/author — a chunk from that book wins strongly.
            norm_q = _normalize_query(query)
            proper = [
                w.lower()
                for w in re.findall(r"[A-Z][A-Za-z'-]{2,}", norm_q)
                if w.lower() not in _SEARCH_STOPWORDS
            ]
            # Rarity weights: matching a RARE term (e.g. "litany") is far more
            # significant than a common one ("fear") — this surfaces the exact
            # passage and anchors its excerpt at the rarest matched term.
            rarity = {t: _fts_count(t) for t in content_terms}
            for c in candidates:
                low = c["content"].lower()
                lowfp = c["file_path"].lower()
                matched = [t for t in content_terms if t in low]
                content_score = sum(1 + 100.0 / max(rarity.get(t, 1), 1) for t in matched)
                fp_hits = sum(1 for t in terms if t in lowfp)
                proper_fp = any(t in lowfp for t in proper)
                if not matched and not fp_hits:
                    continue
                if _is_boilerplate(c["content"], q_sections, file_path=c.get("file_path", "")):
                    continue
                score = content_score * 10 + (50 if proper_fp else (2 if fp_hits else 0))
                anchor = min(matched, key=lambda t: rarity.get(t, 10**9)) if matched else terms[0]
                idx = low.find(anchor)
                if idx < 0:
                    idx = 0
                start = max(0, idx - 60)
                snippet = re.sub(r"\n{3,}", "\n\n", c["content"][start:start + 360])
                excerpt = "…" + snippet + "…"
                _offer(score, c, excerpt=excerpt)
    except Exception:
        pass

    ordered = sorted(best.values(), key=lambda x: -x[0])
    if not book_filter:
        # Diversity floor: no single book may sweep the whole block.
        ordered = _cap_per_book(ordered, min(4, max(3, int(k * 0.8))))
    return [
        {
            "file_path": c["file_path"],
            "content": c["content"],
            "excerpt": excerpt,
            "chunk_id": c["chunk_id"],
        }
        for _, excerpt, c in ordered[: k * 2]
    ]


async def _fast_llm(prompt, system_prompt=None):
    """Cheap, fast model for planning/searching (flash when online, else local).

    ``planner_model`` in settings can pin the librarian/planner to a specific
    model — including provider-prefixed ids ("openrouter/…", "moonshot/…") —
    with flash as the default and local qwen the offline fallback.
    """
    if not _offline():
        planner = str(_load_settings().get("planner_model") or "").strip()
        candidates = ([planner] if planner else []) + [DEEPSEEK_FLASH_MODEL]
        seen = set()
        for cand in candidates:
            resolved = resolve_model(cand)
            if resolved in seen:
                continue
            seen.add(resolved)
            provider, base_url, api_key, wire = resolve_provider(resolved)
            if not (provider and api_key):
                continue
            try:
                return await remote_llm(
                    prompt,
                    system_prompt=system_prompt,
                    model=wire,
                    base_url=base_url,
                    api_key=api_key,
                    provider=provider,
                    max_tokens=900 if planner and cand == planner else 700,
                    timeout=45,
                )
            except Exception as exc:
                _telemetry_log_feedback(
                    "llm_fallback",
                    f"{'planner' if cand == planner and planner else 'flash'}: {str(exc)[:120]}",
                )
    return await ollama_llm(
        prompt, system_prompt=system_prompt, local_model=OLLAMA_DEEP_MODEL,
        think=False,
    )


def _extract_json_list(text):
    """Best-effort parse of a JSON array (or 'done') from model output."""
    m = re.search(r"\[.*\]", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    if re.search(r"\bdone\b", text, re.I):
        return {"done": True}
    return []


_LAST_ANALYSIS = {"question": "", "data": {}}  # cached front-end comprehension


def _analysis(question):
    """Cached comprehension of the question (kind, phrase, scope, angles...)."""
    if _LAST_ANALYSIS.get("question") == question:
        return _LAST_ANALYSIS.get("data") or {}
    return {}


def _analysis_store(question, data):
    _LAST_ANALYSIS["question"] = question
    _LAST_ANALYSIS["data"] = data or {}


# ------------------------------------------------------------- session memory
# Mentat has to remember WITHIN a conversation: what the previous
# question meant (kind/phrase/scope) and what the last census found, so a bare
# follow-up ("the whole series, i need a number") inherits the prior
# understanding instead of starting blind. Persisted per conversation in
# storage/state.json (flock/atomic writes live with the conversation store).
_SESSION_MEM_MAX_AGE = 6 * 3600.0
_SESSION_MEM_PRUNE = 7 * 86400.0


def _session_mem():
    """{conv_id: {"analysis": {...}, "census": {...}}} from state.json."""
    try:
        mem = (_load_state().get("analysis_mem") or {})
        return mem if isinstance(mem, dict) else {}
    except Exception:
        return {}


def _session_mem_for(conv_id):
    try:
        entry = (_session_mem().get(conv_id) or {})
        return entry if isinstance(entry, dict) else {}
    except Exception:
        return {}


def _remember_analysis(question, data):
    """Persist the comprehension of ``question`` for follow-up resolution."""
    if not data:
        return
    conv = _current_conv_id()
    if not conv:
        return
    try:
        state = _load_state()
        mem = dict(state.get("analysis_mem") or {})
        entry = dict(mem.get(conv) or {})
        prev = dict(entry.get("analysis") or {})
        prev.update(
            {
                "question": str(question)[:500],
                "kind": str(data.get("kind") or ""),
                "phrase": str(data.get("phrase") or ""),
                "scope_hint": str(data.get("scope_hint") or ""),
                "ts": time.time(),
            }
        )
        entry["analysis"] = prev
        entry["ts"] = time.time()
        mem[conv] = entry
        cutoff = time.time() - _SESSION_MEM_PRUNE
        state["analysis_mem"] = {
            k: v for k, v in mem.items()
            if (v.get("ts") or 0) >= cutoff or k == conv
        }
        _save_state(state)
    except Exception:
        pass


def _remember_census(question, phrase, total=None):
    """Persist the last successful census so continuations can inherit it."""
    if not phrase:
        return
    conv = _current_conv_id()
    if not conv:
        return
    try:
        state = _load_state()
        mem = dict(state.get("analysis_mem") or {})
        entry = dict(mem.get(conv) or {})
        entry["census"] = {
            "question": str(question)[:500],
            "phrase": phrase,
            "total": total,
            "ts": time.time(),
        }
        entry["ts"] = time.time()
        mem[conv] = entry
        state["analysis_mem"] = mem
        _save_state(state)
    except Exception:
        pass


def _prior_analysis(conv_id):
    """The previous question's comprehension, if fresh."""
    entry = _session_mem_for(conv_id)
    an = entry.get("analysis") or {}
    if not an.get("question"):
        return {}
    ts = an.get("ts") or 0
    if (time.time() - ts) > _SESSION_MEM_MAX_AGE:
        return {}
    return an


def _prior_census(conv_id):
    """The last successful census (phrase + scope question), if fresh."""
    entry = _session_mem_for(conv_id)
    cm = entry.get("census") or {}
    if not cm.get("phrase"):
        return {}
    ts = cm.get("ts") or 0
    if (time.time() - ts) > _SESSION_MEM_MAX_AGE:
        return {}
    return cm


def _parse_analysis_json(raw):
    """Lenient parse of the classifier's JSON (fences, prose, partial fields)."""
    text = re.sub(r"```(?:json)?", "", raw or "").strip().lstrip("`").rstrip("`")
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    out = {}
    for key in ("kind", "phrase", "scope_hint"):
        mm = re.search(r'"%s"\s*:\s*"([^"]*)"' % key, text)
        if mm:
            out[key] = mm.group(1)
    for key in ("angles", "books"):
        mm = re.search(r'"%s"\s*:\s*(\[[^\]]*\])' % key, text)
        if mm:
            try:
                out[key] = json.loads(mm.group(1))
            except Exception:
                out[key] = []
    return out


async def _expand_query(question):
    """Tier 1: comprehend the question AND resolve the books it names.

    The model understands the request the way a librarian would: what KIND
    of answer is wanted (a count, quotes, a comparison...), the exact phrase
    to hunt or count, which books/authors it refers to, and search angles.
    Deterministic code later verifies everything the model proposes — this
    call only decides WHAT to verify, never the numbers.
    Returns {"kind", "phrase", "books", "angles", "scope_hint"}.
    """
    out = {"kind": "", "phrase": "", "books": [], "angles": [], "scope_hint": ""}
    if _offline():
        _analysis_store(question, out)
        return out
    # Already comprehended this question earlier in the ask flow? Reuse it —
    # _build_passages runs right after the strategy pre-pass.
    cached = _analysis(question)
    if any(cached.get(k) for k in ("kind", "phrase", "scope_hint", "books", "angles")):
        return cached
    titles = "; ".join(_clean_name(rel) for rel in sorted(_load_manifest()))
    conv = _current_conv_id()
    prior_blk = ""
    prior_an = _prior_analysis(conv) if conv else {}
    if prior_an.get("question"):
        prior_blk = (
            "Prior context (the user's PREVIOUS question in this conversation "
            "and how it was understood):\n"
            f"  question: {str(prior_an['question'])[:400]}\n"
            "  understood as kind=%s, phrase=%r, scope_hint=%r\n"
            % (
                prior_an.get("kind", ""),
                str(prior_an.get("phrase", ""))[:200],
                str(prior_an.get("scope_hint", ""))[:200],
            )
        )
    prompt = (
        "For the library question below, understand what is being asked and "
        "answer as JSON. The question may be phrased any way at all; your job "
        "is intent, not keywords — handle casual phrasing, typos, and follow-ups.\n"
        "Fields:\n"
        "  kind: one of \"count\" (wants a number/occurrences of a phrase), "
        "\"quotes\" (wants verbatim passages), \"compare\" (compares books), "
        "\"research\" (needs evidence from several books), \"fact\" (a simple "
        "question), \"chat\" (casual, no library needed).\n"
        "  phrase: ONLY when kind is count or quotes — the exact text to look "
        "for or count, written as it would appear in the book (include words "
        "like 'the' if the book would; e.g. \"eyes of the Ibad\"); keep any "
        "user quotation marks if the user quoted something verbatim.\n"
        "  scope_hint: the books/library-part the user points at (e.g. \"dune "
        "series\", \"all books\", \"the quran\"), or \"\".\n"
        "  angles: search terms worth trying: named works, exact phrases, key "
        "concepts, synonyms.\n"
        "  books: which books/authors the question refers to, using names "
        "EXACTLY as they appear in the available-books list.\n"
        f"{prior_blk}"
        "CONTINUATION RULE: if THIS question is a follow-up to the prior one "
        "('the whole series', 'what about the quran?', 'now count it', 'find "
        "them all'), inherit the prior phrase/kind and only change what the "
        "user changed (usually the scope). Answer for THIS question.\n"
        f"Available books: {titles}\n"
        f"Question: {question}\n"
        'Return ONLY JSON: {"kind": "...", "phrase": "...", "scope_hint": "...", '
        '"angles": ["..."], "books": ["..."]}'
    )
    for attempt in (1, 2):
        try:
            raw = await _fast_llm(prompt if attempt == 1 else
                "One line JSON for this: kind, phrase (only if it asks to count/"
                f"quote something exact), scope_hint, angles, books. Question: {question}\n"
                '{"kind": "...", "phrase": "...", "scope_hint": "", '
                '"angles": [], "books": []}')
            data = _parse_analysis_json(raw) or {}
            kind = str(data.get("kind") or "").strip().lower()[:20]
            phrase = str(data.get("phrase") or "").strip()
            if phrase or kind:
                out["kind"] = kind
                out["phrase"] = phrase
                out["scope_hint"] = str(data.get("scope_hint") or "").strip()
                out["angles"] = [str(x).strip() for x in data.get("angles", []) if str(x).strip()][:8]
                out["books"] = [str(x).strip() for x in data.get("books", []) if str(x).strip()][:4]
                break
        except Exception:
            continue
    _analysis_store(question, out)
    if out.get("kind") or out.get("phrase") or out.get("scope_hint"):
        _remember_analysis(question, out)
    return out


async def _planner(question, seen, rounds_left, scratch=None):
    """Tier 2: decide the next searches (or that we're done).

    ``scratch`` is the planner's working memory for this question: one entry
    per completed round (what was searched, what it added, which books it
    touched, plus any note the planner itself wanted to carry forward). It
    keeps later rounds from looping and lets the model reason about gaps
    instead of only the last page of evidence.
    """
    if _offline():
        return {"done": True}
    seen_text = "\n\n".join(
        f"[{i + 1}] {p.get('file_path', '')}\n{p.get('excerpt', '')[:500]}"
        for i, p in enumerate(seen[-6:])
    )
    scratch_text = "\n".join(
        f"round {s.get('round')}: searched {s.get('queries') or '(none)'} -> "
        f"+{s.get('new', 0)} new passage(s)"
        + (f" from {', '.join(s['books'])}" if s.get("books") else "")
        + (f" | note: {s['note']}" if s.get("note") else "")
        for s in (scratch or [])[-6:]
    )
    prompt = (
        "You are searching a library to answer a question. Retrieved so far:\n"
        f"{seen_text or '(nothing yet)'}\n\n"
        + (
            "Your scratchpad so far (do not repeat these searches; use it to "
            f"find gaps):\n{scratch_text}\n\n"
            if scratch_text
            else ""
        )
        + f"Question: {question}\n\n"
        "Decide what to search for next. Do NOT repeat searches that already "
        "appear above — look for gaps instead. Return ONLY JSON: "
        "{\"searches\": [\"query 1\", \"query 2\"], \"note\": \"optional one-line "
        "observation to remember next round\"} with up to 3 search queries, "
        "or {\"done\": true, \"note\": \"...\"} if you already have enough."
    )
    try:
        out = await _fast_llm(prompt)
        if isinstance(out, dict) and out.get("done"):
            return {"done": True, "note": str(out.get("note") or "")[:200]}
        items = _extract_json_list(out or "")
        if isinstance(items, dict) and items.get("done"):
            return {"done": True, "note": str(items.get("note") or "")[:200]}
        if isinstance(items, list):
            return {
                "searches": [str(x) for x in items if str(x).strip()][:3],
                "note": "",
            }
    except Exception:
        pass
    return {"done": True}


def _has_find_intent(question):
    q = question.lower()
    return any(
        w in q
        for w in (
            "find", "list", "all the", "every", "examples", "quote", "quotes",
            "poem", "poems", "song", "songs", "what are the", "enumerate",
            "look for", "where does", "give me", "say about", "view on",
            "stance", "think about", "perspective on", "position on",
        )
    )


def _named_books(question):
    """Distinct book-level identities named in the question.

    Uses proper nouns plus lowercase terms (so 'stalin' works uncapitalized),
    excludes common title words, and dedupes to whole books — 'Catholic
    Study Bible' counts as ONE book, not three.
    """
    proper = [
        w.lower()
        for w in re.findall(r"[A-Z][A-Za-z'-]{2,}", _normalize_query(question))
        if w.lower() not in _SEARCH_STOPWORDS and w.lower() not in _TITLE_STOPWORDS
    ]
    terms = _derive_terms(question)
    candidates = proper + [
        t for t in terms if len(t) >= 4 and t not in proper and t not in _TITLE_STOPWORDS
    ]
    books = set()
    bm = _book_map()
    spaced_raw = {
        key: re.sub(r"[()/›]", " ", entry.get("raw") or key).lower()
        for key, entry in bm.items()
    }
    for t in candidates:
        # a term that appears in many titles ("books", "revolution") names
        # nothing — only rare title terms identify a specific book.
        if sum(1 for n in spaced_raw.values() if _word_in_spaced(t, n)) > 3:
            continue
        for key, spaced in spaced_raw.items():
            if _word_in_spaced(t, spaced):
                books.add(bm[key]["raw"])
                break
    return books


# ---------------------------------------------------------------------------
# Work scope — which books does this question demand, and (for counting
# questions) exact occurrence censuses over the full staged texts.
#
# A "work" is a book collapsed across duplicate files (the same novel as an
# .epub and a scanned .pdf counts as ONE work, not two — otherwise the two
# copies split the retrieval window and double every count).
# ---------------------------------------------------------------------------


def _title_canon(text):
    """Stable identity for a book title, across file labels, rel paths and keys.

    Drops folder prefixes, archive/author parentheticals, extensions and
    leading author segments ("Frank Herbert - Dune 1 - Dune.pdf"), so the
    EPUB and PDF copies of the same novel collapse to the same id ("dune").
    """
    s = re.sub(r"\([^)]*\)", " ", str(text))
    for sep in ("›", "/"):
        if sep in s:
            s = s.rsplit(sep, 1)[1]
    s = s.rsplit(".", 1)[0]
    if " - " in s:
        s = s.split(" - ", 1)[1]
    toks = re.findall(r"[a-z][a-z'-]*", s.lower())
    keep = []
    for w in toks:
        if len(w) <= 2 or w in _SEARCH_STOPWORDS or w in _TITLE_STOPWORDS:
            continue
        if w not in keep:
            keep.append(w)
    return " ".join(keep)


def _collapse_works(keys):
    """Ordered [{'id', 'keys', 'primary', 'title'}] with duplicate copies merged.

    ``primary`` is the richest copy (an epub when present, else the copy with
    the most indexed chunks) — searches and censuses run against it once.
    """
    order = []
    items = {}
    bm = _book_map()
    for k in keys:
        c = _title_canon(bm.get(k, {}).get("raw") or k)
        if c not in items:
            items[c] = {"id": c, "keys": []}
            order.append(items[c])
        if k not in items[c]["keys"]:
            items[c]["keys"].append(k)
    for it in items.values():
        prefs = [k for k in it["keys"] if ".epub" in k]
        if not prefs:
            prefs = sorted(it["keys"], key=lambda k: -len(bm.get(k, {}).get("chunks", [])))
        primary = prefs[0]
        raw = bm.get(primary, {}).get("raw", primary)
        folderless = [k for k in it["keys"] if "›" not in k]
        title = raw.split(" › ")[-1] if folderless == [] else (
            bm.get(folderless[0], {}).get("raw", raw)
        )
        it["primary"] = primary
        it["title"] = _clean_name(title)
    return order


def _book_hits_any(terms, ids, limit_ids=2000):
    """How many chunks of one book contain ANY of the terms (OR semantics)."""
    db = _fts_db()
    q = " OR ".join('"' + str(t).replace('"', "") + '"' for t in terms if t)
    if not q or not ids:
        return 0
    sample = sorted(ids)[:limit_ids]
    ph = ",".join("?" * len(sample))
    try:
        row = db.execute(
            "SELECT count(*) FROM chunks_fts WHERE chunks_fts MATCH ? "
            f"AND chunk_id IN ({ph})",
            (q, *sample),
        ).fetchone()
        return row[0] if row else 0
    except Exception:
        return 0


def _book_hits_all(terms, ids, limit_ids=2000):
    """How many chunks of one book contain ALL of the terms (AND semantics).

    Used as a fallback when an exact phrase query ("eyes of ibad") misses a
    text that carries stopword noise ("eyes of the ibad"): the content words
    still co-occur, so the book verifies.
    """
    db = _fts_db()
    q = " AND ".join('"' + str(t).replace('"', "") + '"' for t in terms if t)
    if not q or " AND " not in q or not ids:
        return 0
    sample = sorted(ids)[:limit_ids]
    ph = ",".join("?" * len(sample))
    try:
        row = db.execute(
            "SELECT count(*) FROM chunks_fts WHERE chunks_fts MATCH ? "
            f"AND chunk_id IN ({ph})",
            (q, *sample),
        ).fetchone()
        return row[0] if row else 0
    except Exception:
        return 0


# Words that belong to the question's machinery, not its subject — counting
# preambles ("how many times..."), locatives ("anywhere in your library",
# "across the books") and meta nouns. They must never decide which books a
# question is about (front matter alone would verify every book).
_SCOPE_JUNK_TERMS = {
    "anywhere", "where", "library", "libraries", "vault", "books", "book",
    "series", "saga", "chronicles", "novels", "novel", "writings", "writing",
    "works", "work", "texts", "text", "files", "file", "collection", "corpus",
    "archive", "reading", "read", "whole", "entire", "every", "each", "across",
    "throughout", "within", "among", "inside", "over", "between", "appear",
    "appears", "appeared", "appearing", "mention", "mentions", "mentioned",
    "mentions", "occur", "occurs", "occurred", "occurring", "occurrence",
    "occurrences", "frequency", "frequent", "count", "counts", "counting",
    "times", "often", "many", "much", "used", "use", "uses", "does", "do",
    "is", "are", "did", "has", "have", "how", "what", "where", "which",
    "say", "says", "said", "speak", "speaks", "spoke", "told", "terms",
    "term", "word", "words", "phrase", "phrases", "quote", "quotes",
    "quoted", "example", "examples", "about", "with", "them", "they",
    "these", "this", "those", "there", "their", "found", "find", "list",
    "all", "any", "your", "my", "our", "the",
}


def _has_library_wide_intent(question):
    """Counting/sweep questions that demand the WHOLE library, not named books."""
    q = (question or "").lower()
    return any(
        w in q
        for w in (
            "all your books", "all my books", "all of your books", "all of my books",
            "your library", "my library", "your vault", "my vault", "whole library",
            "entire library", "whole vault", "entire vault", "any of your books",
            "any of my books", "any book you have", "any of your library",
            "anywhere in your library", "anywhere in the library", "in the library",
            "across your library", "across the library", "every book", "each book",
            "whole collection", "entire collection", "all your texts", "you have",
        )
    )


def _resolve_scope(question, strategy, model_books=(), sweep_all=False, verify_terms=None, named_only=False):
    """Decide which works a question demands, in priority order.

    1. Explicitly named works/authors (incl. the LLM's expansion picks).
    2. Every work whose indexed text actually contains any of the question's
       terms — FTS-verified, immune to ranking, so a book can never be missed
       just because its passage ranked below the cut.
    3. When the question is library-wide (or sweep_all is set) — every other
       work, so censuses can report exact zeros instead of guessing.

    ``verify_terms`` overrides step 2's vocabulary — a census passes the
    exact phrase so common words inside it ("eyes" in "eyes of the ibad")
    can never widen the scope to every book that mentions eyes.
    """
    bm = _book_map()
    if not bm:
        return []
    try:
        _fts_sync()
    except Exception:
        pass
    terms = _derive_terms(question, cap=16)
    wanted = []
    for name in list(model_books or []) + list(_named_books(question) or []):
        for k in _books_matching(name):
            if k not in wanted:
                wanted.append(k)
    for t in terms:
        if t.lower() in _SCOPE_JUNK_TERMS:
            continue  # machinery words ("books", "across") must not name books
        for k in _books_matching(t):
            if k not in wanted:
                wanted.append(k)
    scope = _collapse_works(wanted)
    for it in scope:
        it["demand"] = True  # explicitly named: sweep even with zero content hits
    try:
        all_items = _collapse_works(list(bm.keys()))
        # Verification terms: a quoted phrase ("eyes of the ibad") is itself the
        # discriminating unit and needs no word-level help. Without a phrase,
        # use single words that are neither machinery nor corpus-frequent —
        # "fremen" spans ~700 chunks across six novels yet still only names the
        # Dune shelf, so the bar is a SHARE of the corpus, not an absolute row
        # count.
        phrase_terms = [t for t in terms if len(str(t).split()) > 1]
        try:
            total_rows = _fts_db().execute(
                "SELECT count(*) FROM chunks_fts"
            ).fetchone()[0]
        except Exception:
            total_rows = 0
        if verify_terms:
            rare = [str(t) for t in verify_terms if str(t)]
        else:
            rare = phrase_terms or [
                t for t in terms
                if t.lower() not in _SCOPE_JUNK_TERMS
                and _fts_count(t) <= max(150, int((total_rows or 0) * 0.35))
            ]
        have = {it["id"] for it in scope}
        verified = []
        # Guard-path scope (count wanted, no phrase) is named-only: a common
        # word like "eyes" must not drag the whole library into a Dune-shaped
        # question's references just because no phrase could be extracted.
        for it in ([] if named_only else all_items):
            if it["id"] in have:
                continue
            ids = set()
            for k in it["keys"]:
                ids |= set(bm.get(k, {}).get("ids", set()))
            try:
                n = _book_hits_any(rare, ids)
                if n == 0:
                    # exact phrase missed (stopword noise / diacritics):
                    # fall back to requiring all content words together.
                    loose = [
                        w for w in re.findall(
                            r"[A-Za-z][A-Za-z'-]*", " ".join(rare)
                        )
                        if w.lower() not in _FLEX_STOPWORDS
                        and w.lower() not in _SCOPE_JUNK_TERMS
                        and w.lower() not in _CENSUS_META_WORDS
                    ]
                    if len(loose) >= 2:
                        n = _book_hits_all(loose, ids)
            except Exception:
                n = 0
            if n > 0:
                it["hits"] = n
                it["demand"] = False
                verified.append(it)
        verified.sort(key=lambda it: -it["hits"])
        scope += verified
        have = {it["id"] for it in scope}
        if sweep_all or strategy == "universal" or _has_library_wide_intent(question):
            for it in all_items:
                if it["id"] not in have:
                    it["hits"] = 0
                    it["demand"] = False
                    scope.append(it)
    except Exception:
        pass
    return scope


def _fts_scope_passages(question, book_key, limit=12):
    """Keyword-only scoped fallback: passages from one book matching the terms."""
    terms = _derive_terms(question)
    q_sections = _sections_for_kind(question, _question_kind(question))
    by_id = {c["chunk_id"]: c for c in _load_chunk_texts()}
    out = []
    for cid in _fts_search_scoped(terms, book_key, limit=limit * 2):
        c = by_id.get(cid)
        if not c:
            continue
        if _is_boilerplate(c["content"], q_sections, file_path=c.get("file_path", "")):
            continue
        low = c["content"].lower()
        anchor = next((t for t in terms if t in low), None)
        i = low.find(anchor) if anchor else 0
        s = max(0, i - 60)
        out.append(
            {
                "file_path": c["file_path"],
                "content": c["content"],
                "excerpt": "…" + re.sub(r"\n{3,}", "\n\n", c["content"][s:s + 360]) + "…",
                "chunk_id": c["chunk_id"],
            }
        )
        if len(out) >= limit:
            break
    return out


def _ensure_scope_coverage(final, scope, group_pool, cap_total=26, per_work=3):
    """Guarantee demanded works contribute; named works first, then verified.

    A cross-book question that explicitly names works must not have its
    evidence crowded out by library-wide sweeps: named (demand) works get a
    small quota each, non-named works are capped at two passages apiece, and
    only then is the total capped.
    """
    if not scope:
        return final

    def _work_of(p):
        try:
            k = _book_key(p.get("file_path", ""))
        except Exception:
            return None
        for it in scope:
            if k in it["keys"]:
                return it["id"]
        return None

    out = list(final)
    counts = {}
    for p in out:
        wid = _work_of(p)
        if wid:
            counts[wid] = counts.get(wid, 0) + 1
    ordered = [it for it in scope if it.get("demand")] + [
        it for it in scope if not it.get("demand")
    ]
    for it in ordered:
        if not it.get("hits") and not it.get("demand"):
            continue
        seen_chunks = {p.get("chunk_id") for p in out if p.get("chunk_id")}
        for p in group_pool.get(it["id"], []) or []:
            if counts.get(it["id"], 0) >= per_work:
                break
            cid = p.get("chunk_id")
            if cid and cid in seen_chunks:
                continue
            out.append(p)
            if cid:
                seen_chunks.add(cid)
            counts[it["id"]] = counts.get(it["id"], 0) + 1
    if any(it.get("demand") for it in scope):
        trimmed, others_kept = [], 0
        for p in out:
            wid = _work_of(p)
            demanded = any(it["id"] == wid and it.get("demand") for it in scope)
            if demanded:
                trimmed.append(p)
                continue
            if others_kept >= 3:
                continue  # irrelevant sweeps may not crowd a named-work question
            others_kept += 1
            trimmed.append(p)
        out = trimmed
    return out[:cap_total]


# ------------------------- counting questions (exact census) -----------------

_CENSUS_PREFIX_RE = re.compile(
    r"^(?:"
    r"how many times|how many books|how many of your|how many|how often|how frequently|"
    r"what is the (?:exact )?count of|what.*?count of|the number of|number of|"
    r"any mention(?:s)? of|all mentions of|mentions? of|occurrences? of|frequency of|"
    r"instances? of|which books?(?: in your library)? (?:mention|contain|use|quote|say)|"
    r"where (?:does|do|is|are|can i find|can we find)|"
    r"(?:does|do|is|are|did|has|have) (?:the )?(?:word|phrase|term|expression)?|"
    r"is there any (?:mention|use|occurrence|instance) of|"
    r"does it ever (?:mention|use|say)"
    r")\s*",
    re.IGNORECASE,
)

_CENSUS_VERB_TAIL_RE = re.compile(
    r"\s*(?:(?:is|are|was|were|has|have|had|been|gets?|got)\s+)?"
    r"(?:appears?|appeared|appearing|occurs?|occurred|occurring|shows? up|showed up|"
    r"comes? up|came up|is mentioned|gets mentioned|is quoted|gets quoted|mentioned|"
    r"used|featured|quoted|cited|written|referenced)\s*$",
    re.IGNORECASE,
)

_CENSUS_LOC_TAIL_RE = re.compile(
    r"\s*(?:anywhere\s*)?(?:in|across|within|among|throughout|over|inside|outside)"
    r"\s+(?:the|your|my|our|all|every|any|this)?\s*(?:whole|entire|full|complete)?\s*"
    r"(?:\w+\s+){0,2}"  # a series name may sit before the noun ("the dune series")
    r"(?:six|seven|five|four|three|two|several|many)?\s*"
    r"(?:library|libraries|vault|books?|series|saga|novels?|writings?|works?|"
    r"reading|texts?|collection|corpus|archive|brain|sources?|files?)?\s*$",
    re.I,
)

_CENSUS_TITLE_TAIL_RE = re.compile(
    r"\s*(?:in|of|across|among|inside|over|throughout|within|from)"
    r"\s+[A-Z][A-Za-z'’-]*\s*$"
)

# A trailing locative that names a BOOK rather than a collection ("in dune",
# "across the bible") — the tail words are the title's own words.
_CENSUS_BOOK_TAIL_RE = re.compile(
    r"\s*(?:in|across|within|among|throughout|over|inside|outside|from)\s*"
    r"(?:the|your|my|our|all)?\s*"
    r"([A-Za-z][A-Za-z'’-]*(?:\s+[A-Za-z][A-Za-z'’-]*){0,3})\s*$",
    re.I,
)

_TITLE_TOKEN_CACHE = None


def _title_tokens():
    """Lowercased distinctive words found in the library's book titles.

    Used to recognize trailing book-name locatives ("eyes of ibad in dune")
    that generic collection words ("series", "books") cannot cover — ``dune``,
    ``messiah``, ``quran``, ``hudson`` are scope words here, not phrase words.
    """
    global _TITLE_TOKEN_CACHE
    if _TITLE_TOKEN_CACHE is not None:
        return _TITLE_TOKEN_CACHE
    toks = set()
    try:
        keys = list(_load_manifest().keys())
    except Exception:
        keys = []
    for rel in keys:
        base = re.split(r"[·›/\\]", rel)[-1]
        base = _clean_name(base)
        base = re.sub(r"\.(?:epub|pdf|txt|mobi|azw3|docx?)\s*$", "", base, flags=re.I)
        for w in re.findall(r"[A-Za-z][A-Za-z']{3,}", base):
            wl = w.lower()
            if (
                wl not in _SEARCH_STOPWORDS
                and wl not in _TITLE_STOPWORDS
                and wl not in _SCOPE_JUNK_TERMS
            ):
                toks.add(wl)
    _TITLE_TOKEN_CACHE = toks
    return toks

_CENSUS_MID_VERB_RE = re.compile(
    r"\b(?:appears?|appeared|occur[sr]?|occurred|shows? up|showed up|comes? up|came up|"
    r"is mentioned|gets mentioned|mentioned|used|featured|quoted|cited|written|referenced)\b",
    re.IGNORECASE,
)

# "in the entire dune series, how often ..." — the counting clause can be
# prefixed by a scope phrase that names WHERE to count, not WHAT to count.
_CENSUS_SCOPE_LEAD_RE = re.compile(
    r"^(?:(?:in|across|throughout|among|within|over|reading|looking at)\s+)?"
    r"(?:the|your|my|our|all|this|every|any)?\s*"
    r"(?:entire|whole|full|complete)?\s*"
    r"(?:dune\s+)?(?:all\s+)?"
    r"(?:six|seven|five|four|three|two|several|many)?\s*"
    r"(?:books?|series|novels?|libraries?|works?|writings?|sagas?|chronicles|"
    r"trilogy|franchise|collection|vault|texts?)\b[,\s]*",
    re.I,
)

# "find all the instances of the eyes of ibad ..." / "can you list every
# mention of X" / "find me every place where X shows up" — instance-hunting
# phrasing names WHAT to count without the counting verb ever appearing.
_CENSUS_INSTANCE_LEAD_RE = re.compile(
    r"^(?:can you |could you |please |would you |help me )?"
    r"(?:find|show|locate|search(?: for)?|list|get|give|tell|fetch|hunt|pull)"
    r"(?:\s+me|\s+us)?\s*"
    r"(?:all|every|each|any)?\s*(?:the\s+)?"
    r"(?:(?:instances?|times?|occurrences?|mentions?|places?|examples?|"
    r"appearances?|uses?|usages?|hits?)\s*(?:of|where|in which)?|"
    r"(?:of|where|in which))\b\s*",
    re.I,
)


def _strip_census_tails(s):
    """Trim counting-question scaffolding from the content clause."""
    while True:
        prev = s
        s = s.strip().rstrip("\"'“”‘’?:;.,! ")
        s = _CENSUS_VERB_TAIL_RE.sub("", s).strip()
        s = _CENSUS_LOC_TAIL_RE.sub("", s).strip()
        # a trailing locative that names a BOOK ("in dune", "in the bible"):
        # strip it only when every tail word is a known title word and the
        # surviving clause still has real content ("eyes of ibad" survives,
        # so the count stays exact instead of dying on "...ibad in dune").
        mt = _CENSUS_BOOK_TAIL_RE.search(s)
        if mt:
            tail_words = re.findall(r"[A-Za-z][A-Za-z'-]*", mt.group(1))
            title_words = _title_tokens()
            if tail_words and all(w.lower() in title_words for w in tail_words):
                stem = s[:mt.start()].strip()
                stem_content = [
                    t for t in re.findall(r"[A-Za-z][A-Za-z'-]*", stem)
                    if t.lower() not in _FLEX_STOPWORDS
                ]
                if len(stem_content) >= 1:
                    s = stem
        s = _CENSUS_TITLE_TAIL_RE.sub("", s).strip()
        if s == prev:
            break
    return s


# Conversation fillers that can open a question ("yo, how many times...",
# "ok so what's the count of...") — they must not defeat the anchored
# preamble/scope regexes below.
_CENSUS_FILLER_LEAD_RE = re.compile(
    r"^(?:yo|hey(?: there)?|hi(?: there)?|hello|ok(?:ay)?|so|well|um|uh|hmm|"
    r"now|btw|by the way|and|also)[\s,:—-]+\s*",
    re.I,
)


# "…the dune series MENTION the eyes of ibad" — the counted thing sits AFTER
# a subject-verb construction, the mirror of the usual "does X appear…" shape.
_CENSUS_SUBJECT_VERB_RE = re.compile(
    r"\b(?:mentions?|mentioning|says?|saying|uses?|used|discusses?|discussed|"
    r"features?|quotes?|talks?\s+about|refer(?:s|red)?\s+to)\s+"
    r"(?:the\s+)?(?:word|phrase|term|expression|name)?\s*"
    r"(.{2,120})\s*$",
    re.I,
)
# Same family left at the HEAD by the preamble ("mention the emperor") —
# count machinery only when a real noun phrase follows ("the"/"his"/"the
# word X"), so a phrase that itself opens with "use of..." is untouched.
_CENSUS_LEAD_VERB_RE = re.compile(
    r"^(?:mentions?|mentioning|uses?|used|says?|saying|discusses?|discussed|"
    r"quotes?|features?|talks?\s+about)\s+"
    r"(?=(?:the|a|an|his|her|its|their|this|that)\b)",
    re.I,
)
_SCOPE_MARK_RE = re.compile(
    r"\b(?:series|saga|chronicles?|books?|novels?|libraries?|collection|corpus|"
    r"texts?|works?|writings?|trilogy|volume|vault|chapters?)\b"
    r"|\b[A-Z][A-Za-z'’-]{2,}\b",
    re.I,
)


# Words that belong to a counting question's MACHINERY rather than its subject
# ("how many WORDS/PAGES/BOOKS...", "a COUNT of...") — a phrase built only of
# these ("words are", "count the") is no phrase at all.
_CENSUS_META_WORDS = frozenset(
    {
        "count", "counts", "counting", "counted", "words", "word", "pages",
        "page", "total", "number", "numbers", "times", "time", "frequency",
        "occurrences", "occurrence", "instances", "instance", "mentions",
        "mention", "mentioned", "appear", "appears", "appeared", "uses",
        "use", "used", "list", "lists", "entries", "hits", "terms", "term",
        "phrases", "phrase", "statistics", "stats", "topics", "subjects",
        # question scaffolding that must never survive as a countable phrase
        # ("what does", "how about", "which books") and never be remembered
        "what", "does", "do", "did", "how", "why", "which", "where", "who",
        "when", "say", "says", "said", "about", "book", "books", "them",
        "they", "any", "one", "some", "many", "much", "there", "can", "you",
        "your", "give", "find", "show", "tell", "me", "we", "all",
    }
)


def _census_flagged(question, single):
    """Did the question explicitly flag ``single`` as the thing to inspect
    ("the word melange", 'phrase "eyes of the ibad"')?"""
    return bool(
        re.search(
            r"\b(?:the\s+)?(?:word|phrase|term|expression|name|idea|concept)"
            r"\s+[\"“”‘`']?\s*" + re.escape(single) + r"\b",
            (question or "").lower(),
        )
    )


def _census_phrase(question):
    """The exact phrase a counting question asks about, or None.

    Quoted text wins; otherwise the counting preamble is stripped and the
    content clause is cut at the counting verb ("appear", "occur", "mention",
    "tell me") and trimmed of locative tails, so:
      "how many times does the litany against fear appear in your books"
    -> "litany against fear", and
      "find all the instances of the eyes of ibad in the dune series"
    -> "the eyes of ibad".
    A bare single word survives only when the question flags it as a word/
    phrase/term ("how often is the word melange used...") — a lone name in a
    "did X appear in Y" question is NOT a countable phrase.
    """
    q = str(question or "").strip()
    norm = (
        q.replace("“", '"').replace("”", '"')
        .replace("‘", "'").replace("’", "'")
    )
    # leading interjections ("yo, how many times...") defeat every anchored
    # preamble regex below — strip them before anything else.
    norm = _CENSUS_FILLER_LEAD_RE.sub("", norm, count=1).strip()
    m = re.search(r'(?<![\w])"([^"\n]{2,80})"', norm)
    if not m:
        m = re.search(r"(?<!\w)'([^'\n]{2,80})'", norm)
    quoted = bool(m)
    if quoted:
        phrase = m.group(1).strip()
    else:
        s = norm
        s = _CENSUS_SCOPE_LEAD_RE.sub("", s, count=1).strip()
        for _ in range(3):
            ns = _CENSUS_INSTANCE_LEAD_RE.sub("", s, count=1).strip()
            if ns == s:
                break
            s = ns
        for _ in range(4):
            ns = _CENSUS_PREFIX_RE.sub("", s).strip()
            if ns == s:
                break
            s = ns
        # verb residue left at the head ("mention the emperor", "uses the
        # phrase X") when the preamble ate the sentence's subject — the verb
        # is machinery, strip it when a noun phrase follows.
        s = _CENSUS_LEAD_VERB_RE.sub("", s, count=1).strip()
        s = _strip_census_tails(s)
        # "…and tell me how many there are" — request scaffolding after the phrase
        s = re.sub(r"\s+(?:and|then|so|but)?\s*tell\s+me\b.*$", "", s)
        s = re.sub(r"\s+(?:and|then|so|but)?\s*(?:how\s+many|the\s+number|a\s+number)\b.*$", "", s)
        s = _strip_census_tails(s)
        # Subject-verb shape ("the dune series mention the eyes of ibad"):
        # the counted phrase is the text AFTER the verb, when the verb's
        # subject is recognizable scope scaffolding, not phrase content.
        rv = _CENSUS_SUBJECT_VERB_RE.search(s)
        right_used = False
        if rv:
            left = s[:rv.start()]
            right = rv.group(1).strip()
            right_toks = re.findall(r"[A-Za-z][A-Za-z'-]*", right)
            right_content = [
                t for t in right_toks if t.lower() not in _SEARCH_STOPWORDS
            ]
            left_low = left.lower()
            scoped = bool(
                _SCOPE_MARK_RE.search(left)
                or any(w in _title_tokens() for w in re.findall(r"[a-z][a-z']{3,}", left_low))
            )
            if scoped and len(right_content) >= 1:
                s = right
                right_used = True
        mid = _CENSUS_MID_VERB_RE.search(s)
        if mid and not right_used:
            s = s[:mid.start()].strip()
        s = _strip_census_tails(s)
        s = re.sub(
            r"^(?:the|a|an|of|for|about|with|your|our|this)\s+", "", s
        )
        s = re.sub(
            r"^(?:the|a|an)?\s*(?:word|phrase|term|expression|name|idea|concept)\s+",
            "",
            s,
        ).strip()
        phrase = s
    tokens = re.findall(r"[A-Za-z][A-Za-z'-]*", phrase)
    content = [t for t in tokens if t.lower() not in _SEARCH_STOPWORDS]
    if not content:
        return None
    if len(content) > 8:
        return None
    if not quoted:
        if len(content) == 1:
            # a lone name/word survives when flagged ("the word melange") or
            # when the question is unambiguously a count ("how many times does
            # Paul appear"); a bare "did paul appear in messiah" still won't.
            if not _census_flagged(q, content[0].lower()) and not _has_census_intent(q):
                return None
        elif _CENSUS_META_WORDS.issuperset(t.lower() for t in content):
            # "how many words are in dune" -> "words are" is machinery, not a phrase
            return None
    return " ".join(tokens)


_CENSUS_ALT_JUNK = frozenset(
    {
        "variation", "variations", "spelling", "spellings", "version", "versions",
        "form", "forms", "wording", "wordings", "case", "cases", "thing", "things",
        "anything", "something", "word", "words", "phrase", "phrases", "term", "terms",
    }
)


def _census_segment_phrase(seg):
    """Countable phrase from one OR-segment of a counting question.

    "list me all the times allah or god is mentioned" splits into segments
    whose useful content is "allah" and "god" — each segment gets the same
    preamble/verb/tail stripping as a standalone question, but a lone word
    is allowed here: it is one alternative of an explicit "X or Y" list.
    """
    s = str(seg or "").strip()
    if not s:
        return None
    s = _CENSUS_FILLER_LEAD_RE.sub("", s, count=1).strip()
    s = _CENSUS_SCOPE_LEAD_RE.sub("", s, count=1).strip()
    for _ in range(3):
        ns = _CENSUS_INSTANCE_LEAD_RE.sub("", s, count=1).strip()
        if ns == s:
            break
        s = ns
    for _ in range(3):
        ns = _CENSUS_PREFIX_RE.sub("", s).strip()
        if ns == s:
            break
        s = ns
    s = _CENSUS_LEAD_VERB_RE.sub("", s, count=1).strip()
    s = _strip_census_tails(s)
    s = re.sub(r"\s+(?:and|then|so|but)?\s*tell\s+me\b.*$", "", s)
    s = re.sub(
        r"\s+(?:and|then|so|but)?\s*(?:how\s+many|the\s+number|a\s+number)\b.*$",
        "", s,
    )
    s = _strip_census_tails(s)
    mid = _CENSUS_MID_VERB_RE.search(s)
    if mid:
        s = s[:mid.start()].strip()
    s = _strip_census_tails(s)
    s = re.sub(r"^(?:the|a|an|of|for|about|with|your|our|this)\s+", "", s)
    s = re.sub(
        r"^(?:the|a|an)?\s*(?:word|phrase|term|expression|name|idea|concept)\s+",
        "", s,
    ).strip()
    tokens = re.findall(r"[A-Za-z][A-Za-z'-]*", s)
    content = [
        t for t in tokens
        if t.lower() not in _FLEX_STOPWORDS
        and t.lower() not in _CENSUS_META_WORDS
    ]
    if not content or len(content) > 4:
        return None
    if all(t.lower() in _CENSUS_ALT_JUNK for t in content):
        return None
    return s


def _census_or_phrases(question):
    """Alternative phrases from an explicit "X or Y" count question, or [].

    "…allah or god is mentioned" -> ["allah", "god"]; scaffolding variants
    ("any other variation of that") are dropped. Each surviving alternative
    is counted independently and merged into one combined census block by
    the caller, so an OR question never collapses into an AND-of-one.
    """
    q = str(question or "")
    if not re.search(r"(?<=\s)or(?=\s)", q, re.I):
        return []
    out, seen = [], set()
    for chunk in re.split(r"\s+or\s+", q, flags=re.I):
        for seg in re.split(r"\s*,\s*", chunk):
            p = _census_segment_phrase(seg)
            if p and p.lower() not in seen:
                seen.add(p.lower())
                out.append(p)
    return out if len(out) >= 2 else []


def _has_census_intent(question):
    q = (question or "").lower()
    if not q or len(q.split()) < 4:
        return False
    if _CENSUS_PREFIX_RE.match(q):
        return True
    return any(
        w in q
        for w in (
            "how many", "how often", "how frequently", "occurrence", "occurrences",
            "count of", "frequency", "mention", "mentions", "mentioned",
            "anywhere in your library", "every book that", "all mentions",
            "which books", "instances of", "all the instances", "every instance",
            "all instances", "number of times", "how many there are",
            "tell me how many", "find all the instances", "all the times",
            "all of the times", "find every mention", "find all mentions",
            "list every instance",
        )
    )


_FLEX_STOPWORDS = frozenset(
    _SEARCH_STOPWORDS
    | {
        "the", "a", "an", "of", "to", "in", "on", "at", "by", "for", "with",
        "from", "as", "and", "or", "but", "is", "are", "was", "were", "be",
        "been", "being", "it", "its", "that", "which", "against", "among",
        "through", "about", "into", "over", "under", "after", "before", "up",
        "down", "out", "off", "than", "so", "not", "no", "do", "does", "did",
        "this", "these", "those", "there", "here", "when", "where", "while",
        "why", "how", "all", "any", "both", "each", "few", "more", "most",
        "other", "some", "such", "only", "own", "same", "too", "very", "just",
        "like", "them", "their", "they", "we", "you", "your", "my", "our",
    }
)


_DIACRITIC_FOLD = None


def _diacritic_variants():
    """base ascii letter -> precomposed latin letters folding to it.

    Cached once: "a" -> {à á â … ā …}, so a search for "Allah" also matches
    "Allāh" and a census can't report a wrong count just because a book is
    transliterated with macrons.
    """
    global _DIACRITIC_FOLD
    if _DIACRITIC_FOLD is None:
        fold = {}
        for cp in range(0x00C0, 0x2B00):
            ch = chr(cp)
            dec = unicodedata.normalize("NFD", ch)
            if (
                len(dec) == 2
                and dec[0].isascii()
                and dec[0].isalpha()
                and unicodedata.category(dec[1]) == "Mn"
            ):
                fold.setdefault(dec[0], set()).add(ch)
        _DIACRITIC_FOLD = fold
    return _DIACRITIC_FOLD


def _census_token_re(tok):
    """Regex for one literal token, tolerant of latin diacritics.

    Each ascii letter matches its precomposed accented forms plus any
    combining marks that follow, without normalizing (and thus disturbing
    the offsets of) the source text.
    """
    fold = _diacritic_variants()
    out = []
    for ch in tok:
        low = ch.lower()
        variants = fold.get(low)
        if ch.isalpha() and variants:
            chars = re.escape(low) + "".join(
                re.escape(v) for v in sorted(variants)
            )
            out.append("[" + chars + "][\u0300-\u036f]*")
        else:
            out.append(re.escape(ch))
    return "".join(out)


def _census_pattern(phrase_tokens):
    """Compiled case-insensitive matcher tolerant of stopword noise.

    "eyes of ibad" and "eyes of the Ibad" both match: between the *content*
    words, any punctuation and up to a handful of stopword tokens are
    allowed, so missing or extra little words never zero out a count. A
    phrase whose only meaningful word is stopword-framed ("the end") stays
    literal rather than matching every bare "end".
    """
    if not phrase_tokens:
        return None
    core = [t for t in phrase_tokens if t.lower() not in _FLEX_STOPWORDS]
    if not core:
        core = phrase_tokens
    if len(core) == 1 and len(phrase_tokens) > 1:
        # "in the end" -> exact sequence, flexible punctuation only
        return re.compile(
            r"\b"
            + r"[\s\W]{1,6}".join(_census_token_re(t) for t in phrase_tokens)
            + r"\b",
            re.I,
        )
    if len(core) == 1:
        return re.compile(r"\b" + _census_token_re(core[0]) + r"\b", re.I)
    allow = "|".join(re.escape(w) for w in sorted(_FLEX_STOPWORDS))
    gap = r"(?:(?:" + allow + r")\s+|[\s\W]){0,16}"
    pat = r"\b" + _census_token_re(core[0])
    for w in core[1:]:
        pat += gap + _census_token_re(w)
    pat += r"\b"
    return re.compile(pat, re.I)


def _census_count_in(text, phrase_tokens):
    """Occurrences of the phrase in ``text`` (see _census_pattern)."""
    if not text or not phrase_tokens:
        return 0
    pat = _census_pattern(phrase_tokens)
    return len(pat.findall(text)) if pat else 0


_CENSUS_MAX_BOOK_LINES = 36
_CENSUS_MAX_CHAPTERS = 12


def _render_census_report(scope, phrase, question="", bare=False):
    """Full-text occurrence census across every work in scope -> prompt block.

    Counts the story text only: chapters whose spine marker is front/back
    matter (appendices, glossaries, praise pages, afterwords) are tallied
    separately and excluded, unless the question explicitly asks for them.
    Duplicated ebook chapters (the same marker AND text appearing twice in a
    broken epub) are counted once.
    Sized for giant libraries: chapter lists per book and zero-count book
    lines are capped so a common word across hundreds of books still yields
    a readable, budget-safe block.
    """
    phrase_tokens = phrase.split()
    pattern = _census_pattern(phrase_tokens)
    if pattern is None:
        return ""
    q_ask = _query_sections(question) if question else []
    # The "related wording" inventory: for a distinctive concept head word
    # (e.g. 'ibad'), also report where the WORD appears WITHOUT the exact
    # phrase ("the blue of the Ibad", "total blue of the Ibad") so a census
    # of "eyes of ibad" can say "2 exact, plus N concept-adjacent uses" —
    # models must never have to guess at related sites.
    head = ""
    for tok in reversed(re.findall(r"[A-Za-z][A-Za-z'-]*", phrase)):
        if (
            tok.lower() not in _FLEX_STOPWORDS
            and tok.lower() not in _CENSUS_META_WORDS
            and len(tok) >= 3
        ):
            head = tok.lower()
            break
    head_re = None
    try:
        if head and _fts_count(head) <= 300:
            head_re = re.compile(
                r"(?<![A-Za-z'])"
                + _census_token_re(head)
                + r"(?![A-Za-z'])",
                re.I,
            )
    except Exception:
        head_re = None
    lines = []
    total = 0
    scanned = 0
    zeros_skipped = 0
    head_total = 0
    related_rows = []  # (title, [(marker, count, snippet)])
    for it in scope:
        source_docs = []
        rels = []
        for rel in _load_manifest():
            if _title_canon(rel) == it["id"]:
                rels.append(rel)
        rels.sort(key=lambda r: (".epub" not in r, len(r)))
        try:
            path = KNOWLEDGE_ROOT / rels[0]
            docs = _staged_texts(path)
            if docs is None:
                docs = _stage_file(path)
            source_docs = docs or []
        except Exception:
            source_docs = []
        if not source_docs:
            continue
        scanned += 1
        chapters = []
        apparatus = []
        other = []  # (marker, head-only count, snippet|None)
        work_total = 0
        seen_docs = set()
        for d in source_docs:
            text = str(d.get("text") or "")
            if not text:
                continue
            marker = (d.get("marker") or "").strip() or "(whole book)"
            dup_key = (
                _norm_label(marker),
                re.sub(r"\s+", " ", text[:500].lower())[:300],
            )
            if dup_key in seen_docs:
                continue  # broken ebooks duplicate the same chapter twice
            seen_docs.add(dup_key)
            n = len(pattern.findall(text))
            if n == 0 and head_re is None:
                continue
            sec = _boiler_section_of(marker)
            is_apparatus = bool(sec) and sec not in q_ask
            if head_re and not is_apparatus:
                hn = len(head_re.findall(text))
                head_total += hn
                if hn > 0 and hn > n:
                    snip = None
                    mh = head_re.search(text)
                    if mh:
                        s = max(0, mh.start() - 60)
                        snip = "…" + re.sub(
                            r"\s+", " ", text[s:mh.end() + 60]
                        ).strip() + "…"
                    other.append((marker, hn - n, snip))
            if n == 0:
                continue
            m = pattern.search(text)
            ex = ""
            if m:
                s = max(0, m.start() - 90)
                ex = "…" + re.sub(r"\s+", " ", text[s:m.end() + 90]).strip() + "…"
            (apparatus if is_apparatus else chapters).append((marker, n, ex))
        work_total = sum(n for _, n, _ in chapters)
        total += work_total
        if work_total == 0 and scanned > len(lines) + 1 and len(lines) >= _CENSUS_MAX_BOOK_LINES:
            zeros_skipped += 1
            continue
        shown = chapters[:_CENSUS_MAX_CHAPTERS]
        where = ", ".join(f"{c[0]} (x{c[1]})" for c in shown) or "nowhere"
        if len(chapters) > len(shown):
            where += f" … (+{len(chapters) - len(shown)} more chapters)"
        copies = []
        for k in it["keys"]:
            if k == it["primary"]:
                continue
            raw = _book_map().get(k, {}).get("raw", k)
            copies.append(str(raw).split(" › ")[-1])
        dup = f"  (duplicate copy: {', '.join(_clean_name(c) for c in copies)})" if copies else ""
        app_note = ""
        if apparatus:
            app_total = sum(n for _, n, _ in apparatus)
            names = ", ".join(dict.fromkeys(c[0] for c in apparatus[:3]))
            app_note = (
                f"  (+{app_total} more in front/back matter — {_escape_format(names)} — "
                f"not counted)"
            )
        lines.append(f"- {_escape_format(it['title'])} — {work_total}: {where}{app_note}{dup}")
        for marker, n, ex in chapters[:4]:
            if ex:
                lines.append(f"    · {_escape_format(marker)}: {_escape_format(ex[:220])}")
        if other:
            related_rows.append((it["title"], other))
    if not lines:
        return ""
    if related_rows and head_total <= 60:
        for title, other in related_rows[:6]:
            descs = []
            for marker, cnt, _snip in other[:4]:
                unit = "use" if cnt == 1 else "uses"
                descs.append(f"{marker} ({cnt} {unit})")
            desc = ", ".join(descs)
            if len(other) > 4:
                desc += f" (+{sum(c for _, c, _ in other[4:])} more)"
            snip = next((s for _, _, s in other if s), None)
            lines.append(
                f"  · {_escape_format(title)} — related wording, NOT part of the "
                f"count above: the word “{head}” appears without the exact phrase in "
                f"{desc}."
                + (f" e.g. {_escape_format(snip)}" if snip else "")
            )
    if zeros_skipped:
        lines.append(
            f"- … and {zeros_skipped} more scanned work(s) with no occurrence of "
            f"the phrase (every work in scope was swept)."
        )
    body = "\n".join(lines)
    if bare:
        # Multi-variant censuses merge several bare bodies under one header.
        return body
    head = (
        "\n\nExact library census for \"{}\" — occurrence counts from a full-text "
        "scan of {} book(s), counted verbatim against the story text "
        "(case-insensitive; duplicates of the same book or chapter counted once; "
        "missing little words like 'the' don't change a count). Front/back matter "
        "(appendices, glossaries, praise pages, afterwords) is NOT counted unless "
        "asked for. THESE NUMBERS ARE AUTHORITATIVE: base every numeric statement "
        "on them, never on the retrieved excerpts below, which are samples. A book "
        "absent from this list was not part of the question's scope, not a book "
        "you may assume silent.\n".format(_escape_format(phrase), scanned)
    )
    instr = (
        "\n\nCensus instructions: report the count for each relevant book and name "
        "the chapters/places where it occurs. If a book the user asked about is "
        "absent from the census (e.g. the exact phrase could not be counted), say "
        "so plainly rather than guessing a number."
    )
    return head + "\n".join(lines) + instr


def _best_spelling_fix(toks):
    """One best-effort corrected phrase: each word nearest to the library
    vocabulary — equal-distance ties resolved by corpus frequency, so 'eys'
    becomes 'eyes' (common) rather than 'keys'."""
    out = list(toks)
    try:
        vocab = _library_vocab()
    except Exception:
        vocab = set()
    if not vocab:
        return out
    for i, t in enumerate(out):
        tl = t.lower()
        if tl in _FLEX_STOPWORDS or len(tl) < 3 or len(tl) > 12:
            continue
        if tl in vocab:
            continue  # already a real word — never "fix" a correct spelling
        try:
            cands = difflib.get_close_matches(tl, vocab, n=8, cutoff=0.80)
        except Exception:
            cands = []
        best, best_r = None, 0.0
        for cw in cands:
            if cw == tl:
                continue
            r = difflib.SequenceMatcher(None, tl, cw).ratio()
            if r > best_r + 1e-9:
                best, best_r = cw, r
            elif abs(r - best_r) < 1e-9 and best is not None:
                try:
                    if _fts_count(cw) > _fts_count(best):
                        best = cw
                except Exception:
                    pass
        if best and best_r >= 0.82:
            out[i] = best
    return out


def _census_guard_block(question):
    """Instruction block when a count is wanted but no phrase can be counted."""
    q = str(question or "")[:400]
    return (
        "\n\nThe user's question asks for a COUNT or exhaustive list, but no "
        "single phrase could be extracted to census. The retrieved passages "
        "above are a SAMPLE, not the full text of any book. Do NOT state or "
        "imply exact counts (\"appears 0 times\", \"in all six books\"); if you "
        "cannot give an exact number, say plainly that an exact count is not "
        "available from the passages, then answer with what the passages do "
        f"show.\n[count question: {_escape_format(q)}]"
    )


_ENUMERATION_RE = re.compile(
    r"\b(?:list|enumerate|show all|all the (?:times|mentions|occurrences|"
    r"instances|verses)|every (?:time|mention|occurrence|instance|verse)|"
    r"all (?:mentions|occurrences|times|instances|verses))\b",
    re.I,
)


def _census_enumeration_guard(question, total):
    """Guardrail for 'list every occurrence' asks whose true count is huge.

    The census block above already holds the authoritative numbers and the
    per-book/chapter breakdown. Left alone, the model tries to enumerate all
    of them and invents locations; this tells it to summarize deterministically
    instead. Returns '' when the ask is not an enumeration or the total is
    small enough to list.
    """
    if os.getenv("MENTAT_NO_ENUM_GUARD"):
        return ""
    q = str(question or "")
    try:
        n = int(total)
    except Exception:
        return ""
    if n <= 20 or not _ENUMERATION_RE.search(q):
        return ""
    return (
        "\n\nEnumeration guard: the user asked to list occurrences, but the "
        f"authoritative count is {n} — far too many to enumerate. Do NOT "
        "attempt an exhaustive list and do NOT invent quotes or locations. "
        "State the exact total, give the per-book (and, where the census shows "
        "it, per-chapter) breakdown above, and quote at most three short "
        "examples ONLY if they appear verbatim in the evidence above. Never "
        "fabricate a quote, chapter, page, or verse number."
    )


def _census_ctx(question, strategy):
    """Comprehension-driven count handling.

    Returns {"block": ..., "keys": set|None, "phrase": ...}:
      - block: the exact census report (authoritative numbers) when a phrase
        could be counted, or a guard block when a count is wanted but no
        phrase exists.
      - keys:  book keys whose passages are allowed (scope filter), or None.
    The understanding (is this a count? which phrase?) comes from the fast
    model's analysis when available; keyword heuristics are the offline
    fallback. The phrase is VERIFIED by actually counting it: if the most
    specific phrase matches nothing but a shorter variant matches, the
    variant is counted (models propose, deterministic code disposes).
    """
    an = _analysis(question)
    kind = str(an.get("kind") or "").lower()
    count_kind = kind in ("count", "census", "occurrence", "instances", "counts")
    heuristic = _has_census_intent(question)
    if not (count_kind or heuristic):
        # A bare continuation of a counting conversation ("the whole series, i
        # need a number") can be classified "chat" by the fast model even
        # though it asks for the count we just produced — recognize the shape
        # deterministically so session memory still kicks in.
        prior_an = _prior_analysis(_current_conv_id())
        prior_kind = str(prior_an.get("kind") or "").lower()
        prior_cm = _prior_census(_current_conv_id())
        ql = str(question or "").lower()
        if (
            (prior_kind in ("count", "census", "occurrence", "instances", "counts")
             or prior_cm.get("phrase"))
            and re.search(
                r"\b(?:whole|entire|full|all|total|number|series|books?|novels?|"
                r"them|then|count|again|too|same)\b",
                ql,
            )
            and len(ql.split()) <= 12
            and not _named_books(ql)
            and not re.search(r"[\"“”']", ql)
        ):
            count_kind = True
    if not (count_kind or heuristic):
        return {"block": "", "keys": None, "phrase": None}

    q = str(question or "")
    quoted_raw = bool(
        re.search(r"(?<![\w])[\"“”']([^\"“”'\n]{2,80})[\"“”']", q)
    )
    candidates = []  # (phrase, is_spelling_fix)
    seen = set()
    model_phrase = str(an.get("phrase") or "").strip().strip('"“”’‘`')
    for cand in (model_phrase, _census_phrase(question)):
        c = re.sub(r"\s+", " ", cand or "").strip().strip('"“”’‘`')
        if not c:
            continue
        if not quoted_raw:
            # the classifier (or the question itself) may echo trailing scope
            # words ("eyes of ibad in dune") — strip them like the heuristic
            # path does so the count runs on the phrase, not the locative.
            c = _strip_census_tails(c)
        if not c:
            continue
        toks = re.findall(r"[A-Za-z][A-Za-z'-]*", c)
        content = [t for t in toks if t.lower() not in _FLEX_STOPWORDS]
        if not content or len(content) > 8:
            continue
        if (
            not quoted_raw
            and _CENSUS_META_WORDS.issuperset(t.lower() for t in content)
            and not (len(content) == 1 and _census_flagged(q, content[0].lower()))
        ):
            continue
        key = " ".join(t.lower() for t in toks)
        if key in seen:
            continue
        seen.add(key)
        candidates.append((c, False))
        # fallback: drop trailing tokens so scaffolding residue ("...in the
        # dune series") can never zero out a genuine count. A suffix made only
        # of counting machinery ("list", "all the times") is never a phrase —
        # otherwise a bare request word with hits everywhere ("list") would
        # outrank every zero-report and poison the census.
        if not quoted_raw and len(content) >= 2:
            while len(toks) > 1:
                toks = toks[:-1]
                low = " ".join(t.lower() for t in toks)
                if low in seen:
                    continue
                residual = [
                    t for t in toks
                    if t.lower() not in _FLEX_STOPWORDS
                    and t.lower() not in _CENSUS_META_WORDS
                ]
                if not residual:
                    continue
                seen.add(low)
                candidates.append((" ".join(toks), False))
    # Explicit "X or Y" alternatives get a merged census: each variant is
    # counted independently. Without this, the AND-pattern of a single
    # phrase ("allah or god") counts near-zero — or collapses to one bare
    # word — and the whole question is answered from a wrong number.
    if not quoted_raw:
        try:
            or_parts = _census_or_phrases(question)
        except Exception:
            or_parts = []
        if or_parts:
            candidates.insert(0, (or_parts, False))
    # spelling rescue: "eys of ibad" never matches, but the text has
    # "eyes of the Ibad". One best fix per phrase, verified by counting, and
    # fixes are only used when no unmodified phrasing hit anything — so a
    # typo can rescue a real count but can never override a clean one.
    if not quoted_raw:
        for c, _fix in list(candidates):
            if not isinstance(c, str):
                continue  # merged OR-variant lists are already verified
            toks = re.findall(r"[A-Za-z][A-Za-z'-]*", c)
            if len(toks) < 2:
                continue
            try:
                fixed = _best_spelling_fix(toks)
                fkey = " ".join(t.lower() for t in fixed)
                if fixed != toks and fkey not in seen:
                    seen.add(fkey)
                    candidates.append((" ".join(fixed), True))
            except Exception:
                pass

    # Session inheritance: a bare follow-up ("the whole series, i need a
    # number", "how many total across the books") carries no phrase of its
    # own. Mentat remembers — inherit the last counted phrase of
    # THIS conversation (and the question that scoped it) so the census
    # still runs instead of giving up. The inherited phrase is verified by
    # actually counting it, exactly like every other candidate.
    scope_anchor_q = ""
    if not candidates:
        prior_cm = _prior_census(_current_conv_id())
        if prior_cm.get("phrase"):
            c = re.sub(r"\s+", " ", str(prior_cm["phrase"])).strip().strip('"“”’‘`')
            toks = re.findall(r"[A-Za-z][A-Za-z'-]*", c)
            content = [t for t in toks if t.lower() not in _FLEX_STOPWORDS]
            if (
                content
                and len(content) <= 8
                and not _CENSUS_META_WORDS.issuperset(t.lower() for t in content)
            ):
                candidates.append((c, False))
                scope_anchor_q = str(prior_cm.get("question") or "")

    sweep_all = strategy == "universal" or _has_library_wide_intent(question)

    def _explicit_scope(q):
        """Does the question NAME specific works? Named questions keep their
        census in scope — content-verification must not drag phrase-bearing
        books into a Bible question because the phrase also lives in Dune."""
        try:
            return any(_books_matching(t) for t in _derive_terms(q or "", cap=16))
        except Exception:
            return False

    q_explicit = _explicit_scope(question)
    anchor_explicit = bool(scope_anchor_q) and _explicit_scope(scope_anchor_q)

    def _scope_for(phrase):
        try:
            scope = _resolve_scope(
                question,
                strategy,
                sweep_all=sweep_all,
                verify_terms=[phrase],
                named_only=q_explicit and not sweep_all,
            )
            if not scope and scope_anchor_q:
                # the follow-up names no books — resolve scope from the
                # conversation's earlier census question instead.
                scope = _resolve_scope(
                    scope_anchor_q,
                    strategy,
                    sweep_all=sweep_all,
                    verify_terms=[phrase],
                    named_only=anchor_explicit and not sweep_all,
                )
        except Exception:
            scope = None
        return scope

    def _eval_single(phrase):
        """(block, keys, total) for one plain phrase."""
        scope = _scope_for(phrase)
        if not scope:
            return "", None, 0
        block = ""
        try:
            block = _render_census_report(scope, phrase, question=question)
        except Exception:
            block = ""
        if not block:
            return "", None, 0
        keys = set()
        for it in scope:
            keys.update(it.get("keys") or [])
        total = sum(
            int(x) for x in re.findall(r"— (\d+):", block) if int(x) >= 0
        )
        return block, keys, total

    def _eval(phrase):
        """(block, keys, total) for one phrase or an OR-list of variants.

        An OR-list counts each alternative independently and merges the
        results into one combined block; zero-hit alternatives are dropped
        when at least one variant hits (so a junk segment can never pad the
        report), and the total is the sum across variants.
        """
        if not isinstance(phrase, (list, tuple)):
            return _eval_single(phrase)
        rows = []  # (variant, total, bare body)
        keys = set()
        for part in phrase:
            scope = _scope_for(part)
            if not scope:
                continue
            try:
                body = _render_census_report(
                    scope, part, question=question, bare=True
                )
            except Exception:
                body = ""
            if not body:
                continue
            total = sum(int(x) for x in re.findall(r"— (\d+):", body))
            rows.append((part, total, body))
            for it in scope:
                keys.update(it.get("keys") or [])
        if not rows:
            return "", None, 0
        hit_rows = [r for r in rows if r[1] > 0]
        if hit_rows:
            rows = hit_rows
        names = ", ".join(f"“{_escape_format(p)}”" for p, _, _ in rows)
        header = (
            "\n\nCombined library census for the variants {} — each variant was "
            "counted independently against the full text in scope "
            "(case-insensitive; duplicate copies counted once; a sentence may "
            "count toward more than one variant). THESE NUMBERS ARE "
            "AUTHORITATIVE: base every numeric statement on them, never on the "
            "retrieved excerpts below, which are samples.\n".format(names)
        )
        body_parts = [
            f"\nVariant “{_escape_format(p)}” — {total} occurrence(s) in scope:\n\n{body}"
            for p, total, body in rows
        ]
        instr = (
            "\n\nCensus instructions: report each variant's count separately, "
            "name the books and chapters where it occurs, and never merge the "
            "variants into a single number. If a variant the user asked about "
            "could not be counted, say so plainly rather than guessing."
        )
        return header + "\n".join(body_parts) + instr, keys, sum(r[1] for r in rows)

    original_hits = [p for p, fix in candidates if not fix and _eval(p)[2] > 0]
    usable = [(p, fix) for p, fix in candidates if not fix or not original_hits]
    # Two passes: a real hit ALWAYS outranks any zero-report. A zero-report
    # from a scaffold-poisoned phrase ("eyes of ibad in dune" — the trailing
    # scope words were never stripped) must never shadow the true count of a
    # shorter clean phrase ("eyes of ibad" = 2). Among phrases with hits the
    # longest wins ("eyes of ibad" over the looser "eyes of"); ties go to more
    # occurrences. Zero-reports matter only when every candidate truly misses,
    # and then the most specific one is the honest answer.
    hit_block, hit_keys, hit_phrase, hit_total, hit_words = "", None, None, 0, 0
    zero_block, zero_keys, zero_phrase, zero_words = "", None, None, 0
    for phrase, is_fix in usable:
        block, keys, total = _eval(phrase)
        if not block:
            continue
        label = " or ".join(phrase) if isinstance(phrase, (list, tuple)) else phrase
        n_words = len(re.findall(r"[A-Za-z]+", label))
        if total > 0:
            if n_words > hit_words or (n_words == hit_words and total > hit_total):
                hit_block, hit_keys, hit_phrase, hit_total, hit_words = (
                    block, keys, phrase, total, n_words
                )
        elif n_words > zero_words:
            zero_block, zero_keys, zero_phrase, zero_words = (
                block, keys, phrase, n_words
            )
    def _phrase_label(p):
        return " or ".join(p) if isinstance(p, (list, tuple)) else p

    if hit_block:
        _remember_census(question, _phrase_label(hit_phrase), hit_total)
        guard = _census_enumeration_guard(question, hit_total)
        return {
            "block": hit_block + guard,
            "keys": hit_keys,
            "phrase": _phrase_label(hit_phrase),
        }
    if zero_block:
        return {"block": zero_block, "keys": zero_keys, "phrase": _phrase_label(zero_phrase)}
    if count_kind or heuristic:
        # No countable phrase — still scope the passages to the books the
        # question names, so a Dune-series question never cites the whole
        # library while the guard tells the model not to invent numbers.
        gkeys = None
        try:
            gscope = _resolve_scope(
                question, strategy, sweep_all=sweep_all, named_only=True
            )
            gkeys = set()
            for it in gscope or []:
                gkeys.update(it.get("keys") or [])
            gkeys = gkeys or None
        except Exception:
            gkeys = None
        return {
            "block": _census_guard_block(question),
            "keys": gkeys,
            "phrase": None,
        }
    return {"block": "", "keys": None, "phrase": None}


def _census_block(question, strategy):
    """Prompt block for counting questions: an exact full-text census, or ''.

    Driven by the front-end comprehension (fast model) with the keyword
    heuristics as offline fallback. The counted phrase is verified against
    the texts, so a census can only report zero when the phrase is truly
    absent.
    """
    try:
        return _census_ctx(question, strategy).get("block") or ""
    except Exception:
        return ""


def _census_mismatches(answer, block):
    """Deterministic spot-check of the answer's counts against the census.

    Looks at the text between a book mention and the word 'Chapter' (or end
    of the line): if the model attached a number there that disagrees with
    the census, that is flagged. Never complains about chapter numbers, and
    stays silent when the claim is vague.
    """
    if not answer or not block:
        return []
    rows = []
    for line in block.splitlines():
        if not line.startswith("- "):
            continue
        m = re.match(r"- (.*?) — (\d+):", line)
        if m:
            rows.append((m.group(1).strip(), int(m.group(2))))
    out = []
    all_cores = [
        t.split(" (")[0].split(".epub")[0].strip() for t, _ in rows
    ]
    all_cores = [c for c in all_cores if len(c) >= 3]
    for title, actual in rows:
        if actual == 0:
            continue
        core = title.split(" (")[0].split(".epub")[0].strip()
        if len(core) < 3:
            continue
        for m in re.finditer(r"\b" + re.escape(core) + r"\b", answer):
            seg = answer[max(0, m.start() - 40): m.start() + 220]
            seg = re.split(r"\bChapter\b", seg, maxsplit=1)[0]
            seg = seg.split("\n")[0]
            # "Dune" is a substring of "Dune Messiah"/"Children of Dune" —
            # if another census title appears inside this segment the claim
            # is ambiguous ("...Dune Messiah ... have 0 occurrences" is about
            # Messiah, not Dune) and must not be flagged.
            if any(
                c != core and re.search(r"\b" + re.escape(c) + r"\b", seg)
                for c in all_cores
            ):
                continue
            nums = [int(n) for n in re.findall(r"\b(\d+)\b", seg)]
            if nums and all(n != actual for n in nums):
                out.append(
                    f"{core}: answer says {nums[0]}, census counts {actual}"
                )
                break
    # grand-total claims without book names ("I count 12 across the six novels")
    grand = sum(n for _, n in rows)
    if grand > 0:
        for m in re.finditer(
            r"(?:i\s+count(?:ed)?\s+(\d+))"
            r"|(?:there\s+are\s+(\d+)\s+(?:of|occurrences?|mentions?|times?))"
            r"|(?:\b(\d+)\s+(?:occurrences?|times?|mentions?|instances?)\s*"
            r"(?:in\s+|across\s+|among\s+)(?:the\s+)?(?:six|entire|whole|all|total))"
            r"|(?:appears?\s+(\d+)\s+times)",
            answer,
            re.I,
        ):
            claimed = next((int(g) for g in m.groups() if g), None)
            if claimed is not None and claimed != grand:
                out.append(
                    f"overall count: answer says {claimed}, census counts {grand}"
                )
                break
    return out


def _retrieval_strategy(question, score):
    settings = _load_settings()
    depth = settings.get("search_depth", "auto")
    if depth == "off":
        return "simple"
    if depth == "always":
        return "agent"
    if _has_hunt_intent(question):
        return "hunt"
    intent = _has_find_intent(question)
    # Multi-book/author questions can never take the lazy simple path.
    try:
        if len(_named_books(question)) >= 2:
            return "agent"
    except Exception:
        pass
    if score < 0.20 and not intent:
        return "simple"
    if score >= 0.45 or intent:
        return "agent"
    return "expand"


def _has_quote_intent(question):
    """Wants verbatim passages with citations. The classifier's ``quotes``
    kind is authoritative when present; the keyword list is the offline
    fallback (natural phrasing like "give me the passage where..." or
    "what exactly does Stilgar say" only the model can catch)."""
    an = _analysis(question)
    if str(an.get("kind") or "").lower() == "quotes":
        return True
    if _has_hunt_intent(question):
        return True
    q = question.lower()
    return any(
        w in q
        for w in (
            "quote", "quotes", "litany", "poem", "poems", "song", "songs",
            "hymn", "verse", "verses", "recite", "verbatim", "full text",
            "passage", "exact words", "word for word",
        )
    )


_HUNT_RE = re.compile(
    r"^find:"
    r"|\bhalf[- ]remember\w*\b"
    r"|\b(?:find|locate|hunt for|looking for|search for)\b[^.?!]{0,40}"
    r"\b(?:quote|quotes|passage|passages|line|lines|verse|verses|phrase|"
    r"wording|words)\b"
    r"|\bwhere\s+(?:does|do|is|are|can i find|might i find)\b[^.?!]{0,40}"
    r"\b(?:say|says|said|write|writes|wrote|mention|mentions|mentioned|"
    r"appear|appears|occur|occurs)\b",
    re.I,
)


def _has_hunt_intent(question):
    """A half-remembered quote/passage hunt ("/find", "where does he say…")."""
    return bool(_HUNT_RE.search(str(question or "")))


def _hunt_phrases(question):
    """Quoted phrases first, else the question's content terms."""
    q = str(question or "")
    quoted = re.findall(r"[\"“”'‘’]([^\"“”'‘’\n]{3,80})[\"“”'‘’]", q)
    phrases = [p.strip() for p in quoted if p.strip()]
    terms = [
        t for t in _derive_terms(q, cap=10)
        if t.lower() not in _SCOPE_JUNK_TERMS
        and t.lower() not in _CENSUS_META_WORDS
    ]
    return phrases, terms


def _hunt_passages_uncached(question, limit=36):
    """Exact-first passage hunt: phrase, rare-term AND, spelling rescue, BM25.

    Half-remembered quotes need literal recall, not just semantic similarity:
    three FTS passes (quoted phrase → rarest-terms AND → broad OR), spelling
    rescue when a phrase or term misses, coverage-weighted scoring, then
    verbatim windows anchored on the first matching word, diversified across
    books. Deterministic and fast — the LLM only sees the winners.
    """
    phrases, terms = _hunt_phrases(question)
    if not phrases and not terms:
        return []
    by_id = {c["chunk_id"]: c for c in _load_chunk_texts()}
    if not by_id:
        return []
    scores = {}

    def _consider(cids, base):
        for rank, cid in enumerate(cids or []):
            if not cid or cid not in by_id:
                continue
            scores[cid] = scores.get(cid, 0.0) + base + max(0.0, 3.0 - rank * 0.1)

    for phrase in phrases[:3]:
        cids = _fts_search([phrase], limit=limit * 2)
        _consider(cids, 8.0)
        if not cids:
            try:
                for fixed in _correct_phrase_variants(phrase)[:3]:
                    cids2 = _fts_search([fixed], limit=limit * 2)
                    if cids2:
                        _consider(cids2, 7.0)
                        break
            except Exception:
                pass
    rare = sorted([t for t in terms if len(t) >= 3], key=_fts_count)[:4]
    if len(rare) >= 2:
        try:
            _consider(_fts_search_and(rare, limit=limit * 2), 6.0)
        except Exception:
            pass
        try:
            fixed_terms = _best_spelling_fix(list(rare))
            if fixed_terms and fixed_terms != rare:
                _consider(_fts_search_and(fixed_terms, limit=limit * 2), 5.5)
        except Exception:
            pass
        # half-heard words: terms with zero index hits get their best phonetic
        # soundalikes, still verified by requiring the other rare terms.
        try:
            zero_hit = [
                (i, _phonetic_match(t)[:3])
                for i, t in enumerate(rare)
                if _fts_count(t) == 0
            ]
            for i, cands in zero_hit[:2]:
                for cand in cands:
                    trial = list(rare)
                    trial[i] = cand
                    _consider(_fts_search_and(trial, limit=limit * 2), 5.0)
        except Exception:
            pass
    try:
        _consider(_fts_search(terms or phrases, limit=limit * 3), 3.0)
    except Exception:
        pass
    # sentence-level pass: spans give exact anchors for half-remembered lines.
    span_by_chunk = {}
    try:
        if _load_settings().get("spans_enabled", True):
            for base, qlist in ((7.5, phrases[:2]), (4.5, terms[:6])):
                if not qlist:
                    continue
                for s in _span_search(qlist, limit=limit * 2):
                    cid = s.get("chunk_id")
                    if not cid or cid not in by_id:
                        continue
                    scores[cid] = scores.get(cid, 0.0) + base
                    if cid not in span_by_chunk or base >= 7.0:
                        span_by_chunk[cid] = s
    except Exception:
        pass
    if not scores:
        return []
    term_set = {t.lower() for t in terms}
    ranked = []
    for cid, score in scores.items():
        c = by_id.get(cid)
        if not c:
            continue
        low = str(c.get("content") or "").lower()
        cover = sum(1 for t in term_set if t in low)
        bonus = sum(6.0 for p in phrases[:2] if p.lower() in low)
        ranked.append((score + cover * 1.5 + bonus, c))
    ranked.sort(key=lambda x: -x[0])
    out, per_book = [], {}
    needles = [str(x).lower() for x in (phrases + terms) if str(x).strip()]
    for _score, c in ranked:
        book = _book_key(c.get("file_path", ""))
        if per_book.get(book, 0) >= 6:
            continue
        content = str(c.get("content") or "")
        span = span_by_chunk.get(c.get("chunk_id"))
        if span:
            anchor = str(span.get("text") or content[:1100]).strip()[:1400]
        else:
            low = content.lower()
            anchor = ""
            for needle in needles:
                i = low.find(needle)
                if i >= 0:
                    anchor = content[max(0, i - 240) : i + 900]
                    break
            if not anchor:
                anchor = content[:1100]
        out.append(
            {
                "file_path": c.get("file_path", ""),
                "content": content,
                "excerpt": anchor,
                "chunk_id": c.get("chunk_id"),
                "span": bool(span),
            }
        )
        per_book[book] = per_book.get(book, 0) + 1
        if len(out) >= limit:
            break
    return out


_HUNT_CACHE = {}
_HUNT_CACHE_TTL = 300.0


def _hunt_passages(question, limit=36):
    """Cached wrapper around the deterministic hunt (setting-driven TTL)."""
    try:
        ttl = float(_load_settings().get("hunt_cache_ttl", 300) or 0)
    except Exception:
        ttl = 300.0
    key = (str(question or "").strip().lower(), int(limit))
    now = time.time()
    if ttl > 0:
        hit = _HUNT_CACHE.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    out = _hunt_passages_uncached(question, limit=limit)
    if ttl > 0:
        _HUNT_CACHE[key] = (now, out)
        if len(_HUNT_CACHE) > 64:
            for stale, _ in sorted(_HUNT_CACHE.items(), key=lambda kv: kv[1][0])[:16]:
                _HUNT_CACHE.pop(stale, None)
    return out


def _named_sources(question):
    """Proper nouns in the question that name a specific book/author in the vault."""
    proper = [
        w.lower()
        for w in re.findall(r"[A-Z][A-Za-z'-]{2,}", _normalize_query(question))
        if w.lower() not in _SEARCH_STOPWORDS
    ]
    out = []
    for t in proper:
        if any(
            re.search(rf"\b{re.escape(t)}\b", c["file_path"].lower())
            for c in _load_chunk_texts()
        ):
            out.append(t)
    return out


_INVENTED_OPEN = "⟪"
_INVENTED_CLOSE = "⟫"


def _clean_markers(text):
    """Strip invented-content markers from plain-text copies (clipboard, CLI)."""
    return str(text or "").replace(_INVENTED_OPEN, "").replace(_INVENTED_CLOSE, "")


def _style_invented(text):
    """Convert ⟪…⟫ invented spans to bold (**…**) so the TUI's .msg-ai .strong
    CSS renders them light blue, distinct from the books' own words.

    Bold is applied per paragraph so stanza breaks (blank lines) inside a
    marked poem survive CommonMark's strong-span rules.
    """
    s = str(text or "")
    out = []
    buf = []
    depth = 0
    for ch in s:
        if ch == _INVENTED_OPEN:
            depth += 1
            if depth == 1:
                out.append("".join(buf))
                buf = []
            continue
        if ch == _INVENTED_CLOSE:
            if depth > 0:
                depth -= 1
                if depth == 0:
                    seg = "".join(buf)
                    buf = []
                    out.append(_bold_paragraphs(seg))
            continue
        buf.append(ch)
    out.append("".join(buf))
    return "".join(out)


def _bold_paragraphs(seg):
    parts = re.split(r"\n{2,}", seg)
    return "\n\n".join(f"**{p}**" if p.strip() else p for p in parts)


def _escape_format(text):
    """Escape braces so blocks appended to the system TEMPLATE survive .format().

    LightRAG runs .format() on the whole system prompt; a literal '{' in a
    passage (common in the Study Quran, Kojève, Boer) would raise
    'Single { encountered' and the answer silently returns empty.
    """
    return str(text).replace("{", "{{").replace("}", "}}")


_STAGED_MAP = None


def _staged_paths():
    """book key -> vault Path, for expanding citations from the staged text."""
    global _STAGED_MAP
    if _STAGED_MAP is None:
        m = {}
        for path in _iter_knowledge_files():
            for cand in (_clean_name(str(path)), _clean_name(str(path)).replace("/", " › ")):
                m[_book_key(cand)] = path
        _STAGED_MAP = m
    return _STAGED_MAP


def _long_citation_window(p, width=3200):
    """Expand a matched chunk into a wide, verbatim citation window.

    Locates the excerpt in the book's staged (extracted) text and slices a
    generous window around it, so long quotes/poems come back complete with
    their original line breaks — no re-indexing required.
    """
    fp = str(p.get("file_path") or "")
    m = re.search(r"\(ch(\d+)\)", fp)
    if not m:
        return str(p.get("content") or p.get("excerpt", ""))[:width]
    target = m.group(1)
    needle = str(p.get("excerpt") or p.get("content", ""))[:140]
    path = _staged_paths().get(_book_key(fp))
    if path is None:
        return str(p.get("content") or p.get("excerpt", ""))[:width]
    try:
        docs = _staged_texts(path) or []
        for d in docs:
            if str(d.get("suffix") or "") != target:
                continue
            text = str(d.get("text") or "")
            head = needle[:80].strip()
            idx = text.find(head)
            if idx < 0 and len(head) > 40:
                idx = text.find(head[:40])
            if idx < 0:
                return str(p.get("content") or p.get("excerpt", ""))[:width]
            start = max(0, idx - 140)
            return text[start : start + width]
    except Exception:
        pass
    return str(p.get("content") or p.get("excerpt", ""))[:width]


_PASSAGE_EXCERPT_CHARS = 1100
_PASSAGE_BLOCK_CHARS = 36000
_PASSAGE_BLOCK_FULL_CHARS = 52000
_WHOLE_BOOK_MAX_CHARS = 700000  # ≈ 175k tokens, leaving headroom in K3's 1M window


def _extract_quote_draft(question, passages=None, limit=6):
    """Deterministic verbatim spans for quote-hunting questions.

    Feeds exact library sentences (with their (Book · Chapter) label) so the
    model stitches a cited answer from real text instead of reconstructing a
    quote — the extractive half of "retrieval-heavy, generation-light".
    Quote answers become both faster (less generation) and safer (verbatim,
    located). Spans are SCOPED to the retrieved passages' books so this can
    never inject a span from outside the evidence (which could seed an
    out-of-evidence citation). Set MENTAT_NO_EXTRACT=1 to disable (A/B).
    """
    if os.getenv("MENTAT_NO_EXTRACT"):
        return ""
    scope = set()
    for p in passages or []:
        try:
            bk = _book_key(p.get("file_path", ""))
            if bk:
                scope.add(bk)
        except Exception:
            pass
    try:
        terms = [t for t in _derive_terms(question, cap=10) if len(t) >= 3][:6]
    except Exception:
        return ""
    if not terms:
        return ""
    try:
        rows = _span_search(terms, limit=max(limit * 4, 20))
    except Exception:
        return ""
    picks, seen = [], set()
    for r in rows:
        if scope:
            try:
                if _book_key(r.get("file_path", "")) not in scope:
                    continue
            except Exception:
                continue
        text = re.sub(r"\s+", " ", str(r.get("text") or "")).strip()
        key = text[:80].lower()
        if len(text) < 40 or key in seen:
            continue
        seen.add(key)
        label = _citation_for({"file_path": r.get("file_path", ""), "content": text})
        if not label:
            continue
        picks.append((text, label))
        if len(picks) >= limit:
            break
    if not picks:
        return ""
    lines = [
        "\n\nExact verbatim spans from the library (quote these directly, with "
        "the citations shown — do not paraphrase a quote or invent a location):"
    ]
    for text, label in picks:
        lines.append(f'- "{_escape_format(text)}" ({_escape_format(label)})')
    return "\n".join(lines)


def _render_passage_block(passages, full=False, max_chars=None):
    if not passages:
        return ""
    if max_chars is None:
        max_chars = _PASSAGE_BLOCK_FULL_CHARS if full else _PASSAGE_BLOCK_CHARS
    lines = []
    budget = max_chars
    omitted = 0
    for i, p in enumerate(passages, 1):
        raw_fp = str(p.get("file_path", ""))
        fp = _clean_name(raw_fp)
        marker = raw_fp.split(" · ", 1)[1] if " · " in raw_fp else ""
        tag = ""
        try:
            if marker and _boiler_section_of(marker):
                tag = " [front/back matter]"
        except Exception:
            tag = ""
        if full:
            width = 2400 if len(passages) > 6 else 5200
            text = _long_citation_window(p, width=width)[:width]
        elif p.get("named"):
            text = str(p.get("content") or p.get("excerpt", ""))[:2400]
        else:
            text = str(p.get("excerpt") or p.get("content", ""))[:_PASSAGE_EXCERPT_CHARS]
        text = _escape_format(text)
        # prefix each line with '>' so verse/poetry keeps its line breaks
        text = "\n".join(("> " + ln) if ln.strip() else ">" for ln in text.split("\n"))
        entry = f"[{i}] {fp}{tag}\n{text}"
        if len(entry) > budget and omitted == 0 and i == 1:
            # a single giant first passage still must not blow the window
            entry = entry[: max(1200, budget)]
        if len(entry) > budget:
            omitted += 1
            continue
        lines.append(entry)
        budget -= len(entry) + 2
        if budget < 1200 and i < len(passages):
            omitted += len(passages) - i
            break
    if omitted:
        lines.append(f"> … {omitted} further passage(s) omitted to respect the context budget.")
    return (
        "\n\nAdditional passages retrieved from your library — you may quote "
        "these verbatim and cite them by book · chapter:\n\n" + "\n\n".join(lines)
    )


_TITLE_STOPWORDS = {
    "study", "edition", "new", "revised", "translation", "commentary",
    "american", "book", "books", "guide", "volume", "vol", "introduction",
}


def _fts_own_hits(terms, own_ids, limit_ids=2000):
    """Count how many of a book's chunks match the terms in the FTS index.

    A direct membership check — immune to ranking, so a book whose title
    tokens are common still verifies as reachable.
    """
    db = _fts_db()
    q = " AND ".join('"' + str(t).replace('"', "") + '"' for t in terms if t)
    if not q or not own_ids:
        return 0
    sample = sorted(own_ids)[:limit_ids]
    ph = ",".join("?" * len(sample))
    try:
        row = db.execute(
            f"SELECT count(*) FROM chunks_fts WHERE chunks_fts MATCH ? AND chunk_id IN ({ph})",
            (q, *sample),
        ).fetchone()
        return row[0] if row else 0
    except Exception:
        return 0


async def _canary_check(rag, rel, k=4):
    """Verify one book is retrievable. Returns [(check_name, ok, detail), ...]."""
    import collections

    checks = []
    chunks = _load_chunk_texts()
    rel_clean = _clean_name(rel)
    fname = rel_clean.split("/")[-1]
    folder = rel.split("/")[-2] if "/" in rel else ""

    def _norm(s):
        return re.sub(r"\s+", "", s).lower()

    def _book_of(c):
        book_part = str(c["file_path"]).split(" · ")[0]
        book_part = book_part.rsplit(" › ", 1)[-1].rsplit("/", 1)[-1]
        return _norm(book_part)

    own = [c for c in chunks if _book_of(c) == _norm(fname)]
    checks.append(("identity", len(own) > 0, f"{len(own)} chunks"))
    if not own:
        return checks
    own_ids = {c["chunk_id"] for c in own}

    def own_hit(ps):
        return sum(1 for p in ps if p.get("chunk_id") in own_ids)

    ps = await _librarian_search(rag, fname, k=k)
    if own_hit(ps) == 0 and folder:
        ps = ps + await _librarian_search(rag, folder, k=k)

    # index-level reachability: the filename's own tokens find own chunks
    tokens = [
        w.lower() for w in re.findall(r"[A-Za-z']{3,}", fname)
        if w.lower() not in _SEARCH_STOPWORDS
    ][:2]
    index_hits = 0
    if len(tokens) >= 2:
        index_hits = _fts_own_hits(tokens, own_ids)
        checks.append(("index reachable", index_hits >= 1, f"{index_hits} own match"))
    # A duplicate book (e.g. the Dune PDF shadowed by the epub) may not rank,
    # but if its own chunks are findable in the index that is still healthy.
    checks.append(
        ("title findable", own_hit(ps) >= 1 or index_hits >= 1, f"{own_hit(ps)}/{len(ps)} own")
    )

    blob = " ".join(c["content"] for c in own).lower()
    words = [w for w in re.findall(r"[a-z]{6,}", blob) if w not in _SEARCH_STOPWORDS]
    counts = collections.Counter(words)
    candidates = [w for w, n in counts.items() if 2 <= n <= 30]
    if candidates:
        token = next(
            (w for w in fname.split() if len(w) >= 3 and w.lower() not in _SEARCH_STOPWORDS),
            "",
        ).lower()
        sample = candidates[:2]
        found = 0
        for w in sample:
            terms = [w, token] if token else [w]
            if _fts_own_hits(terms, own_ids) >= 1:
                found += 1
        checks.append(("sample words findable", found == len(sample), f"{found}/{len(sample)}"))
    return checks


def _rewrite_references(answer, passages):
    """Replace the model's References section with the sources it CITED.

    Listing every retrieved passage's book produced reference bloat (11 books
    for an answer that only quoted Dune). A book is kept when one of its
    distinctive title tokens appears in the answer body; if nothing matches
    (rare — no citation at all), the full context list is kept so the reader
    still sees what the answer was grounded in.
    """
    if not passages or not (answer and str(answer).strip()):
        return answer
    body = re.sub(r"\n#{2,4}\s*References\s*\n.*$", "", str(answer), flags=re.S)
    body_low = body.lower()
    seen, seen_all = [], []
    for p in passages:
        fp = _clean_name(str(p.get("file_path", "")))
        book = fp.split(" · ")[0] if " · " in fp else fp
        book = book.rsplit(" › ", 1)[-1].strip()
        if not book or book in seen_all:
            continue
        seen_all.append(book)
        for tok in re.findall(r"[A-Za-z][A-Za-z'’-]{3,}", book):
            low = tok.lower()
            if low in _SEARCH_STOPWORDS or low in _TITLE_STOPWORDS:
                continue
            if low in body_low:
                seen.append(book)
                break
    if not seen:
        seen = seen_all
    if not seen:
        return answer
    lines = [f"- [{i}] {b}" for i, b in enumerate(seen, 1)]
    section = "\n\n### References\n\n" + "\n".join(lines)
    return body + section


def _prioritize_named(question, results, extra_names=None):
    """Split results into named-book passages (lead) and the rest.

    Proper nouns in the question that name a book/author lead the block,
    capped PER named book (so 'Stalin vs Kojève' leads with BOTH books, not
    whichever one had the most matches), and within a book passages matching
    the topic terms rank first so front-matter can't crowd out the content.
    ``extra_names`` are model-resolved book names from query expansion.
    """
    proper = [
        w.lower()
        for w in re.findall(r"[A-Z][A-Za-z'-]{2,}", _normalize_query(question))
        if w.lower() not in _SEARCH_STOPWORDS and w.lower() not in _TITLE_STOPWORDS
    ]
    all_norms = [
        re.sub(r"\s+", "", e["raw"]).lower() for e in _book_map().values()
    ]
    for name in _named_books(question):
        for w in re.findall(r"[a-zA-Z]{3,}", _normalize_query(str(name))):
            low = w.lower()
            if (
                low in _SEARCH_STOPWORDS
                or low in _TITLE_STOPWORDS
                or low in proper
            ):
                continue
            if sum(1 for n in all_norms if low in n) <= 3:
                proper.append(low)
    if extra_names:
        for name in extra_names:
            for w in re.findall(r"[a-zA-Z]{3,}", _normalize_query(str(name))):
                low = w.lower()
                if (
                    low not in _SEARCH_STOPWORDS
                    and low not in _TITLE_STOPWORDS
                    and low not in proper
                ):
                    proper.append(low)
    content = [t for t in _derive_terms(question) if t not in proper]
    q_sections = _query_sections(question)

    def _sortkey(p):
        hay = (str(p.get("excerpt") or "") + " " + str(p.get("file_path", ""))).lower()
        return (
            _is_boilerplate(
                str(p.get("content") or p.get("excerpt", "")),
                q_sections,
                file_path=p.get("file_path", ""),
            ),
            -sum(1 for t in content if t in hay),
        )

    prio_by_id = {}
    for p in results:
        fp_low = str(p.get("file_path", "")).lower()
        for t in proper:
            if t in fp_low:
                prio_by_id[p.get("chunk_id")] = p
                break

    named_terms = [
        t for t in proper
        if any(t in str(p.get("file_path", "")).lower() for p in results)
    ]
    per_book_cap = 10 if len(named_terms) <= 1 else 5

    ordered_prio = []
    used = set()
    for t in proper:
        group = sorted(
            [
                p for p in prio_by_id.values()
                if p.get("chunk_id") not in used
                and t in str(p.get("file_path", "")).lower()
            ],
            key=_sortkey,
        )[:per_book_cap]
        for p in group:
            ordered_prio.append(p)
            used.add(p.get("chunk_id"))

    ordered_prio = _diversify(ordered_prio, cap=4)
    prio_ids = set()
    for p in ordered_prio:
        prio_ids.add(p.get("chunk_id"))
    # The rest keeps the UNselected named passages too (they are still the
    # named book's own text — the reranker decides among them, so a
    # single-book question ends up dominated by that book, not the filler).
    rest = [p for p in results if p.get("chunk_id") not in prio_ids]
    for p in ordered_prio:
        p["named"] = True
    return ordered_prio, rest


async def _probe_passages(rag, question, k=8):
    """Context preview for `brain probe` — no LLM calls at all.

    Runs the librarian search (semantic + keyword) and the named-book
    priority + local rerank, so it shows exactly what the answer would be
    grounded in, deterministically and free.
    """
    results = []
    seen = set()

    def _add(items):
        for p in items or []:
            cid = p.get("chunk_id")
            if cid and cid in seen:
                continue
            if cid:
                seen.add(cid)
            results.append(p)

    if _has_hunt_intent(question):
        try:
            _add(
                _hunt_passages(
                    question,
                    limit=min(
                        24, int(_load_settings().get("hunt_limit", 36) or 36)
                    ),
                )
            )
        except Exception:
            pass
    _add(await _librarian_search(rag, question, k=k))
    # one extra deterministic search: content terms + named books, which
    # mirrors what the expansion tier adds (e.g. "mercy dune").
    terms = _derive_terms(question)
    named = _named_sources(question)
    content = [t for t in terms if t not in named]
    if content and named:
        try:
            _add(await _librarian_search(rag, " ".join(content[:4] + named), k=k))
        except Exception:
            pass
    # Scope sweep: every demanded work gets its own scoped search (no LLM),
    # mirroring the answer path so `probe` shows exactly what an answer would
    # be grounded in.
    scope = []
    group_pool = {}
    try:
        sweep_all = _has_library_wide_intent(question)
        scope = _resolve_scope(question, "expand", sweep_all=sweep_all)
        group_pool = {it["id"]: [] for it in scope}
    except Exception:
        scope = []
    sweep_depth = int(_load_settings().get("sweep_depth", 6) or 6)
    for it in scope:
        if not it.get("hits") and not it.get("demand"):
            continue
        kk = max(4, min(sweep_depth, k))
        try:
            sp = await _librarian_search(rag, question, k=kk, book_filter=it["primary"])
        except Exception:
            sp = []
        if not sp:
            try:
                sp = _fts_scope_passages(question, it["primary"], limit=kk * 2)
            except Exception:
                sp = []
        group_pool[it["id"]] = sp
        _add(sp)
    if not scope and _has_quote_intent(question):
        import collections as _collections

        dist = _collections.Counter()
        for p in results:
            dist[_book_key(p.get("file_path"))] += 1
        keys = [bk for bk, _ in dist.most_common(4)]
        async def _shelf(bk):
            try:
                return await _librarian_search(rag, question, k=4, book_filter=bk)
            except Exception:
                return []
        for shelf_results in await asyncio.gather(*[_shelf(bk) for bk in keys]):
            _add(shelf_results)
    prio, rest = _prioritize_named(question, results)
    if len(rest) > 8:
        try:
            rest = _diversify(await _rerank_passages(question, rest, top_n=12), cap=4)[:8]
        except Exception:
            rest = _diversify(rest, cap=4)[:8]
    final = _diversify(prio[:8] + rest, cap=4)
    if scope:
        final = _ensure_scope_coverage(final, scope, group_pool)
    else:
        final = _ensure_named_coverage(final, question, results)
    return final


def _ensure_named_coverage(final, question, results, cap_total=14):
    """Guarantee at least one passage from every book the question names."""
    named_keys = []
    for name in list(_named_books(question))[:6]:
        for bk in _books_matching(name)[:1]:
            if bk not in named_keys:
                named_keys.append(bk)
    if not named_keys:
        return final
    present = {_book_key(p.get("file_path")) for p in final}
    additions = []
    for bk in named_keys:
        if bk in present:
            continue
        for p in results or []:
            if _book_key(p.get("file_path")) == bk and p not in final and p not in additions:
                additions.append(p)
                present.add(bk)
                break
    return (additions + final)[:cap_total]


def _rrf_fuse(ranked_lists, k=60):
    """Reciprocal Rank Fusion over several ranked retrieval lists.

    score(chunk) = Σ_over_lists 1/(k + rank). Chunks that rank well across
    MULTIPLE query variants rise above chunks that top only one — this is the
    breadth fix (multi-query results were previously just concatenated in query
    order). Set MENTAT_NO_RRF=1 to fall back to concatenation (A/B testing).
    """
    if os.getenv("MENTAT_NO_RRF"):
        flat = []
        for lst in ranked_lists:
            flat.extend(lst or [])
        return flat
    scores, first = {}, {}
    for lst in ranked_lists:
        for rank, p in enumerate(lst or []):
            cid = p.get("chunk_id") or id(p)
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
            first.setdefault(cid, p)
    return [first[c] for c in sorted(scores, key=lambda c: -scores[c])]


async def _build_passages(rag, question, strategy):
    """Gather relevant passages across the whole index (Tier 1 + Tier 2)."""
    _RETRIEVAL_ERRORS.clear()
    results = []
    seen_ids = set()

    def _add(items):
        for p in items or []:
            cid = p.get("chunk_id")
            if cid and cid in seen_ids:
                continue
            if cid:
                seen_ids.add(cid)
            results.append(p)

    hyde = ""
    expansion = {}
    try:
        hypo, exp = await asyncio.gather(
            _hypothetical_passage(question),
            _expand_query(question),
            return_exceptions=True,
        )
        if isinstance(hypo, str):
            hyde = hypo
        if isinstance(exp, dict):
            expansion = exp
    except Exception:
        pass

    queries = [question]
    model_books = []
    if expansion:
        queries += [a for a in expansion.get("angles", []) if a]
        model_books = [b for b in expansion.get("books", []) if b]
    queries = queries[:6]
    _retrieval_note("embedding your question…")
    # Batch embeddings: one Ollama call for the HyDE doc, one for all queries.
    embeds = {}
    try:
        embeds["hyde"] = await nomic_embed([hyde or question], context="document")
        qs = [q for q in queries[1:] if q]
        if qs:
            qemb = await nomic_embed(qs, context="query")
            for q, e in zip(qs, qemb):
                embeds[q] = np.expand_dims(e, 0)
    except Exception as exc:
        _retrieval_degrade(f"embedding: {exc}")
    _lists = []
    for q in queries:
        try:
            _lists.append(await _librarian_search(
                rag, q, k=5,
                embedding=embeds.get("hyde") if q == question else embeds.get(q),
            ))
        except Exception as exc:
            _retrieval_degrade(f"search: {exc}")
    _add(_rrf_fuse(_lists))

    if strategy == "hunt":
        try:
            _add(
                _hunt_passages(
                    question,
                    limit=int(_load_settings().get("hunt_limit", 36) or 36),
                )
            )
        except Exception as exc:
            _retrieval_degrade(f"hunt: {exc}")

    if strategy == "agent":
        issued = {q.lower().strip() for q in queries}
        scratch = []
        rounds = 0
        # Universal (cross-book synthesis) questions get a deeper, wider hunt.
        try:
            configured = int(_load_settings().get("agent_rounds", 0) or 0)
        except Exception:
            configured = 0
        agent_rounds = configured or (6 if strategy == "universal" else 4)
        result_cap = configured or (32 if strategy == "universal" else 24)
        while rounds < agent_rounds and len(results) < result_cap:
            rounds += 1
            plan = await _planner(question, results[-8:], rounds, scratch=scratch)
            if plan.get("note"):
                scratch.append(
                    {
                        "round": rounds,
                        "queries": [],
                        "new": 0,
                        "books": [],
                        "note": plan["note"],
                    }
                )
            if plan.get("done"):
                break
            searches = [
                s for s in plan.get("searches", [])[:3]
                if s and s.lower().strip() not in issued
            ]
            if not searches:
                break
            for s in searches:
                issued.add(s.lower().strip())
            before = len(results)
            semb = None
            try:
                semb = await nomic_embed(searches, context="query")
            except Exception as exc:
                _retrieval_degrade(f"agent embedding: {exc}")
            for i, sq in enumerate(searches):
                try:
                    _add(await _librarian_search(
                        rag, sq, k=5,
                        embedding=(np.expand_dims(semb[i], 0) if semb is not None else None),
                    ))
                except Exception as exc:
                    _retrieval_degrade(f"agent search: {exc}")
            new_books = []
            for p in results[before:]:
                key = _book_key(p.get("file_path", ""))
                if key and key not in new_books:
                    new_books.append(key)
            scratch.append(
                {
                    "round": rounds,
                    "queries": searches,
                    "new": len(results) - before,
                    "books": new_books[:4],
                }
            )

    # Scope shelf tier: every work the question demands gets its OWN scoped
    # sweep — named works first, then every work whose text actually contains
    # the question's terms (FTS-verified), then (for library-wide questions)
    # the rest. Multi-book questions can never be swallowed by one book's
    # vocabulary, and no relevant book can be missed by ranking alone.
    scope = []
    group_pool = {}
    try:
        named_any = bool(model_books) or bool(_named_books(question))
        # A question that names its works sweeps THOSE works (plus anything
        # content-verified); only unnamed universal questions sweep the whole
        # library, so irrelevant books can never crowd a Dune question.
        sweep_all = (
            (strategy == "universal" and not named_any)
            or _has_library_wide_intent(question)
        )
        scope = _resolve_scope(question, strategy, model_books=model_books, sweep_all=sweep_all)
        group_pool = {it["id"]: [] for it in scope}
    except Exception:
        scope = []
    sweep_depth = int(_load_settings().get("sweep_depth", 6) or 6)
    for it in scope:
        if not it.get("hits") and not it.get("demand"):
            continue
        kk = max(4, sweep_depth)
        if len(scope) <= 1:
            kk = max(kk, 8)  # a single demanded work gets a deep sweep
        try:
            sp = await _librarian_search(
                rag, question, k=kk,
                embedding=embeds.get("hyde"),
                book_filter=it["primary"],
            )
        except Exception:
            sp = []
        if not sp and it.get("hits"):
            try:
                sp = _fts_scope_passages(question, it["primary"], limit=kk * 2)
            except Exception:
                sp = []
        group_pool[it["id"]] = sp
        _add(sp)
    if not scope:
        # fall back to the named-book scoped searches (old behaviour)
        shelf_keys = []
        for name in list(model_books or [])[:6] + list(_named_books(question) or [])[:6]:
            for bk in _books_matching(name)[:1]:
                if bk not in shelf_keys:
                    shelf_keys.append(bk)
        if _has_quote_intent(question) and not shelf_keys:
            import collections as _collections

            dist = _collections.Counter()
            for p in results:
                dist[_book_key(p.get("file_path"))] += 1
            for bk, _ in dist.most_common(3):
                if bk not in shelf_keys:
                    shelf_keys.append(bk)

        async def _shelf(bk):
            try:
                return await _librarian_search(
                    rag, question, k=4,
                    embedding=embeds.get("hyde"),
                    book_filter=bk,
                )
            except Exception:
                return []

        for shelf_results in await asyncio.gather(*[_shelf(bk) for bk in shelf_keys]):
            _add(shelf_results)

    # Named-work priority: proper nouns in the question (authors, books) must
    # lead the final block — the semantic noise can't bury the named source.
    n_scope = len(scope)
    universal = strategy == "universal"
    hunt = strategy == "hunt"
    prio, rest = _prioritize_named(question, results, extra_names=model_books)
    if len(rest) > 8:
        _retrieval_note("reranking passages…")
        try:
            top_n = (
                48 if hunt
                else min(24 if not universal else 30, 12 + 3 * max(n_scope, 1))
            )
            cap = 6 if (hunt or n_scope <= 1 or universal) else 4
            rest = _diversify(
                await _rerank_passages(question, rest, top_n=top_n), cap=cap
            )
            if not hunt:
                rest = rest[: min(14, 8 + 2 * max(n_scope, 1))]
        except Exception:
            rest = _diversify(rest, cap=4)[:8]
    final = _diversify(
        prio[: (14 if n_scope <= 1 else 8)] + rest,
        cap=(8 if n_scope <= 1 else (6 if universal or hunt else 4)),
    )
    if hunt:
        final = final[:36]
    if scope:
        final = _ensure_scope_coverage(
            final, scope, group_pool,
            cap_total=(36 if hunt else (32 if universal else 26)),
        )
    else:
        final = _ensure_named_coverage(final, question, results)
    global _LAST_RETRIEVAL
    try:
        _LAST_RETRIEVAL = [
            {
                "rank": i,
                "chunk_id": p.get("chunk_id"),
                "file_path": p.get("file_path"),
                "named": i < min(8, len(prio)),
            }
            for i, p in enumerate(final)
        ]
    except Exception:
        _LAST_RETRIEVAL = []
    return final


# ---------------------------------------------------------------------------
# Library profiles — per-work statistics for "what did I put in my index".
# Deterministic, computed from the chunk store + staged chapter texts, cached
# to disk and rebuilt automatically when the store changes. Powers
# ``brain inventory``, the TUI /inventory panel, and the MCP library_stats
# tool — and keeps word-frequency queries instant at any library size.
# ---------------------------------------------------------------------------

PROFILES_PATH = STORAGE_DIR / "profiles.json"


def _library_digest():
    """Cheap fingerprint of the chunk store (count + book edges + mtime)."""
    try:
        bm = _book_map()
        keys = sorted(bm.keys())
        mtime = LIBRARY_DB_PATH.stat().st_mtime if LIBRARY_DB_PATH.exists() else 0
        return "%d|%s|%s|%d|%d" % (
            len(bm), keys[0] if keys else "", keys[-1] if keys else "",
            mtime, sum(len(v.get("ids") or ()) for v in bm.values()),
        )
    except Exception:
        return ""


def _library_profiles(refresh=False):
    """Per-work inventory: {work, copies, chunks, chapters, apparatus,
    chars, words}[] sorted by size, plus library totals. Cached under
    profiles.json; rebuild when the store digest changes or ``refresh``."""
    digest = _library_digest()
    if not refresh:
        try:
            cached = json.loads(PROFILES_PATH.read_text())
            if cached.get("digest") == digest and cached.get("works"):
                return cached
        except Exception:
            pass
    try:
        bm = _book_map()
        works = _collapse_works(list(bm.keys()))
        manifest = _load_manifest()
        rows = []
        totals = {"chunks": 0, "chapters": 0, "apparatus": 0, "chars": 0, "words": 0}
        for it in works:
            n_chunks = 0
            chars = 0
            words = 0
            for k in it["keys"]:
                entry = bm.get(k)
                if not entry:
                    continue
                n_chunks += len(entry.get("ids") or ())
                for c in entry.get("chunks") or []:
                    content = str(c.get("content") or "")
                    chars += len(content)
                    words += len(content.split())
            chapters = 0
            apparatus = 0
            seen_docs = set()
            for rel, info in manifest.items():
                if _title_canon(rel) != it["id"]:
                    continue
                path = KNOWLEDGE_ROOT / rel
                try:
                    docs = _staged_texts(path)
                    if docs is None:
                        docs = _stage_file(path)
                except Exception:
                    docs = None
                for d in docs or []:
                    marker = (d.get("marker") or "").strip() or "(whole book)"
                    dup_key = (
                        _norm_label(marker),
                        re.sub(r"\s+", " ", str(d.get("text") or "")[:500].lower())[:300],
                    )
                    if dup_key in seen_docs:
                        continue
                    seen_docs.add(dup_key)
                    if _boiler_section_of(marker):
                        apparatus += 1
                    else:
                        chapters += 1
            rows.append(
                {
                    "work": it["title"],
                    "copies": len(it["keys"]),
                    "chunks": n_chunks,
                    "chapters": chapters,
                    "apparatus": apparatus,
                    "chars": chars,
                    "words": words,
                }
            )
            totals["chunks"] += n_chunks
            totals["chapters"] += chapters
            totals["apparatus"] += apparatus
            totals["chars"] += chars
            totals["words"] += words
        rows.sort(key=lambda r: -r["words"])
        out = {"digest": digest, "works": rows, "totals": totals}
        try:
            PROFILES_PATH.write_text(json.dumps(out, indent=1))
        except Exception:
            pass
        return out
    except Exception:
        return {"digest": digest, "works": [], "totals": {}}


def _term_frequency(term):
    """Exact whole-word occurrences of ``term`` per work (story vs front/back
    matter), counted against the staged chapter texts. Deterministic and fast
    enough to call interactively; used by ``brain freq`` and MCP
    term_frequency."""
    term = (term or "").strip().strip('"“”‘’')
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", term)
    if not words or len(words) > 4:
        return []
    if len(words) == 1:
        pat = re.compile(
            r"(?<![A-Za-z'])" + re.escape(words[0]) + r"(?![A-Za-z'])", re.I
        )
    else:
        pat = _census_pattern(words)
    try:
        works = _collapse_works(list(_book_map().keys()))
        manifest = _load_manifest()
    except Exception:
        return []
    out = []
    for it in works:
        story = apparatus = 0
        seen = set()
        for rel, info in manifest.items():
            if _title_canon(rel) != it["id"]:
                continue
            path = KNOWLEDGE_ROOT / rel
            try:
                docs = _staged_texts(path)
                if docs is None:
                    docs = _stage_file(path)
            except Exception:
                docs = None
            for d in docs or []:
                marker = (d.get("marker") or "").strip() or "(whole book)"
                dup_key = (
                    _norm_label(marker),
                    re.sub(r"\s+", " ", str(d.get("text") or "")[:500].lower())[:300],
                )
                if dup_key in seen:
                    continue
                seen.add(dup_key)
                n = len(pat.findall(str(d.get("text") or "")))
                if n:
                    if _boiler_section_of(marker):
                        apparatus += n
                    else:
                        story += n
        out.append({"work": it["title"], "story": story, "apparatus": apparatus})
    return out


# ---------------------------------------------------------------------------
# Library map — per-book summaries + central concepts + cross-book index.
# Built once per book (incremental) with the fast model; powers the "universal"
# (cross-book synthesis / themes / comparison) answer mode.
# ---------------------------------------------------------------------------

LIBRARY_MAP_PATH = STORAGE_DIR / "library_map.json"

UNIVERSAL_INSTRUCTION = (
    "The user is asking a cross-book question — answer it the way a strong "
    "interdisciplinary reader would: build ONE argument, not a book report. "
    "1) Form a thesis that holds across the books, then marshal evidence: for "
    "each relevant book state its contribution briefly, then compare, contrast, "
    "and show where books agree, diverge, or complete one another. "
    "2) Ground every substantive claim in the provided passages and cite by "
    "book · chapter; quote verbatim when quoting. "
    "3) A claim about a book is only 'silent' if no passage from it was "
    "provided and no census covered it. "
    "4) Mark your own inferences as your reading (⟪ ⟫ for invented content, "
    "'my reading:' for interpretations). "
    "5) End with the implication of the synthesis — what the books together "
    "argue that none of them argues alone."
)


def _load_library_map():
    try:
        return json.loads(LIBRARY_MAP_PATH.read_text())
    except Exception:
        return {"books": {}}


def _save_library_map(mp):
    try:
        LIBRARY_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
        LIBRARY_MAP_PATH.write_text(json.dumps(mp, ensure_ascii=False, indent=1))
    except Exception:
        pass


async def _map_one_book(rel, text):
    """One fast call: 1-2 sentence summary + central concepts for a book."""
    prompt = (
        "Here is text from a book. Summarize the book in 1-2 sentences and list "
        "6-8 of its central concepts or themes, one short phrase each. Return "
        "ONLY JSON: {\"summary\": \"...\", \"concepts\": [\"...\", ...]}\n\n"
        f"Book: {rel}\n\nText:\n{text[:12000]}"
    )
    try:
        out = await _fast_llm(prompt)
        m = re.search(r"\{.*\}", out or "", re.S)
        data = json.loads(m.group(0)) if m else {}
        return {
            "summary": str(data.get("summary", "")).strip(),
            "concepts": [str(c).strip() for c in data.get("concepts", []) if str(c).strip()][:8],
        }
    except Exception:
        return {"summary": "", "concepts": []}


def _concept_excerpts(concepts, per=2):
    """A representative passage excerpt per concept (via the FTS index)."""
    out = []
    try:
        chunks = _load_chunk_texts()
        by_id = {c["chunk_id"]: c for c in chunks}
        _fts_sync()
        for concept in concepts:
            got = 0
            for cid in _fts_search([concept], limit=4):
                c = by_id.get(cid)
                if not c:
                    continue
                low = c["content"].lower()
                i = low.find(concept.lower())
                if i < 0:
                    i = 0
                s = max(0, i - 50)
                ex = c["content"][s:s + 300].replace("\n", " ")
                out.append({"concept": concept, "file_path": c["file_path"], "excerpt": ex})
                got += 1
                if got >= per:
                    break
    except Exception:
        pass
    return out


async def _build_library_map(force=False):
    """Incremental map build: only books whose file changed get re-summarized."""
    mp = _load_library_map()
    books = mp.get("books", {})
    manifest = _load_manifest()
    changed = False
    for rel, entry in manifest.items():
        digest = str(entry.get("hash", ""))[:16]
        if not force and books.get(rel, {}).get("digest") == digest:
            continue
        path = KNOWLEDGE_ROOT / rel
        docs = _staged_texts(path)
        if docs is None:
            try:
                docs = _stage_file(path)
            except Exception:
                docs = []
        if not docs:
            continue
        text = " ".join(d["text"] for d in docs)
        info = await _map_one_book(rel, text)
        books[rel] = {
            "digest": digest,
            "title": _clean_name(rel).replace("/", " › "),
            "summary": info.get("summary", ""),
            "concepts": info.get("concepts", []),
            "concept_excerpts": _concept_excerpts(info.get("concepts", [])),
        }
        changed = True
    if changed or force:
        mp["books"] = books
        _save_library_map(mp)
    return mp


def _has_universal_intent(question):
    q = question.lower()
    return any(
        w in q
        for w in (
            "across", "compare", "contrast", "themes", "theme", "relationship between",
            "relate", "synthesis", "synthesize", "throughout the library",
            "in the library", "between these books", "in common", "dialogue",
            "across the books", "whole library", "throughout your books",
            "triangulate", "juxtapose", "parallel", "common ground", "all three",
            "these thinkers", "resonat", "echo",
        )
    )


_INTERPRET_WORDS = (
    "interpret", "connect", "relate", "synthesize", "juxtapose", "compare",
    "what would", "implications", "novel", "reading of", "resonat",
    "triangulate", "parallel", "meaning of", "in common", "all three",
)


def _is_interpretive(question, score=None):
    """Deep/connection questions get the philosophical close-reader prompt."""
    q = (question or "").lower()
    if any(w in q for w in _INTERPRET_WORDS):
        return True
    if _has_universal_intent(question):
        return True
    if score is None:
        score = _question_heuristic_score(question)
    return score >= 0.30


def _select_books(question, mp, limit=5):
    terms = _derive_terms(question)
    books = mp.get("books", {})
    picked = []
    # 1) each named term gets the book whose title matches it (one per term)
    for t in terms:
        if len(picked) >= limit:
            break
        for rel, info in books.items():
            if rel in picked:
                continue
            if t in (info.get("title", rel) or "").lower():
                picked.append(rel)
                break
    # 2) fill remaining slots by concept/summary relevance
    scored = []
    for rel, info in books.items():
        if rel in picked:
            continue
        hay = (
            info.get("title", "") + " " + info.get("summary", "")
            + " " + " ".join(info.get("concepts", []))
        ).lower()
        hits = sum(1 for t in terms if t in hay)
        if hits:
            scored.append((hits, rel))
    scored.sort(key=lambda x: -x[0])
    for _, rel in scored:
        if len(picked) >= limit:
            break
        picked.append(rel)
    return picked


def _render_map_block(question, mp):
    rels = _select_books(question, mp)
    if not rels:
        return ""
    lines = []
    for rel in rels:
        info = mp.get("books", {}).get(rel, {})
        title = _escape_format(info.get("title", rel))
        summary = _escape_format((info.get("summary") or "")[:400])
        concepts = ", ".join(_escape_format(c) for c in info.get("concepts", [])[:8])
        lines.append(f"- {title}: {summary}" + (f"\n    concepts: {concepts}" if concepts else ""))
        for ex in info.get("concept_excerpts", [])[:2]:
            lines.append(f"    · {_escape_format(ex['concept'])}: {_escape_format(ex['excerpt'][:200])}")
    return (
        "\n\nLibrary overview for a cross-book question:\n"
        + "\n".join(lines)
        + "\n\n" + UNIVERSAL_INSTRUCTION
    )


# ---------------------------------------------------------------------------
# Cross-encoder reranker (local, offline) — precision fix + prompt compression.
# ---------------------------------------------------------------------------

_RERANKER = None


def _get_reranker():
    global _RERANKER
    if _RERANKER is None:
        from sentence_transformers import CrossEncoder

        _RERANKER = CrossEncoder("BAAI/bge-reranker-base")
    return _RERANKER


async def _rerank_model(query, documents, top_n=8, **kwargs):
    """Signature LightRAG expects -> [{'index': i, 'relevance_score': s}]."""
    try:
        model = _get_reranker()
        pairs = [[query, str(d)[:800]] for d in documents]
        scores = await asyncio.to_thread(model.predict, pairs)
        order = sorted(range(len(scores)), key=lambda i: -float(scores[i]))
        return [{"index": i, "relevance_score": float(scores[i])} for i in order[:top_n]]
    except Exception:
        return [{"index": i, "relevance_score": 1.0} for i in range(min(top_n, len(documents)))]


async def _rerank_passages(question, passages, top_n=8):
    if not passages:
        return passages
    try:
        model = _get_reranker()
        pairs = [
            [question, str(p.get("excerpt") or p.get("content", ""))[:800]]
            for p in passages
        ]
        scores = await asyncio.to_thread(model.predict, pairs)
        order = sorted(range(len(scores)), key=lambda i: -float(scores[i]))
        return [passages[i] for i in order[:top_n]]
    except Exception:
        return passages[:top_n]


async def _hypothetical_passage(question):
    """HyDE: a hypothetical excerpt that would answer the question."""
    if _offline():
        return ""  # local retrieval embeds the question directly
    prompt = (
        "Write a 2-3 sentence hypothetical passage from a book that would "
        "answer this question. Read like an actual excerpt.\nQuestion: " + question
    )
    try:
        return (await _fast_llm(prompt) or "").strip()
    except Exception:
        return ""


async def _revise_for_argument(answer, question):
    """One critique-and-revise pass for deep-route answers (online only).

    A fast editor finds genuine problems (numbers vs census, suspect quotes,
    ungrounded claims, books wrongly called silent, missed cross-book links);
    if it finds any, the draft is revised once by the chat model. Cheap, one
    extra pass — this is the "think twice before you speak" step.
    """
    a = str(answer or "").strip()
    if _offline() or len(a) < 400 or not DEEPSEEK_API_KEY:
        return answer
    try:
        critique = await deepseek_llm(
            "You are a demanding editor over an AI librarian's answer that must "
            "be grounded in given book passages. List ONLY genuine problems: "
            "numbers that could contradict a census, quotes that look "
            "reworded, claims not supported by the passages, books declared "
            "silent without evidence, or missed connections between books. "
            "If the draft is sound reply exactly: OK\n\n"
            f"QUESTION: {str(question)[:500]}\n\nDRAFT:\n{a[:9000]}",
            model=DEEPSEEK_FLASH_MODEL,
            max_tokens=700,
        )
    except Exception:
        return answer
    c = (critique or "").strip()
    if not c or c.upper().startswith("OK") or len(c) < 40:
        return answer
    try:
        revised = await deepseek_llm(
            "Revise the draft below to fix every criticism the editor raised. "
            "Keep quotes verbatim and numbers matching the census exactly; "
            "remove nothing that was correct. Return ONLY the revised answer.\n\n"
            f"EDITOR:\n{c[:1800]}\n\nDRAFT:\n{a[:12000]}",
            model=DEEPSEEK_FLASH_MODEL,
            max_tokens=12000,
        )
    except Exception:
        return answer
    return str(revised or "").strip() or answer


_PAGE_MARK_RE = re.compile(r"##\s*Page\s+(\d+)")
_VERSE_REF_RE = re.compile(r"\b(\d{1,3}:\d{1,3})\b")

_PDF_DISPLAY = (
    ("study quran", "The Study Quran"),
    ("kojeve", "Kojeve, Introduction to the Reading of Hegel"),
    ("super imperialism", "Super Imperialism"),
    ("muqaddimah", "The Muqaddimah"),
    ("dialectical and historical", "Stalin, Dialectical and Historical Materialism"),
    ("aptheker", "Aptheker, The American Revolution"),
)


def _display_book(book):
    """Readable citation name: known short titles, else parentheticals gone."""
    low = str(book or "").lower()
    for key, nice in _PDF_DISPLAY:
        if key in low:
            return nice
    cleaned = re.sub(r"\([^)]*\)", " ", str(book))
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -–—,.")
    return cleaned or book


def _citation_for(passage):
    """(Book · Chapter/verse/page) label from a passage, or ''.

    PDFs carry "## Page N" markers inside the staged text, so page anchors
    are derived from the passage content itself (no re-index needed). The
    Study Quran additionally gets a surah:verse anchor when the chunk shows
    one — giving (The Study Quran · 2:255 · p. 42).
    """
    fp = str((passage or {}).get("file_path") or "")
    if not fp:
        return ""
    rel = fp.replace("\\", "/").rsplit("/", 1)[-1].split(" › ")[-1].strip()
    book_part, _, marker = rel.partition(" · ")
    is_pdf = bool(re.search(r"\.pdf\s*$", book_part, re.I))
    book = re.sub(r"\.(?:epub|pdf|txt|mobi|azw3|docx?)\s*$", "", book_part, flags=re.I)
    book = re.sub(r"\s*\([^)]*\)\s*$", "", book).strip()
    marker = re.sub(r"\s*\(ch\d+\)\s*$", "", marker).strip()
    if not book:
        return ""
    if is_pdf:
        book = _display_book(book)
        content = str(
            (passage or {}).get("content") or (passage or {}).get("excerpt") or ""
        )
        anchors = []
        if "study quran" in book.lower():
            vm = _VERSE_REF_RE.search(content)
            if vm:
                anchors.append(vm.group(1))
        pm = _PAGE_MARK_RE.search(content)
        if pm:
            anchors.append(f"p. {pm.group(1)}")
        if anchors:
            return " · ".join([book] + anchors)
    return f"{book} · {marker}" if marker else book


_QUOTE_RE = re.compile(
    r"(?<![A-Za-z0-9])"          # a real quote opens on a non-word boundary…
    r"[\"“]([^\"“”\n]{25,400})[\"”]"
    r"(?![A-Za-z0-9])"           # …and closes on one too
)
_CITED_AFTER_RE = re.compile(r"^\s*(?:\([^)]{2,90}\)|\[[^\]]{1,20}\])")


def _ensure_quote_attribution(answer, passages):
    """Insert (Book · Chapter) after quotes the evidence can locate.

    Runs after synthesis: every quoted span longer than a phrase is checked
    against the retrieved passages; if it already carries a parenthetical or
    bracketed citation it is left alone, otherwise the matching passage's
    citation is appended. Returns (answer, inserted_count).
    """
    answer = str(answer or "")
    if not answer or not passages:
        return answer, 0
    index = []
    for p in passages:
        text = re.sub(
            r"\s+", " ", str(p.get("content") or p.get("excerpt") or "")
        ).strip()
        label = _citation_for(p)
        if text and label:
            index.append((text.lower(), label))
    if not index:
        return answer, 0
    out, pos, fixed = [], 0, 0
    for m in _QUOTE_RE.finditer(answer):
        out.append(answer[pos : m.end()])
        pos = m.end()
        if _CITED_AFTER_RE.match(answer[m.end() : m.end() + 90]):
            continue  # already attributed
        probe = re.sub(r"\s+", " ", m.group(1)).strip().lower()
        label = ""
        for plen in (140, 90, 55):
            head = probe[:plen]
            if len(head) < 25:
                continue
            for text, lab in index:
                if head in text:
                    label = lab
                    break
            if label:
                break
        if label:
            out.append(f" ({label})")
            fixed += 1
    out.append(answer[pos:])
    return "".join(out), fixed


def _verify_quotes(answer, passages):
    """Quoted strings in the answer that can't be grounded in the provided passages."""
    quoted = re.findall(
        r'(?<![A-Za-z0-9])["“]([^"“”]{20,})["”](?![A-Za-z0-9])', answer or ""
    )
    if not quoted:
        return []
    blob = " ".join(
        str(p.get("content") or p.get("excerpt", "")).lower() for p in passages
    )
    blob_words = set(re.findall(r"[a-z0-9']{3,}", blob))
    ungrounded = []
    for q in quoted:
        low = re.sub(r"\s+", " ", q.lower()).strip()
        words = re.findall(r"[a-z0-9']{3,}", low)
        if not words:
            continue
        matched = sum(1 for w in words if w in blob_words)
        # 0.5: tolerate paraphrase while still catching fabrications
        if matched / len(words) < 0.5:
            ungrounded.append(q)
    return ungrounded


def _mark_ungrounded_quotes(answer, passages):
    """Wrap quotes the passages cannot ground in ⟪…⟫ (the invented-content
    marker), so a fabrication is flagged IN PLACE instead of only warned about
    in a trailing note. Returns (marked_answer, marked_count)."""
    if not answer:
        return answer, 0
    try:
        bad = _verify_quotes(answer, passages) or []
    except Exception:
        return answer, 0
    out = answer
    marked = 0
    for frag in bad:
        for variant in (frag, re.sub(r"\s+", " ", frag)):
            if variant and variant in out:
                out = out.replace(variant, "\u27ea" + variant + "\u27eb", 1)
                marked += 1
                break
    return out, marked


_CITE_PAIR_RE = re.compile(r"\(([^()\n]{3,90}?) · ([^()\n]{1,90}?)\)")


def _mark_ungrounded_citations(answer, passages):
    """Wrap inline citations whose LOCATION the passages do not show in ⟪…⟫.

    _mark_ungrounded_quotes checks the quoted TEXT; the (Book · location) label
    itself went unverified, so a model can cite a real book with a fabricated
    chapter/page/verse. This checks each cited location against the passages
    for that book — their _citation_for labels (chapter markers, PDF pages,
    Quran verses) and their raw content — and marks unsupported locations.
    Conservative: only flags when the book IS among the retrieved passages, so
    legitimate cross-references are left alone. Returns (answer, marked_count).

    OPT-IN (MENTAT_CITE_VERIFY=1). Default-off because testing showed it
    over-flags: the model legitimately cites chapters/appendix sections/verses
    that are real but not present in the top-k retrieved passages (e.g.
    "Chapter 33", "TERMINOLOGY OF THE IMPERIUM", "3:190"), so marking them
    corrupts good answers. A precise version needs the full book's marker set,
    not just the retrieved passages.
    """
    if not answer or not passages:
        return answer, 0
    labels, blobs = {}, {}
    for p in passages:
        label = _citation_for(p)
        if not label:
            continue
        b = label.split(" · ")[0].strip().lower()
        labels.setdefault(b, []).append(label.lower())
        content = str(p.get("content") or p.get("excerpt") or "").lower()
        blobs.setdefault(b, []).append(content)
    if not labels:
        return answer, 0
    out, marked = answer, 0
    for m in list(_CITE_PAIR_RE.finditer(answer)):
        book, loc = m.group(1).strip(), m.group(2).strip()
        bkey, loc_l = book.lower(), loc.lower().strip()
        match = next((b for b in labels if b and (b in bkey or bkey in b)), None)
        if not match or len(loc_l) < 3:
            continue
        supported = any(loc_l in lab for lab in labels[match]) or any(
            loc_l in blob for blob in blobs.get(match, [])
        )
        if supported:
            continue
        original = m.group(0)
        if original in out:
            out = out.replace(original, f"({book} · \u27ea{loc}\u27eb)", 1)
            marked += 1
    return out, marked


async def _repair_ungrounded(question, answer, passages):
    """One targeted self-correction pass over an answer with flagged problems.

    The verifiers flag ungrounded quotes and fabricated citation locations; this
    asks the model to fix ONLY those, grounded in the exact library spans, and
    keeps the repaired answer only if it still looks like a real answer. This is
    the local "think -> check -> repair" step: the system corrects itself instead
    of shipping flagged text. Set MENTAT_REPAIR=1 to enable (opt-in: it can turn
    a flagged fake quote into an unflagged paraphrase, so the default is to MARK
    and surface problems rather than silently rewrite them).
    """
    if not os.getenv("MENTAT_REPAIR") or not answer or not passages:
        return answer
    issues = []
    try:
        bad_q = _verify_quotes(answer, passages) or []
        if bad_q:
            issues.append(f"{len(bad_q)} quote(s) not found verbatim in the evidence")
    except Exception:
        pass
    try:
        _, bad_c = _mark_ungrounded_citations(answer, passages)
        if bad_c:
            issues.append(f"{bad_c} citation location(s) the evidence does not show")
    except Exception:
        pass
    if not issues:
        return answer
    evidence = ""
    try:
        evidence = _render_passage_block(passages, max_chars=1800)
    except Exception:
        evidence = ""
    prompt = (
        "Your previous answer has problems:\n- " + "\n- ".join(issues) + "\n\n"
        "Fix ONLY those problems, working ONLY from the EVIDENCE below:\n"
        "1. For every quote not found verbatim in the evidence: replace it with a "
        "verbatim span from the EVIDENCE, or turn it into a labelled paraphrase "
        "and drop the quotation marks. Never invent a quote.\n"
        "2. For every citation location the evidence does not show: correct it to "
        "a location the evidence DOES show, or remove the location (keep the book).\n"
        "3. Never cite a book that is not in the EVIDENCE. If nothing in the "
        "evidence supports the claim, say so plainly instead.\n"
        "Change nothing else - keep all correct quotes, citations, and prose "
        "intact. Return ONLY the corrected answer.\n\n"
        "EVIDENCE:\n"
        + (evidence or "(no evidence available - drop unverifiable quotes and say so)")
        + "\n\nPREVIOUS ANSWER:\n" + str(answer)
    )
    try:
        fixed = await query_llm(
            prompt,
            system_prompt="You are a meticulous editor. Fix only what is flagged.",
            **({"think": False} if _offline() else {}),
        )
        fixed = str(fixed or "").strip()
        if fixed and len(fixed) > 60:
            return fixed
    except Exception:
        pass
    return answer


def _extract_txt(path):
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return Path(path).read_text(encoding=encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return Path(path).read_text(errors="ignore")


def _ocr_page_text(page, dpi=200):
    """Apple Vision OCR of one PDF page (rendered to an image).

    Used for scanned/image PDFs where pymupdf's text layer is empty.
    Results are ordered top-to-bottom, left-to-right.
    """
    import Vision

    pix = page.get_pixmap(dpi=dpi)
    png = pix.tobytes("png")
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setUsesLanguageCorrection_(True)
    handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(png, None)
    ok, err = handler.performRequests_error_([request], None)
    if not ok:
        return ""
    results = sorted(
        request.results() or [],
        key=lambda r: (-r.boundingBox().origin.y, r.boundingBox().origin.x),
    )
    return "\n".join(r.topCandidates_(1)[0].string() for r in results)


def _extract_pdf(path):
    import pymupdf

    doc = pymupdf.open(str(path))
    try:
        parts = []
        for index, page in enumerate(doc, start=1):
            text = page.get_text().strip()
            if not text:
                try:
                    text = _ocr_page_text(page)
                except Exception:
                    text = ""
            if text:
                parts.append(f"## Page {index}\n\n{text}")
        return "\n\n".join(parts)
    finally:
        doc.close()


def _strip_html(text):
    """Strip tags but PRESERVE paragraph/line breaks (for verse, poetry, dialogue)."""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
    # block-level boundaries become newlines
    text = re.sub(r"</?(p|div|br|li|h[1-6]|blockquote|tr|ul|ol|table)[^>]*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.split("\n")]
    out = []
    blanks = 0
    for ln in lines:
        if ln:
            out.append(ln)
            blanks = 0
        elif out and blanks < 1:
            out.append("")
            blanks += 1
    return "\n".join(out).strip()


def _epub_item_body(item):
    """Return an epub item's raw body bytes, handling both ebooklib item APIs."""
    getter = getattr(item, "get_body_content", None)
    if getter is None:
        getter = getattr(item, "get_content", None)
    if getter is None:
        return b""
    try:
        return getter() or b""
    except Exception:
        return b""


def _extract_epub(path):
    import ebooklib
    from ebooklib import epub

    book = epub.read_epub(str(path))
    parts = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        content = _epub_item_body(item).decode("utf-8", errors="ignore")
        text = _strip_html(content)
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def _extract_epub_chapters(path):
    from ebooklib import epub

    book = epub.read_epub(str(path))
    chapters = []
    seq = 0
    for item_id in book.spine:
        item = book.get_item_with_id(item_id[0])
        if item is None:
            continue
        name = item.get_name()
        content = _epub_item_body(item).decode("utf-8", errors="ignore")
        text = _strip_html(content).strip()
        if not text:
            continue
        if name and re.search(r"(toc|nav)", name, re.I):
            continue
        low = text.lower()
        if len(text) < 200 and "table of contents" in low:
            continue
        marker = None
        m = re.search(r"(?:chapter|ch)[\s_.\-]*(\d+)", name, re.I)
        if m:
            marker = f"Chapter {int(m.group(1))}"
        else:
            m = re.search(r"part[\s_.\-]*(\d+)", name, re.I)
            if m:
                marker = f"Book {int(m.group(1))}"
        if not marker:
            heading = re.search(r"<h[1-3][^>]*>(.*?)</h[1-3]>", content, re.S | re.I)
            title = re.sub(r"<[^>]+>", "", heading.group(1)).strip() if heading else ""
            marker = title or f"Chapter {seq + 1}"
        seq += 1
        chapters.append(
            {
                "marker": marker,
                "suffix": f"ch{seq}",
                "text": f"## {marker}\n\n{text}",
            }
        )
    return chapters


def _extract_docx(path):
    from docx import Document

    document = Document(str(path))
    parts = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                if cell.text.strip():
                    parts.append(cell.text)
    return "\n\n".join(parts)


def extract_text(path):
    suffix = Path(path).suffix.lower()
    if suffix in (".txt", ".md", ".markdown", ".html", ".htm", ".rst"):
        return _extract_txt(path)
    if suffix == ".pdf":
        return _extract_pdf(path)
    if suffix == ".epub":
        return _extract_epub(path)
    if suffix == ".docx":
        return _extract_docx(path)
    raise ValueError(f"unsupported file type: {suffix or '(none)'}")


def _fetch_url_text(url, max_bytes=500_000):
    import urllib.request

    request = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (Mentat)"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        content_type = response.headers.get("Content-Type", "")
        data = response.read(max_bytes + 1)
        truncated = len(data) > max_bytes
        if truncated:
            data = data[:max_bytes]
        decoded = data.decode("utf-8", errors="ignore").lstrip()
        if "html" in content_type or decoded.startswith("<"):
            text = _strip_html(decoded)
        else:
            text = decoded
    text = text.strip()
    if truncated:
        text = text + "\n\n[truncated: saved first 500 KB]"
    return text


def _iter_knowledge_files():
    if not KNOWLEDGE_ROOT.exists():
        return
    for dirpath, dirnames, filenames in os.walk(KNOWLEDGE_ROOT):
        dirnames[:] = [
            d
            for d in dirnames
            if not d.startswith(".") and d != APP_DIR_NAME and d != "__pycache__"
        ]
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            path = Path(dirpath) / name
            if path.suffix.lower() in SKIP_SUFFIXES:
                continue
            yield path


def _file_hash(path, chunk_size=1 << 20):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _file_size(path):
    try:
        return path.stat().st_size
    except Exception:
        return 0


def _doc_id(rel_path):
    return "doc-" + hashlib.md5(str(KNOWLEDGE_ROOT / rel_path).encode()).hexdigest()


def _chapter_doc_id(rel_path, suffix):
    return "doc-" + hashlib.md5(
        (str(KNOWLEDGE_ROOT / rel_path) + "::" + str(suffix)).encode()
    ).hexdigest()


def _entry_hash(entry):
    if isinstance(entry, dict):
        return entry.get("hash", "")
    return entry


def _entry_docs(entry):
    if isinstance(entry, dict):
        return entry.get("docs", [])
    return []


def _index_is_running():
    import subprocess as sp

    try:
        matches = sp.run(
            ["pgrep", "-f", "brain.py index"], capture_output=True, text=True
        ).stdout.split()
    except Exception:
        return False
    own = {str(os.getpid()), str(os.getppid())}
    return any(pid not in own for pid in matches)


def _load_manifest():
    if MANIFEST_PATH.exists():
        try:
            return json.loads(MANIFEST_PATH.read_text())
        except Exception:
            return {}
    return {}


def _save_manifest(manifest):
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True))


def _load_legacy_history():
    """Raw read of the old flat history.json (used only by the one-time migration)."""
    if HISTORY_PATH.exists():
        try:
            data = json.loads(HISTORY_PATH.read_text())
            return data if isinstance(data, list) else []
        except Exception:
            return []
    return []


# ---------- conversational history store ----------
# Conversations live one-per-file under storage/conversations/ with a tiny
# index.json for the sidebar. Every mutation is serialized (process-local RLock
# + cross-process flock) and written atomically (tmp + os.replace), so a torn
# write or a second process can never clobber the history the way the old
# single flat file could. Conversation ids are uuid4 hex: collision-proof even
# across processes.

CONV_DIR = STORAGE_DIR / "conversations"
CONV_INDEX_PATH = CONV_DIR / "index.json"
CONV_STATE_PATH = STORAGE_DIR / "state.json"
CONV_LOCK_PATH = CONV_DIR / ".lock"
_CONVO_GAP_HOURS = 4.0

_history_rlock = threading.RLock()
_lock_file_handle = None


def _file_lock():
    global _lock_file_handle
    if _lock_file_handle is None:
        CONV_DIR.mkdir(parents=True, exist_ok=True)
        _lock_file_handle = open(CONV_LOCK_PATH, "a+")
    return _lock_file_handle


@contextmanager
def _conv_lock():
    handle = _file_lock()
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    _history_rlock.acquire()
    try:
        yield
    finally:
        _history_rlock.release()
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(data)
    os.replace(tmp, path)


def _parse_ts(ts):
    try:
        return time.mktime(time.strptime(str(ts), "%Y-%m-%d %H:%M:%S"))
    except Exception:
        return None


def _load_index():
    try:
        data = json.loads(CONV_INDEX_PATH.read_text())
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_index(index):
    _atomic_write(CONV_INDEX_PATH, json.dumps(index, indent=2, ensure_ascii=False))


def _conv_dir(conv_id):
    return CONV_DIR / conv_id


def _conv_path(conv_id):
    return _conv_dir(conv_id) / "turns.json"


def _conv_docs_dir(conv_id):
    return _conv_dir(conv_id) / "docs"


def _load_conv(conv_id):
    if not conv_id:
        return []
    try:
        data = json.loads(_conv_path(conv_id).read_text())
        return data.get("turns", []) if isinstance(data, dict) else []
    except Exception:
        return []


def _save_conv(conv_id, turns):
    _atomic_write(
        _conv_path(conv_id),
        json.dumps({"conv": conv_id, "turns": turns}, indent=2, ensure_ascii=False),
    )


def _load_state():
    try:
        data = json.loads(CONV_STATE_PATH.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_state(state):
    _atomic_write(CONV_STATE_PATH, json.dumps(state, indent=2))


def _new_conv_id():
    return uuid.uuid4().hex


def _current_conv_id():
    """The conversation new questions continue: explicit state first, else the
    most recently updated conversation if it is still fresh (so restarts
    continue the chat)."""
    state = _load_state()
    if state.get("current"):
        return state["current"]
    index = _load_index()
    if not index:
        return None
    last = index[-1]
    ts = _parse_ts(last.get("updated"))
    if ts is not None and (time.time() - ts) <= _CONVO_GAP_HOURS * 3600:
        return last.get("conv") or None
    return None


def _set_current_conv(conv_id):
    state = _load_state()
    state["current"] = conv_id
    _save_state(state)


def _ensure_conv():
    """Return the active conversation id, creating one if none is set — so
    session memory (analysis/census) has a home from the very first turn."""
    conv = _current_conv_id()
    if conv:
        return conv
    conv = _new_conv_id()
    state = _load_state()
    state["current"] = conv
    _save_state(state)
    return conv


def _touch_index_unlocked(conv_id, turns):
    """Rebuild this conversation's index row from its turns (caller holds the lock)."""
    index = _load_index()
    row = next((r for r in index if r.get("conv") == conv_id), None)
    if row is None:
        row = {"conv": conv_id, "created": turns[0].get("timestamp", "") if turns else ""}
        index.append(row)
    row["updated"] = turns[-1].get("timestamp", "") if turns else row.get("updated", "")
    row["count"] = len(turns)
    if turns:
        row.setdefault("first_q", turns[0].get("question") or "")
    if not (row.get("summary") or "").strip():
        summary = ""
        for e in reversed(turns):
            summary = (e.get("summary") or "").strip()
            if summary:
                break
        row["summary"] = summary or (_short_summary(turns[0].get("question") or "") if turns else "")
    index.sort(key=lambda r: r.get("updated") or "")
    _save_index(index)


def _append_history(entry):
    """Append a turn to the current conversation (or a fresh one)."""
    if not _store_ok():
        raise RuntimeError(STORAGE_STALE_MSG)
    with _conv_lock():
        conv = _current_conv_id() or _new_conv_id()
        entry["conv"] = conv
        turns = _load_conv(conv)
        turns.append(entry)
        _save_conv(conv, turns)
        _touch_index_unlocked(conv, turns)
        state = _load_state()
        state["current"] = conv
        _save_state(state)


def _update_history_summary(conv_id, timestamp, question, summary):
    """Store a summary on the matching turn of one conversation."""
    with _conv_lock():
        turns = _load_conv(conv_id)
        for e in turns:
            if e.get("timestamp") == timestamp and e.get("question") == question:
                e["summary"] = summary
                break
        _save_conv(conv_id, turns)
        _touch_index_unlocked(conv_id, turns)


def _conversations():
    """One row per conversation, most recently updated last."""
    out = []
    for row in _load_index():
        out.append(
            {
                "conv": row.get("conv"),
                "count": row.get("count", 0),
                "first_ts": row.get("created") or "",
                "last_ts": row.get("updated") or "",
                "summary": row.get("summary") or "",
                "question": row.get("first_q") or "",
            }
        )
    return out


def _delete_conversation(conv_id):
    """Delete a whole conversation. Returns the number of removed turns."""
    with _conv_lock():
        removed = len(_load_conv(conv_id))
        try:
            shutil.rmtree(_conv_dir(conv_id), ignore_errors=True)
        except Exception:
            pass
        index = [r for r in _load_index() if r.get("conv") != conv_id]
        _save_index(index)
        if _load_state().get("current") == conv_id:
            _save_state({"current": index[-1].get("conv") if index else ""})
        return removed


def _delete_history(index):
    """Delete one turn of the current conversation (0 = oldest)."""
    conv = _current_conv_id()
    if not conv:
        return None
    with _conv_lock():
        turns = _load_conv(conv)
        if index < 0 or index >= len(turns):
            return None
        removed = turns.pop(index)
        _save_conv(conv, turns)
        _touch_index_unlocked(conv, turns)
        return removed


def _acquire_app_lock():
    """Prevent two interactive instances from clobbering each other's state.

    Returns a handle that must stay referenced for the lock's lifetime, or
    None if another live instance holds it. The lock dies with the process
    (flock semantics), so stale locks clear themselves.
    """
    handle = open(STORAGE_DIR / "app.lock", "a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        try:
            handle.close()
        except Exception:
            pass
        return None
    try:
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
    except Exception:
        pass
    return handle


def _app_lock_holder_pid():
    """PID recorded in the app lock file, or None when absent/stale."""
    try:
        raw = (STORAGE_DIR / "app.lock").read_text().strip()
        pid = int(raw)
    except Exception:
        return None
    if pid <= 0 or pid == os.getpid():
        return None
    try:
        os.kill(pid, 0)
    except OSError:
        return None  # recorded process is gone — stale lock
    return pid


def _release_stale_lock():
    """Remove the lock file when no live process holds it. True if removed."""
    try:
        path = STORAGE_DIR / "app.lock"
        if not path.exists():
            return False
        if _app_lock_holder_pid() is not None:
            return False
        # no live holder (flock died with the process) — clear the file
        path.unlink()
        return True
    except Exception:
        return False


def _migrate_legacy_history():
    """One-time move from the flat history.json to per-conversation files.

    Existing conv groupings are preserved; conv-less entries (written by stale
    old-version processes) are grouped by >_CONVO_GAP_HOURS gaps. The legacy
    file is kept as history.legacy.json. Never runs on read paths again.
    """
    if not HISTORY_PATH.exists():
        return
    if _load_index():
        try:
            HISTORY_PATH.rename(HISTORY_PATH.with_name("history.legacy.json"))
        except Exception:
            pass
        return
    history = _load_legacy_history()
    if not history:
        return
    groups = {}
    order = []
    current = None
    last_ts = None
    for e in history:
        ts = _parse_ts(e.get("timestamp"))
        if not e.get("conv"):
            if current is None or (
                last_ts is not None
                and ts is not None
                and (ts - last_ts) > _CONVO_GAP_HOURS * 3600
            ):
                current = f"legacy-{uuid.uuid4().hex[:12]}"
            e["conv"] = current
        else:
            current = e["conv"]
        if ts is not None:
            last_ts = ts
        if current not in groups:
            groups[current] = []
            order.append(current)
        groups[current].append(e)
    with _conv_lock():
        state = _load_state()
        old_state = {}
        try:
            old_state = json.loads((STORAGE_DIR / "conv_state.json").read_text()) or {}
        except Exception:
            pass
        current_conv = state.get("current") or old_state.get("current")
        remap = {}
        index = []
        for old in order:
            new_id = uuid.uuid4().hex
            remap[old] = new_id
            turns = groups[old]
            for e in turns:
                e["conv"] = new_id
            _save_conv(new_id, turns)
            summary = ""
            for e in reversed(turns):
                summary = (e.get("summary") or "").strip()
                if summary:
                    break
            if not summary:
                summary = _short_summary(turns[0].get("question") or "")
            index.append(
                {
                    "conv": new_id,
                    "created": turns[0].get("timestamp") or "",
                    "updated": turns[-1].get("timestamp") or "",
                    "count": len(turns),
                    "summary": summary,
                    "first_q": turns[0].get("question") or "",
                }
            )
        index.sort(key=lambda r: r.get("updated") or "")
        _save_index(index)
        if current_conv and current_conv in remap:
            _save_state({"current": remap[current_conv]})
        elif not state.get("current") and index:
            _save_state({"current": index[-1]["conv"]})
    try:
        HISTORY_PATH.rename(HISTORY_PATH.with_name("history.legacy.json"))
    except Exception:
        pass
    try:
        (STORAGE_DIR / "conv_state.json").rename(STORAGE_DIR / "conv_state.legacy.json")
    except Exception:
        pass


def _audit():
    """Report-card over every subsystem: storage, index consistency, pending
    work, conversations, and telemetry-derived health. Read-only."""
    report = {}
    try:
        report["files"] = {
            p.name: p.stat().st_size
            for p in sorted(STORAGE_DIR.iterdir())
            if p.is_file()
        }
    except Exception:
        report["files"] = {}
    report["chunks"] = len(_load_chunk_texts())
    try:
        fts_n = _fts_db().execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
    except Exception:
        fts_n = -1
    report["fts_rows"] = fts_n
    try:
        vec_n = _vec_db().execute("SELECT count(*) FROM chunks_vec").fetchone()[0]
    except Exception:
        vec_n = -1
    report["vec_rows"] = vec_n
    report["index_consistent"] = fts_n == report["chunks"] == vec_n
    report["manifest_books"] = len(_load_manifest())
    try:
        brain = Brain()
        new, changed, removed, _ = brain._scan_changes()
        report["pending_files"] = len(new) + len(changed)
        report["removed_files"] = len(removed)
    except Exception:
        report["pending_files"] = -1
    report["legacy_json_stores"] = [
        n for n in (
            "kv_store_text_chunks.json", "kv_store_full_docs.json",
            "vdb_chunks.json", "kv_store_doc_status.json",
        )
        if (STORAGE_DIR / n).exists()
    ]
    convs = _conversations()
    report["conversations"] = len(convs)
    report["broken_convs"] = sum(
        1 for c in convs if not _conv_path(c.get("conv")).exists()
    )
    report["telemetry"] = {}
    try:
        conn = _telemetry_conn()
        report["telemetry"]["asks"] = conn.execute("SELECT count(*) FROM asks").fetchone()[0]
        report["telemetry"]["retries"] = conn.execute("SELECT count(*) FROM asks WHERE fast_retry=1").fetchone()[0]
        report["telemetry"]["no_answer"] = conn.execute("SELECT count(*) FROM asks WHERE status='no_answer'").fetchone()[0]
        n_ret = conn.execute("SELECT count(*) FROM retrieval").fetchone()[0] or 0
        n_cit = conn.execute("SELECT count(*) FROM retrieval WHERE cited=1").fetchone()[0] or 0
        report["telemetry"]["citation_precision_pct"] = round(100.0 * n_cit / max(1, n_ret), 1)
        conn.close()
    except Exception:
        pass
    # integrity gates
    report["integrity"] = {}
    try:
        row = _library_db().execute(
            "SELECT v FROM lib_meta WHERE k='code_version'"
        ).fetchone()
        data_ver = int(row[0]) if row else 0
        report["integrity"]["store_version"] = data_ver
        report["integrity"]["code_version"] = CODE_VERSION
        report["integrity"]["store_fresh"] = data_ver <= CODE_VERSION
    except Exception:
        report["integrity"]["store_fresh"] = True
    try:
        leaks = 0
        for key, entry in _book_map().items():
            ids = _fts_search_scoped(["the", "and"], key, limit=8)
            if any(cid not in entry["ids"] for cid in ids):
                leaks += 1
        report["integrity"]["shelf_leaks"] = leaks
    except Exception:
        report["integrity"]["shelf_leaks"] = -1
    return report


def _migrate_conv_folders():
    """One-time move from flat <uuid>.json files to <uuid>/turns.json folders
    (folders let each conversation carry a private docs/ workspace)."""
    if not CONV_DIR.exists():
        return
    try:
        for child in list(CONV_DIR.iterdir()):
            if not child.is_file() or child.suffix != ".json" or child.name == "index.json":
                continue
            if not re.fullmatch(r"[0-9a-f]{32}", child.stem):
                continue
            try:
                conv_id = child.stem
                data = child.read_text()
                _conv_dir(conv_id).mkdir(parents=True, exist_ok=True)
                _atomic_write(_conv_path(conv_id), data)
                child.unlink(missing_ok=True)
            except Exception:
                pass
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Draft workspace — per-conversation working documents. Attached drafts are
# copied into the conversation's private docs/ folder, chunked and searched
# locally to that conversation (never the global library), and deleted with it.
# ---------------------------------------------------------------------------

DRAFT_INSTRUCTION = (
    "\n\nThe passages labeled [YOUR DRAFT: ...] below are the user's own "
    "work-in-progress. Treat them as editable working material, NOT as sources: "
    "quote them back as needed, correct their logic, propose revisions, and "
    "recommend quotes from the library (cited by book · chapter) to support or "
    "replace claims. Never cite a draft as an authoritative source."
)


def _safe_doc_name(name):
    safe = re.sub(r"[^A-Za-z0-9._ -]", "_", str(name or "draft"))
    safe = safe.strip().strip(".")
    return safe[:120] or "draft"


def _split_text_chunks(text, size=4000, overlap=200):
    """Paragraph-aware chunking for ingestion (~size chars, overlap carry)."""
    text = str(text or "").strip()
    if not text:
        return []
    paras = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    chunks = []
    buf = ""
    for p in paras:
        while len(p) > size:
            chunks.append(p[:size])
            p = p[size - overlap :]
        if buf and len(buf) + len(p) + 2 > size:
            chunks.append(buf)
            buf = p
        else:
            buf = (buf + "\n\n" + p).strip() if buf else p
    if buf:
        chunks.append(buf)
    return chunks


def _doc_chunks(text, size=1100, overlap=120):
    """Split draft text into overlapping chunks at paragraph boundaries."""
    text = str(text or "").strip()
    if not text:
        return []
    paras = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    chunks = []
    buf = ""
    for p in paras:
        while len(p) > size:
            chunks.append(p[:size])
            p = p[size - overlap:]
        if buf and len(buf) + len(p) + 2 > size:
            chunks.append(buf)
            buf = p
        else:
            buf = (buf + "\n\n" + p).strip() if buf else p
    if buf:
        chunks.append(buf)
    return chunks


def _attach_conv_doc(conv_id, name, text):
    """Copy a working document into the conversation's private docs folder."""
    docs_dir = _conv_docs_dir(conv_id)
    docs_dir.mkdir(parents=True, exist_ok=True)
    path = docs_dir / _safe_doc_name(name)
    _atomic_write(path, str(text or ""))
    return path.name


def _list_conv_docs(conv_id):
    docs_dir = _conv_docs_dir(conv_id)
    if not docs_dir.exists():
        return []
    out = []
    for p in sorted(docs_dir.iterdir()):
        if p.is_file() and not p.name.startswith("."):
            out.append({"name": p.name, "chars": p.stat().st_size})
    return out


def _detach_conv_doc(conv_id, name):
    docs_dir = _conv_docs_dir(conv_id)
    try:
        (docs_dir / _safe_doc_name(name)).unlink(missing_ok=True)
        return True
    except Exception:
        return False


def _search_conv_docs(conv_id, query, k=6):
    """Cheap overlap-ranked search over the conversation's own drafts."""
    docs = _list_conv_docs(conv_id)
    if not docs:
        return []
    q = _normalize_query(query or "")
    terms = [t for t in re.findall(r"[a-z0-9'-]{3,}", q) if t not in _SEARCH_STOPWORDS]
    scored = []
    for d in docs:
        try:
            text = (_conv_docs_dir(conv_id) / d["name"]).read_text()
        except Exception:
            continue
        for chunk in _doc_chunks(text):
            low = chunk.lower()
            score = sum(low.count(t) for t in terms)
            if score > 0:
                scored.append({"name": d["name"], "text": chunk, "score": score})
    scored.sort(key=lambda c: c["score"], reverse=True)
    return scored[:k]


def _render_draft_block(doc_chunks):
    parts = []
    for i, c in enumerate(doc_chunks, 1):
        parts.append(f"[YOUR DRAFT: {c['name']}]\n{c['text']}")
    block = "\n\n---\n\n".join(parts)
    return _escape_format("\n\n[DRAFT CONTEXT]\n" + block)


# ---------------------------------------------------------------------------
# Telemetry — the research diary. Logs every ask, its retrieved passages, and
# whether the answer actually used them. Append-only, fenced off so it can
# never break an answer; this is the training/eval data for future upgrades.
# ---------------------------------------------------------------------------

TELEMETRY_PATH = STORAGE_DIR / "telemetry.db"
_LAST_RETRIEVAL = []


def _telemetry_conn():
    conn = sqlite3.connect(TELEMETRY_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _telemetry_init():
    try:
        conn = _telemetry_conn()
        with conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS asks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT, conv_id TEXT, question TEXT,
                    mode TEXT, model TEXT, voice TEXT, thinking TEXT,
                    strategy TEXT, docs_count INTEGER DEFAULT 0,
                    t_open REAL, t_route REAL, t_passages REAL, t_answer REAL,
                    status TEXT, fast_retry INTEGER DEFAULT 0,
                    ungrounded INTEGER DEFAULT 0, answer_len INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS retrieval (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ask_id INTEGER, rank INTEGER,
                    chunk_id TEXT, book TEXT, chapter TEXT,
                    source TEXT, named_priority INTEGER DEFAULT 0,
                    in_context INTEGER DEFAULT 1, cited INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT, conv_id TEXT, kind TEXT, detail TEXT
                );
                """
            )
            try:
                conn.execute("ALTER TABLE asks ADD COLUMN truncated INTEGER DEFAULT 0")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE asks ADD COLUMN served_local INTEGER DEFAULT 0")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE asks ADD COLUMN reasoning_len INTEGER DEFAULT 0")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE asks ADD COLUMN t_thinking REAL")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE asks ADD COLUMN t_content REAL")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE asks ADD COLUMN tokens_in INTEGER DEFAULT 0")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE asks ADD COLUMN tokens_out INTEGER DEFAULT 0")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE asks ADD COLUMN cost_usd REAL DEFAULT 0")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE asks ADD COLUMN route_reason TEXT")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE asks ADD COLUMN kind TEXT")
            except Exception:
                pass
        conn.close()
    except Exception:
        pass


def _telemetry_log_ask(row):
    try:
        _telemetry_init()
        row = dict(row or {})
        row["truncated"] = int(row.get("truncated") or 0)
        row["served_local"] = int(row.get("served_local") or 0)
        row["reasoning_len"] = int(row.get("reasoning_len") or 0)
        row["t_thinking"] = row.get("t_thinking")
        row["t_content"] = row.get("t_content")
        row["tokens_in"] = int(row.get("tokens_in") or 0)
        row["tokens_out"] = int(row.get("tokens_out") or 0)
        row["cost_usd"] = float(row.get("cost_usd") or 0.0)
        row["route_reason"] = str(row.get("route_reason") or "")
        conn = _telemetry_conn()
        with conn:
            conn.execute(
                """INSERT INTO asks (ts, conv_id, question, mode, model, voice, thinking,
                   strategy, docs_count, t_open, t_route, t_passages, t_answer,
                   status, fast_retry, ungrounded, answer_len, truncated,
                   served_local, reasoning_len, t_thinking, t_content,
                   tokens_in, tokens_out, cost_usd, route_reason, kind)
                   VALUES (:ts,:conv_id,:question,:mode,:model,:voice,:thinking,
                   :strategy,:docs_count,:t_open,:t_route,:t_passages,:t_answer,
                   :status,:fast_retry,:ungrounded,:answer_len,:truncated,
                   :served_local,:reasoning_len,:t_thinking,:t_content,
                   :tokens_in,:tokens_out,:cost_usd,:route_reason,:kind)""",
                row,
            )
            ask_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()
        return ask_id
    except Exception:
        return None


def _telemetry_log_retrieval(rows):
    if not rows:
        return
    try:
        conn = _telemetry_conn()
        with conn:
            conn.executemany(
                """INSERT INTO retrieval (ask_id, rank, chunk_id, book, chapter, source,
                   named_priority, in_context, cited)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                rows,
            )
        conn.close()
    except Exception:
        pass


def _telemetry_log_feedback(kind, detail="", conv_id=None):
    try:
        _telemetry_init()
        conn = _telemetry_conn()
        with conn:
            conn.execute(
                "INSERT INTO feedback (ts, conv_id, kind, detail) VALUES (?,?,?,?)",
                (time.strftime("%Y-%m-%d %H:%M:%S"), conv_id or "", kind, detail),
            )
        conn.close()
    except Exception:
        pass


def _citation_needles(answer):
    """(book, chapter) citation tuples found in the answer text."""
    out = set()
    for m in re.finditer(r"\(([^()]{2,80}? · Chapter \d+)\)", str(answer or "")):
        parts = m.group(1).split(" · ")
        if len(parts) == 2:
            out.add((parts[0].strip(), parts[1].strip()))
    return out


def _match_citations(answer, passages):
    """Per-passage flags: did the answer cite this passage's book·chapter?

    Answers cite short names ('Dune Messiah') while passage paths carry full
    book paths ('books › Dune › Dune Messiah (Frank Herbert) .epub') — so the
    match accepts containment in EITHER direction on the book name.
    """
    needles = _citation_needles(answer)
    cited = []
    for p in passages or []:
        fp = str(p.get("file_path") or "")
        m = re.match(r"^(.*?) · Chapter (\d+)", fp)
        if not m:
            cited.append(False)
            continue
        book = _clean_name(m.group(1))
        short = book.rsplit(" › ", 1)[-1].rsplit("/", 1)[-1]
        chapter = m.group(2)
        hit = any(
            str(nc).replace("Chapter", "").strip() == chapter
            and (nb in short or short in nb or nb in book)
            for nb, nc in needles
        )
        cited.append(hit)
    return cited


def _flush_ask_telemetry(
    self, question, mode, settings, strategy, used_model, answer, passages,
    status, fast_retry=0, ungrounded=0, docs_count=0, entry=None, truncated=0,
    served_model="", reasoning_len=0, t_thinking=None, t_content=None,
    tokens_in=0, tokens_out=0, cost_usd=0.0, route_reason="", kind=""
):
    try:
        trace = {}
        for name, t in getattr(self, "_trace", []):
            if not name.startswith("passages"):
                trace[name] = t
        for name, t in getattr(self, "_trace", []):
            if name.startswith("passages"):
                trace["passages"] = t
        row = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "conv_id": (entry or {}).get("conv", "") or (_current_conv_id() or ""),
            "question": question,
            "mode": mode,
            "model": (served_model or used_model or ""),
            "voice": (settings or {}).get("voice", "default"),
            "thinking": str((settings or {}).get("thinking", "")),
            "strategy": strategy or "",
            "docs_count": int(docs_count or 0),
            "t_open": trace.get("open"),
            "t_route": trace.get("route"),
            "t_passages": trace.get("passages"),
            "t_answer": trace.get("answer"),
            "status": status,
            "fast_retry": 1 if fast_retry else 0,
            "ungrounded": int(ungrounded or 0),
            "answer_len": len(str(answer or "")),
            "truncated": int(truncated or 0),
            "served_local": 1 if "qwen" in str(served_model).lower() else 0,
            "reasoning_len": int(reasoning_len or 0),
            "t_thinking": t_thinking,
            "t_content": t_content,
            "tokens_in": int(tokens_in or 0),
            "tokens_out": int(tokens_out or 0),
            "cost_usd": float(cost_usd or 0.0),
            "route_reason": str(route_reason or _ROUTE_REASON or ""),
            "kind": str(kind or ""),
        }
        ask_id = _telemetry_log_ask(row)
        if ask_id:
            cited = _match_citations(answer, _LAST_RETRIEVAL)
            rows = []
            for i, r in enumerate(_LAST_RETRIEVAL):
                fp = str(r.get("file_path") or "")
                m = re.match(r"^(.*?) · Chapter (\d+)", fp)
                book = m.group(1) if m else fp[:60]
                chapter = m.group(2) if m else ""
                rows.append(
                    (
                        ask_id, i, r.get("chunk_id") or "", book, chapter,
                        "lib", 1 if r.get("named") else 0, 1,
                        1 if (i < len(cited) and cited[i]) else 0,
                    )
                )
            _telemetry_log_retrieval(rows)
    except Exception:
        pass


async def _summarize_question(question):
    """A 3-5 word summary of what a question asks (fast model, one call)."""
    try:
        out = await _fast_llm(
            "Summarize what this question is asking in 3-5 words. "
            "Reply with ONLY the summary, no quotes or punctuation.\n"
            f"Question: {question}"
        )
        out = _normalize_query(out or "")
        words = [w for w in re.findall(r"[A-Za-z'-]+", out) if len(w) > 1]
        words = [w[:-2] if w.endswith("'s") else w for w in words]
        return " ".join(words[:6]).strip()
    except Exception:
        return ""


async def _backfill_summaries(limit=20):
    """Summarize recent turns that lack a summary (for the sidebar)."""
    index = _load_index()
    for row in reversed(index[-limit:]):
        turns = _load_conv(row.get("conv"))
        missing = [e for e in turns[-limit:] if not (e.get("summary") or "").strip()]
        for e in missing:
            summary = await _summarize_question(e.get("question") or "")
            if summary:
                _update_history_summary(
                    row.get("conv"), e.get("timestamp"), e.get("question") or "", summary
                )


class Brain:
    def __init__(self):
        self._rag = None
        self._lock = asyncio.Lock()
        self._last_stream_result = None
        self._convo_summary = ""
        self._convo_summary_key = None
        self._trace = []
        self._progress = None
        self._store_writable = _check_store_version()
        if self._store_writable:
            _migrate_legacy_history()
            _migrate_conv_folders()

    async def _build_conversation_history(self):
        """Recent turns verbatim + a compressed summary of the older conversation."""
        settings = _load_settings()
        history = _load_conv(_current_conv_id())
        if not history:
            return []
        cap = settings.get("history_turns", 6)
        if len(history) <= cap:
            return self._history_messages(history)
        recent = history[-3:]
        older = history[:-3]
        key = len(older)
        # Rebuild the summary at most every 3 new turns (the last 3 are verbatim
        # anyway, so a slightly stale summary loses nothing important).
        if self._convo_summary_key is None or key - self._convo_summary_key >= 3:
            text = "\n\n".join(
                f"Q: {e.get('question', '')}\nA: {str(e.get('answer', ''))[:300]}"
                for e in older
            )
            try:
                summary = await _fast_llm(
                    "Compress this conversation into 3-4 sentences, keeping the "
                    "key topics, open questions, and anything the user cares about.\n\n"
                    + text
                )
                self._convo_summary = (summary or "").strip()
            except Exception:
                self._convo_summary = ""
            self._convo_summary_key = key
        msgs = []
        if self._convo_summary:
            msgs.append(
                {"role": "system", "content": "[Earlier conversation, summarized] " + self._convo_summary}
            )
        msgs += self._history_messages(recent)
        return msgs

    @staticmethod
    def _history_messages(entries):
        msgs = []
        for entry in entries:
            msgs.append({"role": "user", "content": entry.get("question", "")})
            msgs.append({"role": "assistant", "content": str(entry.get("answer", ""))[:3000]})
        return msgs

    async def open(self):
        """No-op compatibility: the brain no longer needs a framework instance."""
        return None

    async def close(self):
        pass

    def _scan_changes(self, only=None):
        global _STAT_CACHE
        manifest = _load_manifest()
        current = {}
        new_files = []
        changed_files = []
        for path in _iter_knowledge_files():
            rel = str(path.relative_to(KNOWLEDGE_ROOT))
            if only and not rel.startswith(only):
                continue
            try:
                st = path.stat()
                key = (st.st_size, st.st_mtime_ns)
            except OSError:
                continue
            cached = _STAT_CACHE.get(rel)
            if cached is not None and cached[0] == key:
                digest = cached[1]
                current[rel] = digest
                if rel not in manifest:
                    new_files.append(path)
                elif _entry_hash(manifest[rel]) != digest:
                    changed_files.append(path)
                continue
            digest = _file_hash(path)
            _STAT_CACHE[rel] = (key, digest)
            current[rel] = digest
            if rel not in manifest:
                new_files.append(path)
            elif _entry_hash(manifest[rel]) != digest:
                changed_files.append(path)
        for rel in list(_STAT_CACHE):
            if rel not in current:
                del _STAT_CACHE[rel]
        removed = [rel for rel in manifest if rel not in current]
        if only:
            removed = [rel for rel in removed if rel.startswith(only)]
        return new_files, changed_files, removed, current

    async def _insert_document(self, rag, path, rel):
        """Own ingestion: stage -> chunk -> embed -> insert (no LightRAG)."""
        docs = _staged_texts(path)
        if docs is None:
            docs = _stage_file(path)
        suffix = Path(path).suffix.lower()
        rel_display = str(Path(path).relative_to(KNOWLEDGE_ROOT))
        if suffix == ".epub" and docs and all(d.get("suffix") for d in docs):
            book_path = _clean_name(rel_display)
            pairs = []
            for d in docs:
                doc_id = _chapter_doc_id(rel, d["suffix"])
                for i, chunk_text in enumerate(
                    _split_text_chunks(str(d.get("text") or ""))
                ):
                    pairs.append(
                        (
                            f"{doc_id}-chunk-{i:03d}",
                            f"{book_path} · {d['marker']} ({d['suffix']})",
                            chunk_text,
                        )
                    )
        else:
            text = docs[0]["text"] if docs else extract_text(path)
            if not text.strip():
                raise ValueError("file produced no extractable text")
            doc_id = _doc_id(rel)
            display = _clean_name(rel_display).replace("/", " › ")
            pairs = [
                (
                    f"{doc_id}-chunk-{i:03d}",
                    display,
                    chunk_text,
                )
                for i, chunk_text in enumerate(_split_text_chunks(text))
            ]
        if not pairs:
            raise ValueError("file produced no chunks")
        await self._store_chunks(pairs)
        return sorted({p[0].rsplit("-chunk-", 1)[0] for p in pairs})

    async def _store_chunks(self, pairs):
        """Embed + insert chunks into library.db, fts, and vec."""
        ids = [p[0] for p in pairs]
        texts = [p[2] for p in pairs]
        embeddings = []
        for start in range(0, len(texts), 20):
            batch = texts[start : start + 20]
            try:
                emb = await nomic_embed(batch, context="document")
                embeddings.extend(emb)
            except Exception:
                raise RuntimeError("embedding failed")
        db = _library_db()
        rows = []
        for (cid, fp, text), emb in zip(pairs, embeddings):
            book = fp.split(" · ", 1)[0]
            ch = re.search(r"\(ch(\d+)\)", fp)
            chapter = ch.group(1) if ch else ""
            seq = 0
            seq_m = re.search(r"-chunk-(\d+)$", cid)
            if seq_m:
                seq = int(seq_m.group(1))
            rows.append((cid, fp, book, chapter, seq, text))
        db.executemany(
            "INSERT OR REPLACE INTO chunks (chunk_id, file_path, book, chapter, seq, content) "
            "VALUES (?,?,?,?,?,?)",
            rows,
        )
        db.commit()
        _fts_patch(
            [(cid, fp, text) for cid, fp, text in pairs],
            delete_prefixes={cid.rsplit("-chunk-", 1)[0] for cid in ids},
        )
        _vec_insert_many(ids, embeddings)
        try:
            _build_spans(chunk_ids=ids)
        except Exception:
            pass
        _refresh_caches()

    async def _delete_chunks_by_doc(self, doc_id):
        """Delete every chunk belonging to one document id (prefix match)."""
        db = _library_db()
        rows = db.execute(
            "SELECT chunk_id FROM chunks WHERE chunk_id LIKE ?", (doc_id + "-chunk-%",)
        ).fetchall()
        ids = [r[0] for r in rows]
        if not ids:
            return 0
        ph = ",".join("?" * len(ids))
        try:
            db.execute(
                f"DELETE FROM spans_fts WHERE span_id IN "
                f"(SELECT span_id FROM spans WHERE chunk_id IN ({ph}))",
                ids,
            )
            db.execute(f"DELETE FROM spans WHERE chunk_id IN ({ph})", ids)
            db.commit()
        except Exception:
            pass
        db.execute(f"DELETE FROM chunks WHERE chunk_id IN ({ph})", ids)
        db.commit()
        _vec_delete_many(ids)
        _fts_patch(delete_prefixes=(doc_id,))
        _refresh_caches()
        return len(ids)


    async def index(self, verbose=False, only=None):
        if not _store_ok():
            return {
                "indexed": 0, "updated": 0, "deleted": 0, "errors": [],
                "already_running": False, "store_stale": True,
                "message": STORAGE_STALE_MSG,
            }
        if _index_is_running():
            return {
                "indexed": 0,
                "updated": 0,
                "deleted": 0,
                "errors": [],
                "already_running": True,
                "message": (
                    "Another index run is already in progress. Wait for it to "
                    "finish, then try again (check `brain index-status`)."
                ),
            }

        manifest = _load_manifest()
        rag = await self.open()

        new_files, changed_files, removed, current = self._scan_changes(only=only)

        stats = {"indexed": 0, "updated": 0, "deleted": 0, "errors": []}

        work = new_files + changed_files
        prog = None
        if verbose:
            global _active_progress
            prog = _IndexProgress()
            prog.reset(work)
            _active_progress = prog

        try:
            for rel in removed:
                try:
                    for doc_id in (_entry_docs(manifest.get(rel)) or [_doc_id(rel)]):
                        await self._delete_chunks_by_doc(doc_id)
                    del manifest[rel]
                    stats["deleted"] += 1
                except Exception as exc:
                    stats["errors"].append(f"{rel}: {exc}")

            for path in changed_files:
                rel = str(path.relative_to(KNOWLEDGE_ROOT))
                try:
                    for doc_id in (_entry_docs(manifest.get(rel)) or [_doc_id(rel)]):
                        await self._delete_chunks_by_doc(doc_id)
                    doc_ids = await self._insert_document(rag, path, rel)
                    manifest[rel] = {"hash": current[rel], "docs": doc_ids}
                    stats["updated"] += 1
                    if prog:
                        prog.file_done(rel)
                        prog.clear()
                    if verbose:
                        print(f"updated: {rel}")
                        sys.stdout.flush()
                except Exception as exc:
                    stats["errors"].append(f"{rel}: {exc}")

            for path in new_files:
                rel = str(path.relative_to(KNOWLEDGE_ROOT))
                try:
                    doc_ids = await self._insert_document(rag, path, rel)
                    manifest[rel] = {"hash": current[rel], "docs": doc_ids}
                    stats["indexed"] += 1
                    if prog:
                        prog.file_done(rel)
                        prog.clear()
                    if verbose:
                        print(f"indexed: {rel}")
                        sys.stdout.flush()
                except Exception as exc:
                    stats["errors"].append(f"{rel}: {exc}")
        finally:
            if prog:
                prog.finish()
                _active_progress = None

        _save_manifest(manifest)

        # One full FTS reconciliation per batch (per-file maintenance is now
        # incremental via _fts_patch) — cheap insurance against edge cases.
        if work or removed:
            try:
                _fts_sync(force=True)
            except Exception:
                pass

        # Canary checks for the files we just indexed: verify each new/changed
        # book is actually retrievable before declaring success.
        processed = {str(p.relative_to(KNOWLEDGE_ROOT)) for p in (new_files + changed_files)}
        canary = []
        for rel in processed:
            try:
                for name, ok, detail in await _canary_check(rag, rel):
                    if not ok:
                        canary.append(f"{rel}: {name} — {detail}")
            except Exception as exc:
                canary.append(f"{rel}: canary error {exc}")
        if canary:
            stats["canary_warnings"] = canary
        return stats

    async def probe(self, question):
        """Diagnostic: show everything the answer would be grounded in, WITHOUT
        any LLM calls (strategy, terms, named sources, passages, routing)."""
        import time as _time

        t0 = _time.time()
        score = _question_heuristic_score(question)
        strategy = _retrieval_strategy(question, score)
        if strategy == "simple":
            strategy = "expand"  # mirror the answer path: every question is grounded
        if _has_universal_intent(question):
            strategy = "universal"
        rag = await self.open()
        terms = _derive_terms(question)
        named = _named_sources(question)
        passages = []
        if strategy != "simple":
            try:
                passages = await _probe_passages(rag, question)
            except Exception:
                pass
        route = await _route_model(question)
        block = _render_passage_block(passages)
        return {
            "question": question,
            "score": round(score, 3),
            "strategy": strategy,
            "universal": _has_universal_intent(question),
            "quote_intent": _has_quote_intent(question),
            "named_sources": named,
            "terms": terms,
            "route_model": route or _load_settings().get("model", ""),
            "passages": [
                {
                    "file_path": p.get("file_path", ""),
                    "named": bool(p.get("named")),
                    "excerpt": (p.get("excerpt") or "")[:220],
                }
                for p in passages
            ],
            "block_chars": len(block),
            "elapsed_s": round(_time.time() - t0, 2),
        }

    async def health(self):
        """Library health: store sanity + per-book retrievability canaries.

        Returns [(check, ok, detail), ...] — fast, no LLM calls.
        """
        import time as _time

        t0 = _time.time()
        results = []
        rag = await self.open()
        try:
            chunks = _load_chunk_texts()
            _fts_sync()
            _vec_sync()
            results.append(("chunk store", len(chunks) > 0, f"{len(chunks)} chunks"))
            nvec = _vec_db().execute("SELECT count(*) FROM chunks_vec").fetchone()[0]
            results.append(("vector store", nvec > 0, f"{nvec} vectors"))
            nbooks = len(_load_library_map().get("books", {}))
            results.append(("library map", nbooks > 0, f"{nbooks} books"))
            manifest = _load_manifest()
            for rel in sorted(manifest):
                try:
                    for name, ok, detail in await _canary_check(rag, rel):
                        label = f"{rel.split('/')[-1][:30]} :: {name}"
                        results.append((label, ok, detail))
                except Exception as exc:
                    results.append((rel.split("/")[-1][:30], False, str(exc)[:60]))
        finally:
            results.append(("elapsed", True, f"{_time.time() - t0:.1f}s"))
        return results

    async def ask(self, question, mode=None, lazy=True):
        if not _store_ok():
            return {
                "status": "store_stale",
                "question": question,
                "message": STORAGE_STALE_MSG,
            }
        settings = _load_settings()
        mode = mode or settings["mode"]
        _t0ask = time.time()
        self._trace = []

        def _t(name):
            self._trace.append((name, round(time.time() - _t0ask, 2)))

        _ensure_conv()

        if lazy:
            new_files, changed_files, removed, current = self._scan_changes()
            pending = len(new_files) + len(changed_files)
            if pending:
                new_bytes = sum(_file_size(p) for p in new_files) + sum(
                    _file_size(p) for p in changed_files
                )
                if pending <= AUTO_INDEX_MAX_FILES and new_bytes <= AUTO_INDEX_MAX_BYTES:
                    await self.index(verbose=False)
                elif _index_is_running():
                    return {
                        "status": "indexing_running",
                        "question": question,
                        "message": (
                            "An index run is already in progress — files are being "
                            "indexed in the background. Check `index-status` for live "
                            "progress, then ask again once it finishes."
                        ),
                    }
                else:
                    return {
                        "status": "needs_index",
                        "question": question,
                        "new_files": pending,
                        "new_bytes": new_bytes,
                        "message": (
                            f"{pending} new or changed file(s) "
                            f"({new_bytes / 1024 / 1024:.1f} MB) are not indexed yet. "
                            "Index them first with `brain index` (or the 'index' console command), "
                            "then ask again."
                        ),
                    }

        rag = await self.open()
        _t("open")

        conversation_history = await self._build_conversation_history()

        lens = (settings.get("lens") or "").strip()
        score = _question_heuristic_score(question)
        interpretive = _is_interpretive(question, score)

        sys_template = _rag_system_prompt(mode, interpretive=interpretive)
        if lens:
            lens_block = lens.replace("{", "{{").replace("}", "}}") + "\n\n"
            sys_template = lens_block + sys_template
        voice_block = VOICE_PRESETS.get(settings.get("voice", "default"), "")
        if voice_block:
            sys_template = voice_block + "\n\n" + sys_template
        # Comprehension FIRST: the strategy choice below wants the classifier's
        # kind (compare/research -> universal evidence), not just keywords.
        try:
            await _expand_query(question)
        except Exception:
            pass
        strategy = _retrieval_strategy(question, score)
        if strategy == "simple":
            strategy = "expand"  # the librarian grounds EVERY question now
        an_kind = str(_analysis(question).get("kind") or "").lower()
        if (
            _has_universal_intent(question)
            or an_kind in ("compare", "research", "argument", "synthesis", "universal")
        ):
            strategy = "universal"
        passages = []
        try:
            passages = await _build_passages(rag, question, strategy)
        except Exception as exc:
            _telemetry_log_feedback(
                "retrieval_error", str(exc)[:160], _current_conv_id()
            )
            passages = []
        census_block = ""
        try:
            census_ctx = _census_ctx(question, strategy)
            if census_ctx.get("keys") and passages:
                allowed = census_ctx["keys"]
                passages = [
                    p for p in passages
                    if _book_key(p.get("file_path", "")) in allowed
                ]
            census_block = census_ctx.get("block") or ""
        except Exception:
            census_block = ""
        try:
            block = _render_passage_block(
                passages,
                full=_has_quote_intent(question)
                or strategy in ("universal", "hunt"),
            )
            if block:
                sys_template = sys_template + block
        except Exception:
            pass
        if census_block:
            sys_template = sys_template + census_block
        if not passages:
            degrade = _retrieval_degraded_note()
            if degrade:
                _telemetry_log_feedback(
                    "retrieval_degraded", degrade[:200], _current_conv_id()
                )
                sys_template = sys_template + (
                    "\n\n[Retrieval warning: the library search degraded ("
                    + degrade
                    + "). The empty evidence is a system failure, not proof the "
                    "library lacks the text. Tell the user retrieval failed and "
                    "to check the index/embedder; never improvise an excuse.]"
                )
        try:
            cov = _evidence_coverage(passages)
        except Exception:
            cov = {"books": 0, "names": [], "chunks": 0}
        note = _coverage_note(cov, an_kind, strategy)
        if note and settings.get("coverage_notes", True):
            _telemetry_log_feedback(
                "coverage_thin",
                f"{cov['books']} book(s) for {an_kind or strategy}: "
                f"{', '.join(cov['names'])[:120]}",
                _current_conv_id(),
            )
            sys_template = sys_template + note
        if strategy == "universal":
            try:
                mp = await _build_library_map()
                map_block = _render_map_block(question, mp)
                if map_block:
                    sys_template = sys_template + map_block
                graph_block = _graph_block(question, passages)
                if graph_block:
                    sys_template = sys_template + graph_block
            except Exception:
                pass
        if _named_sources(question):
            sys_template = sys_template + "\n\n" + NAMED_SOURCE_INSTRUCTION
        doc_chunks = []
        try:
            doc_chunks = _search_conv_docs(_current_conv_id(), question, k=6)
            if doc_chunks:
                sys_template = sys_template + _render_draft_block(doc_chunks) + DRAFT_INSTRUCTION
        except Exception:
            doc_chunks = []
        try:
            sys_template = sys_template + _register_instruction(_question_kind(question))
        except Exception:
            pass
        try:
            mem = _memory_matches(question)
            if mem:
                sys_template = sys_template + _render_memory_block(mem)
        except Exception:
            pass
        sys_template = sys_template + _length_budget(question)
        try:
            if _question_kind(question) == "quotes":
                _qdraft = _extract_quote_draft(question, passages)
                if _qdraft:
                    sys_template = sys_template + _qdraft
        except Exception:
            pass
        if _offline():
            sys_template = sys_template + _offline_answer_rules(
                _question_kind(question)
            )

        global _ROUTE_OVERRIDE
        prev_route = _ROUTE_OVERRIDE
        retried = False
        ungrounded_n = 0
        _t("passages")
        try:
            an_kind = str(_analysis(question).get("kind") or "").lower()
            _ROUTE_OVERRIDE = await _route_model(
                question,
                force_deep=(
                    strategy == "universal"
                    or an_kind in ("compare", "research", "argument", "synthesis")
                    or bool(census_block)
                ),
            )
            answer = await query_llm(
                question,
                system_prompt=sys_template,
                history_messages=conversation_history,
                **(
                    {
                        "think": _question_kind(question)
                        in (
                            "compare", "research", "argument", "synthesis",
                            "concept", "commentary",
                        )
                    }
                    if _offline()
                    else {}
                ),
            )
            usage_snapshot = dict(_LAST_USAGE or {})

            if not (answer and str(answer).strip()):
                r_first = (_LAST_REASONING or "").strip()
                prev_route = _ROUTE_OVERRIDE
                retried = True
                # A reasoning model that burned its budget thinks but never
                # writes — retry with the non-reasoning chat model instead.
                _ROUTE_OVERRIDE = (
                    "qwen" if _offline() else "deepseek-flash"
                )
                try:
                    answer = await query_llm(
                        question,
                        system_prompt=sys_template,
                        history_messages=conversation_history,
                        **({"think": False} if _offline() else {}),
                    )
                finally:
                    _ROUTE_OVERRIDE = prev_route
                if not (answer and str(answer).strip()):
                    if r_first:
                        answer = (
                            "_The model reasoned but ran out of output budget "
                            "before writing; here is the tail of its reasoning._\n\n"
                            + r_first[-2500:]
                        )
                    else:
                        answer = _no_answer_line()
            served_model = _LAST_SERVED_MODEL
            if passages and settings.get("filter_references", True):
                try:
                    answer = _rewrite_references(answer, passages)
                except Exception:
                    pass
            if (
                passages
                and answer
                and str(answer).strip()
                and settings.get("auto_attribution", True)
            ):
                try:
                    answer, attributed = _ensure_quote_attribution(
                        str(answer), passages
                    )
                    if attributed:
                        _telemetry_log_feedback(
                            "quote_attributed",
                            f"{attributed} quote(s) auto-cited",
                            _current_conv_id(),
                        )
                except Exception:
                    pass
            if (
                _offline()
                and passages
                and answer
                and str(answer).strip()
                and os.getenv("MENTAT_REPAIR")
            ):
                try:
                    answer = await _repair_ungrounded(question, answer, passages)
                except Exception:
                    pass
            if passages and answer and str(answer).strip():
                try:
                    answer, ungrounded_n = _mark_ungrounded_quotes(
                        str(answer), passages
                    )
                    if ungrounded_n:
                        answer = (
                            str(answer)
                            + "\n\n_⚠ " + str(ungrounded_n)
                            + " quote(s) above could not be verified against the "
                            "provided passages and are marked ⟪…⟫._"
                        )
                except Exception:
                    pass
                try:
                    if os.getenv("MENTAT_CITE_VERIFY"):
                        answer, ungrounded_c = _mark_ungrounded_citations(
                            answer, passages
                        )
                    else:
                        ungrounded_c = 0
                    if ungrounded_c:
                        answer = (
                            str(answer)
                            + "\n\n_⚠ " + str(ungrounded_c)
                            + " citation location(s) could not be verified against "
                            "the provided passages and are marked ⟪…⟫._"
                        )
                except Exception:
                    pass
            if census_block and answer and str(answer).strip():
                try:
                    mismatches = _census_mismatches(str(answer), census_block)
                    if mismatches:
                        answer = (
                            str(answer)
                            + "\n\n_⚠ Census check: "
                            + "; ".join(mismatches[:4])
                            + "._"
                        )
                except Exception:
                    pass
            if answer and str(answer).strip():
                route_low = str(_ROUTE_OVERRIDE or "").lower()
                if route_low in ("deepseek-think", "qwen-deep"):
                    try:
                        revised = await _revise_for_argument(answer, question)
                        if revised and str(revised).strip():
                            answer = revised
                    except Exception:
                        pass
        finally:
            _ROUTE_OVERRIDE = prev_route
        _t("answer")

        refs_own = [
            {"file_path": p.get("file_path"), "reference_id": str(i + 1)}
            for i, p in enumerate(passages or [])
        ]
        context_text = _group_sources_by_book(refs_own)

        entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "question": question,
            "mode": mode,
            "answer": answer,
            "contexts": context_text,
        }
        _append_history(entry)
        try:
            summary = await _summarize_question(question)
            if summary:
                _update_history_summary(entry.get("conv"), entry["timestamp"], question, summary)
        except Exception:
            pass
        entry["status"] = "answered"
        _tok_in = int((usage_snapshot or {}).get("prompt_tokens", 0) or 0)
        _tok_out = int((usage_snapshot or {}).get("completion_tokens", 0) or 0)
        _model_used = served_model or (_ROUTE_OVERRIDE or settings.get("model") or "")
        _flush_ask_telemetry(
            self, question, mode, settings, strategy,
            (_ROUTE_OVERRIDE or settings.get("model") or ""), answer,
            passages, "answered" if str(answer).strip() else "no_answer",
            fast_retry=retried, ungrounded=ungrounded_n,
            docs_count=len(passages), entry=entry, served_model=served_model,
            tokens_in=_tok_in, tokens_out=_tok_out,
            cost_usd=estimate_cost(_model_used, _tok_in, _tok_out),
            route_reason=_ROUTE_REASON,
            kind=_question_kind(question),
        )
        return entry

    async def ask_stream(self, question, mode=None):
        """Answer grounded in the library, streaming tokens via an async generator.

        Yields the accumulated answer text; after completion, the final result is
        available on ``self._last_stream_result``.
        """
        if not _store_ok():
            raise RuntimeError(STORAGE_STALE_MSG)
        self._last_stream_result = None
        _t0 = time.time()
        self._trace = []

        def _t(name):
            self._trace.append((name, round(time.time() - _t0, 2)))

        settings = _load_settings()
        mode = mode or settings["mode"]
        _ensure_conv()
        rag = await self.open()
        _t("open")

        conversation_history = await self._build_conversation_history()
        _t("history")

        lens = (settings.get("lens") or "").strip()
        score = _question_heuristic_score(question)
        interpretive = _is_interpretive(question, score)
        sys_template = _rag_system_prompt(mode, interpretive=interpretive)
        if lens:
            lens_block = lens.replace("{", "{{").replace("}", "}}") + "\n\n"
            sys_template = lens_block + sys_template
        voice_block = VOICE_PRESETS.get(settings.get("voice", "default"), "")
        if voice_block:
            sys_template = voice_block + "\n\n" + sys_template
        # Comprehension FIRST — the classifier's kind (compare/research ->
        # universal evidence, count -> census, quotes -> long windows) must
        # drive the strategy and prompt choices, not only routing.
        try:
            await _expand_query(question)
        except Exception:
            pass
        strategy = _retrieval_strategy(question, score)
        if strategy == "simple":
            strategy = "expand"  # the librarian grounds EVERY question now
        an_kind = str(_analysis(question).get("kind") or "").lower()
        if (
            _has_universal_intent(question)
            or an_kind in ("compare", "research", "argument", "synthesis", "universal")
        ):
            strategy = "universal"
        passages = []
        progress = getattr(self, "_progress", None)

        def _note(msg):
            if progress:
                try:
                    progress(msg)
                except Exception:
                    pass

        _note("searching your library…")
        _set_retrieval_note(_note)
        census_block = ""
        try:
            passages = await _build_passages(rag, question, strategy)
        except Exception as exc:
            _telemetry_log_feedback(
                "retrieval_error", str(exc)[:160], _current_conv_id()
            )
            _note("retrieval hit an error — answering on what is available")
            passages = []
        try:
            census_ctx = _census_ctx(question, strategy)
            if census_ctx.get("keys") and passages:
                allowed = census_ctx["keys"]
                passages = [
                    p for p in passages
                    if _book_key(p.get("file_path", "")) in allowed
                ]
            census_block = census_ctx.get("block") or ""
        except Exception:
            census_block = ""
        try:
            block = _render_passage_block(
                passages,
                full=_has_quote_intent(question)
                or strategy in ("universal", "hunt"),
            )
            if block:
                sys_template = sys_template + block
        except Exception:
            pass
        if census_block:
            sys_template = sys_template + census_block
        if not passages:
            degrade = _retrieval_degraded_note()
            if degrade:
                _telemetry_log_feedback(
                    "retrieval_degraded", degrade[:200], _current_conv_id()
                )
                sys_template = sys_template + (
                    "\n\n[Retrieval warning: the library search degraded ("
                    + degrade
                    + "). The empty evidence is a system failure, not proof the "
                    "library lacks the text. Tell the user retrieval failed and "
                    "to check the index/embedder; never improvise an excuse.]"
                )
        try:
            cov = _evidence_coverage(passages)
        except Exception:
            cov = {"books": 0, "names": [], "chunks": 0}
        note = _coverage_note(cov, an_kind, strategy)
        if note and settings.get("coverage_notes", True):
            _telemetry_log_feedback(
                "coverage_thin",
                f"{cov['books']} book(s) for {an_kind or strategy}: "
                f"{', '.join(cov['names'])[:120]}",
                _current_conv_id(),
            )
            sys_template = sys_template + note
        _t(f"passages({len(passages)})")
        _note(f"found {len(passages)} passages — synthesizing…")
        if strategy == "universal":
            try:
                mp = await _build_library_map()
                map_block = _render_map_block(question, mp)
                if map_block:
                    sys_template = sys_template + map_block
                graph_block = _graph_block(question, passages)
                if graph_block:
                    sys_template = sys_template + graph_block
            except Exception:
                pass
        if _named_sources(question):
            sys_template = sys_template + "\n\n" + NAMED_SOURCE_INSTRUCTION
        doc_chunks = []
        try:
            doc_chunks = _search_conv_docs(_current_conv_id(), question, k=6)
            if doc_chunks:
                sys_template = sys_template + _render_draft_block(doc_chunks) + DRAFT_INSTRUCTION
                _note(f"consulting your drafts ({len(doc_chunks)} chunks)…")
        except Exception:
            doc_chunks = []
        try:
            sys_template = sys_template + _register_instruction(_question_kind(question))
        except Exception:
            pass
        try:
            mem = _memory_matches(question)
            if mem:
                sys_template = sys_template + _render_memory_block(mem)
        except Exception:
            pass
        sys_template = sys_template + _length_budget(question)
        try:
            if _question_kind(question) == "quotes":
                _qdraft = _extract_quote_draft(question, passages)
                if _qdraft:
                    sys_template = sys_template + _qdraft
        except Exception:
            pass
        if _offline():
            sys_template = sys_template + _offline_answer_rules(
                _question_kind(question)
            )
        _t("context")
        refs = [
            {"file_path": p.get("file_path"), "reference_id": str(i + 1)}
            for i, p in enumerate(passages or [])
        ]

        global _ROUTE_OVERRIDE
        prev_route = _ROUTE_OVERRIDE
        retried = False
        used_fallback = False
        ungrounded_n = 0
        try:
            an_kind = str(_analysis(question).get("kind") or "").lower()
            _ROUTE_OVERRIDE = await _route_model(
                question,
                force_deep=(
                    strategy == "universal"
                    or an_kind in ("compare", "research", "argument", "synthesis")
                    or bool(census_block)
                ),
            )
            _t("route")
            used_model = _ROUTE_OVERRIDE or settings.get("model") or ""
            think_start = None
            think_end = None
            content_start = None
            content_end = None
            ui_progress = getattr(self, "_progress", None)

            def _hook(msg):
                nonlocal think_start, think_end
                if isinstance(msg, tuple) and msg[0] == "think":
                    now = time.time()
                    if think_start is None:
                        think_start = now
                    think_end = now
                if ui_progress:
                    try:
                        ui_progress(msg)
                    except Exception:
                        pass

            _set_reasoning_hook(_hook)
            parts = []
            try:
                stream_gen = await query_llm(
                    question,
                    system_prompt=sys_template,
                    history_messages=conversation_history,
                    stream=True,
                **(
                    _offline_gen_kwargs(question)
                    if _offline()
                    else {}
                ),
                )
                async for chunk in stream_gen:
                    if chunk:
                        if content_start is None:
                            content_start = time.time()
                        content_end = time.time()
                        parts.append(chunk)
                        yield "".join(parts)
            except Exception as exc:
                # The stream died mid-flight: fall through to the retry path
                # below (a non-stream call to the fast model, which can itself
                # fall back to local) instead of erroring out.
                _telemetry_log_feedback(
                    "fallback", f"stream: {str(exc)[:160]}", _current_conv_id()
                )
            full = "".join(parts)
            usage_snapshot = dict(_LAST_USAGE or {})
            _set_reasoning_hook(None)
            _t("answer")
            reasoning = _LAST_REASONING
            t_thinking = (think_end - think_start) if think_start else 0.0
            t_content = (content_end - content_start) if content_start else 0.0

            answer = full or ""
            truncated = False
            if answer.strip() and not re.search(r"[.!?\"\u201d\u00bb\)\u2026]$", answer.strip()[-1]):
                # The stream died mid-sentence. Continue with a fast model,
                # seeded from the tail MINUS the broken final word, so the
                # continuation starts clean. Never fail silently.
                truncated = True
                tail = str(answer)
                seed_tail = tail[:-40] if len(tail) > 200 else tail[-600:]
                continue_prompt = (
                    "Continue the following answer EXACTLY where it stopped. "
                    "Do not repeat any of it, do not add a preamble:\n\n"
                    + seed_tail
                )
                prev_route = _ROUTE_OVERRIDE
                attempts = [
                    "qwen" if _offline() else "deepseek-flash",
                    "deepseek-flash" if _offline() else "qwen",
                ]
                cont = ""
                for model_name in attempts:
                    _ROUTE_OVERRIDE = model_name
                    try:
                        cont = await query_llm(
                            continue_prompt,
                            system_prompt=sys_template,
                            history_messages=conversation_history,
                            **({"think": False} if _offline() else {}),
                        )
                    except Exception:
                        cont = ""
                    finally:
                        _ROUTE_OVERRIDE = prev_route
                    if cont and str(cont).strip():
                        break
                if cont and str(cont).strip():
                    answer = str(answer) + str(cont)
                    full = answer
                    truncated = False
                    yield answer
                else:
                    answer = str(answer) + "\n\n_\u2014 [answer was cut off]_"
                    yield answer
            served_model = _LAST_SERVED_MODEL
            if not answer.strip():
                # Stream produced nothing (e.g. reasoning timed out) — retry
                # with a different model. If the deep model reasoned but never
                # wrote, use the non-reasoning chat model; otherwise flash.
                r_first = (_LAST_REASONING or "").strip()
                retried = True
                prev_route = _ROUTE_OVERRIDE
                _ROUTE_OVERRIDE = (
                    "qwen" if _offline() else "deepseek-flash"
                )
                try:
                    answer = await query_llm(
                        question,
                        system_prompt=sys_template,
                        history_messages=conversation_history,
                        **({"think": False} if _offline() else {}),
                    )
                finally:
                    _ROUTE_OVERRIDE = prev_route
                if not (answer and str(answer).strip()):
                    if r_first:
                        answer = (
                            "_The model reasoned but ran out of output budget "
                            "before writing; here is the tail of its reasoning._\n\n"
                            + r_first[-2500:]
                        )
                    else:
                        answer = _no_answer_line()
                        _telemetry_log_feedback("no_answer", question, _current_conv_id())
                    used_fallback = True
                yield answer
            if passages and settings.get("filter_references", True):
                try:
                    answer = _rewrite_references(answer, passages)
                except Exception:
                    pass
            if (
                passages
                and answer
                and str(answer).strip()
                and settings.get("auto_attribution", True)
            ):
                try:
                    answer, attributed = _ensure_quote_attribution(
                        str(answer), passages
                    )
                    if attributed:
                        _telemetry_log_feedback(
                            "quote_attributed",
                            f"{attributed} quote(s) auto-cited",
                            _current_conv_id(),
                        )
                except Exception:
                    pass
            if (
                _offline()
                and passages
                and answer
                and str(answer).strip()
                and os.getenv("MENTAT_REPAIR")
            ):
                try:
                    answer = await _repair_ungrounded(question, answer, passages)
                except Exception:
                    pass
            if passages and answer and str(answer).strip():
                try:
                    answer, ungrounded_n = _mark_ungrounded_quotes(answer, passages)
                    if ungrounded_n:
                        answer = (
                            answer
                            + "\n\n_⚠ " + str(ungrounded_n)
                            + " quote(s) above could not be verified against the "
                            "provided passages and are marked ⟪…⟫._"
                        )
                except Exception:
                    pass
                try:
                    if os.getenv("MENTAT_CITE_VERIFY"):
                        answer, ungrounded_c = _mark_ungrounded_citations(
                            answer, passages
                        )
                    else:
                        ungrounded_c = 0
                    if ungrounded_c:
                        answer = (
                            str(answer)
                            + "\n\n_⚠ " + str(ungrounded_c)
                            + " citation location(s) could not be verified against "
                            "the provided passages and are marked ⟪…⟫._"
                        )
                except Exception:
                    pass
            if census_block and answer and str(answer).strip():
                try:
                    mismatches = _census_mismatches(str(answer), census_block)
                    if mismatches:
                        answer = (
                            str(answer)
                            + "\n\n_⚠ Census check: "
                            + "; ".join(mismatches[:4])
                            + "._"
                        )
                except Exception:
                    pass
            if answer and str(answer).strip():
                route_low = str(used_model or _ROUTE_OVERRIDE or "").lower()
                if route_low in ("deepseek-think", "qwen-deep"):
                    try:
                        revised = await _revise_for_argument(answer, question)
                        if revised and str(revised).strip():
                            answer = revised
                    except Exception:
                        pass
            _t("verify")
            contexts = _group_sources_by_book(refs)
            entry = {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "question": question,
                "mode": mode,
                "answer": answer,
                "contexts": contexts,
                "model": used_model,
            }
            _append_history(entry)
            try:
                summary = await _summarize_question(question)
                if summary:
                    entry["summary"] = summary
                    _update_history_summary(entry.get("conv"), entry["timestamp"], question, summary)
            except Exception:
                pass
            _tok_in = int((usage_snapshot or {}).get("prompt_tokens", 0) or 0)
            _tok_out = int((usage_snapshot or {}).get("completion_tokens", 0) or 0)
            if not _tok_out and answer:
                _tok_out = int(len(answer) / 4)  # stream gave no usage chunk
            self._last_stream_result = {
                "answer": answer,
                "refs": refs,
                "entry": entry,
                "reasoning": reasoning,
                "served_local": "qwen" in str(served_model).lower(),
                "served_model": served_model,
                "t_thinking": round(t_thinking, 1) if t_thinking else 0.0,
                "t_content": round(t_content, 1) if t_content else 0.0,
                "tokens_in": _tok_in,
                "tokens_out": _tok_out,
                "cost_usd": estimate_cost(
                    served_model or used_model, _tok_in, _tok_out
                ),
                "route_reason": _ROUTE_REASON,
                "kind": _question_kind(question),
            }
            _flush_ask_telemetry(
                self, question, mode, settings, strategy, used_model, answer,
                passages,
                "no_answer" if used_fallback else ("answered" if answer.strip() else "no_answer"),
                fast_retry=retried, ungrounded=ungrounded_n,
                docs_count=len(passages), entry=entry, truncated=truncated,
                served_model=served_model, reasoning_len=len(reasoning or ""),
                t_thinking=round(t_thinking, 1) if t_thinking else None,
                t_content=round(t_content, 1) if t_content else None,
                tokens_in=_tok_in, tokens_out=_tok_out,
                cost_usd=estimate_cost(
                    served_model or used_model, _tok_in, _tok_out
                ),
                route_reason=_ROUTE_REASON,
                kind=_question_kind(question),
            )
        finally:
            _ROUTE_OVERRIDE = prev_route
            _set_reasoning_hook(None)
            _set_retrieval_note(None)

    async def chat(self, question, history_messages=None):
        """Natural assistant chat (no index retrieval)."""
        answer = await query_llm(
            question,
            system_prompt=CHAT_SYSTEM_PROMPT,
            history_messages=list(history_messages or []),
        )
        if not (answer and str(answer).strip()):
            r_tail = (_LAST_REASONING or "").strip()
            if r_tail:
                answer = (
                    "_The model reasoned but ran out of output budget before "
                    "writing; here is the tail of its reasoning._\n\n" + r_tail[-2500:]
                )
            else:
                answer = _no_answer_line()
        entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "question": question,
            "answer": answer,
            "mode": "chat",
        }
        _append_history(entry)
        entry["status"] = "answered"
        return entry

    def history(self, limit=20):
        """Turns of the current conversation, most recent last."""
        conv = _current_conv_id()
        if conv:
            return _load_conv(conv)[-limit:]
        out = []
        for row in _load_index()[-3:]:
            out.extend(_load_conv(row.get("conv")))
        return out[-limit:]

    def conversations(self):
        """One summary row per conversation (for the sidebar)."""
        return _conversations()

    def new_conversation(self):
        """Start a fresh conversation; new questions stop continuing the old one."""
        _set_current_conv(_new_conv_id())

    def open_conversation(self, conv_id):
        """Continue an existing conversation (sidebar click)."""
        if _conv_path(conv_id).exists():
            _set_current_conv(conv_id)

    def delete_conversation(self, conv_id):
        """Delete a whole conversation. Returns the number of removed turns."""
        return _delete_conversation(conv_id)

    def delete_history(self, index):
        """Delete one history entry by index (0 = oldest). Returns the removed entry."""
        return _delete_history(index)

    def delete_last_history(self):
        """Delete the most recent history entry."""
        turns = _load_conv(_current_conv_id())
        return _delete_history(len(turns) - 1) if turns else None

    def search(self, phrase, limit=25):
        """Full-text search across every file in the vault (a command+F equivalent).

        Returns exact matches with book/chapter and a surrounding excerpt.
        """
        needle = (phrase or "").lower().strip()
        if not needle:
            return []
        results = []
        for src, text in _search_file_texts():
            low = text.lower()
            start = 0
            while len(results) < limit:
                idx = low.find(needle, start)
                if idx == -1:
                    break
                results.append({"source": src, "excerpt": _excerpt(text, idx)})
                start = idx + len(needle)
            if len(results) >= limit:
                break
        return results

    def library_exact_matches(self, question, limit=4):
        """Best exact verbatim passages in the library matching the question.

        Returns a formatted context block (or ''), for grounding answers in exact text.
        """
        words = [
            w for w in re.findall(r"[A-Za-z]{3,}", question or "")
            if w.lower() not in _SEARCH_STOPWORDS
        ]
        key_words = [w.lower() for w in words]
        best = []
        for phrase in _extract_search_phrases(question):
            needle = phrase.lower()
            hits = self.search(phrase, limit=5)
            fixed = ""
            if not hits:
                for variant in _correct_phrase_variants(phrase):
                    hv = self.search(variant, limit=5)
                    if hv:
                        fixed = variant
                        hits = hv
                        break
            if not hits:
                continue
            rarity_needle = fixed or phrase
            try:
                rarity = len(self.search(rarity_needle, limit=1000))
            except Exception:
                rarity = 0
            for hit in hits:
                ex = hit["excerpt"].lower()
                score = sum(1 for w in key_words if w in ex)
                if needle and needle in ex:
                    score += 100
                if fixed and fixed in ex:
                    score += 100
                if needle and needle in hit["source"].lower():
                    score += 50
                if fixed and fixed in hit["source"].lower():
                    score += 50
                score += max(0, 200 - min(rarity, 200))
                best.append({**hit, "_score": score})
            if len(best) >= 30:
                break
        if not best:
            return ""
        seen, uniq = set(), []
        for h in best:
            k = (h["source"], h["excerpt"])
            if k not in seen:
                seen.add(k)
                uniq.append(h)
        uniq.sort(key=lambda h: (-h["_score"], h["source"]))
        top = uniq[:limit]
        lines = [
            f"[{i + 1}] {h['source']}: {h['excerpt']}"
            for i, h in enumerate(top)
        ]
        return (
            "\n\nExact passages found in your library "
            "(verify quotes and cite these by book + chapter):\n"
            + "\n".join(lines)
        )

    def get_settings(self):
        return _load_settings()

    def set_setting(self, key, value):
        if key not in SETTINGS_DEFAULTS:
            return {
                "ok": False,
                "reason": f"unknown setting '{key}'. Valid: {', '.join(SETTINGS_DEFAULTS)}",
            }
        try:
            coerced = _coerce_setting(key, value)
        except ValueError as exc:
            return {"ok": False, "reason": str(exc)}
        settings = _load_settings()
        settings[key] = coerced
        _save_settings(settings)
        return {"ok": True, "key": key, "value": coerced}

    def lens_from_file(self, name):
        safe = re.sub(r"[^A-Za-z0-9_-]", "-", name).strip("-") or "default"
        lens_path = KNOWLEDGE_ROOT / "lenses" / f"{safe}.md"
        if not lens_path.exists():
            return {"ok": False, "reason": f"no lens file at {lens_path}"}
        text = lens_path.read_text().strip()
        if not text:
            return {"ok": False, "reason": "lens file is empty"}
        settings = _load_settings()
        settings["lens"] = text
        _save_settings(settings)
        return {"ok": True, "name": safe, "chars": len(text)}

    async def remember(self, text, topic="default"):
        topic = re.sub(r"[^A-Za-z0-9_-]", "-", topic).strip("-") or "default"
        mem_dir = KNOWLEDGE_ROOT / "memory"
        mem_dir.mkdir(parents=True, exist_ok=True)
        path = mem_dir / f"{topic}.md"
        if path.exists():
            body = path.read_text()
        else:
            body = f"# Memory: {topic}\n"
        body += f"- {time.strftime('%Y-%m-%d %H:%M')}: {text.strip()}\n"
        path.write_text(body)
        stats = await self.index(verbose=False, only=f"memory/{topic}.md")
        return {"ok": True, "path": str(path), "indexed": stats}

    async def save_url(self, url, title=None):
        from urllib.parse import urlparse

        if not url.lower().startswith(("http://", "https://")):
            return {"ok": False, "reason": "only http(s) URLs can be saved"}
        text = _fetch_url_text(url)
        if not text:
            return {"ok": False, "reason": "no readable text at that URL"}

        if not title:
            parsed = urlparse(url)
            basename = (parsed.path.rstrip("/").split("/")[-1] or "page")
            title = f"{parsed.netloc.replace('www.', '')} - {basename}"[:80]
        slug = re.sub(r"[^A-Za-z0-9_-]", "-", title).strip("-") or "saved-page"

        web_dir = KNOWLEDGE_ROOT / "web"
        web_dir.mkdir(parents=True, exist_ok=True)
        path = web_dir / f"{slug}.md"
        header = f"# {title}\n\nSource: {url}\nSaved: {time.strftime('%Y-%m-%d %H:%M')}\n\n"
        path.write_text(header + text)
        stats = await self.index(verbose=False, only=f"web/{slug}.md")
        return {"ok": True, "path": str(path), "chars": len(text), "indexed": stats}

    async def book_ask(self, work, question, reasoning_effort="high"):
        """Ask a question with a whole work loaded into a 1M-context model.

        Default long-context model is DeepSeek's own (deepseek-v4-pro, 1M
        context, automatic caching) so no Kimi key is required; a "kimi-k3" or
        "moonshot/…" setting routes through Moonshot instead. The text is
        capped so the request fits the window with room for the answer.
        """
        settings = _load_settings()
        model_choice = (
            str(settings.get("long_context_model") or "").strip()
            or DEEPSEEK_THINK_MODEL
        )
        provider, base_url, api_key, wire = resolve_provider(
            resolve_model(model_choice)
        )
        if _offline():
            return {
                "status": "offline",
                "message": (
                    "offline mode is on — whole-book mode needs a remote "
                    "1M-context model. Use /offline (or the setting) to go back online."
                ),
            }
        if not (provider and api_key):
            return {
                "status": "no_key",
                "message": (
                    f"no API key for long_context_model={model_choice!r} — set "
                    "DEEPSEEK_API_KEY (default), OPENROUTER_API_KEY, or "
                    "MOONSHOT_API_KEY in app/.env."
                ),
            }
        matches = _books_matching(work)
        if not matches:
            return {"status": "not_found", "message": f"no indexed work matches {work!r}"}
        book_key = matches[0]
        rels = [rel for rel in _load_manifest() if _title_canon(rel) == book_key]
        rels.sort(key=lambda r: (".epub" not in r, len(r)))
        if not rels:
            return {"status": "not_found", "message": f"{work!r} is not in the manifest"}
        parts = []
        for rel in rels:
            path = KNOWLEDGE_ROOT / rel
            try:
                docs = _staged_texts(path)
                if docs is None:
                    docs = _stage_file(path)
            except Exception:
                docs = None
            for d in docs or []:
                marker = (d.get("marker") or "").strip()
                text = str(d.get("text") or "")
                if text.strip():
                    parts.append(f"\n\n## {marker or '(whole book)'}\n\n{text}")
        body = "".join(parts).strip()
        if not body:
            return {"status": "not_found", "message": f"{work!r} has no extractable text"}
        truncated = len(body) > _WHOLE_BOOK_MAX_CHARS
        if truncated:
            body = body[:_WHOLE_BOOK_MAX_CHARS]
        system = (
            "You are Mentat answering from the COMPLETE text of a work supplied "
            "below. Ground every statement in that text, quote verbatim, and "
            "cite the chapter marker (## …). If the text does not contain the "
            "answer, say so plainly.\n\n<work>\n" + body + "\n</work>"
        )
        try:
            answer = await remote_llm(
                question,
                system_prompt=system,
                model=wire,
                base_url=base_url,
                api_key=api_key,
                provider=provider,
                max_tokens=16000 if provider == "moonshot" else 8000,
                reasoning_effort=reasoning_effort,
                timeout=600,
            )
        except Exception as exc:
            return {"status": "error", "message": f"{type(exc).__name__}: {exc}"}
        return {
            "status": "answered",
            "work": book_key,
            "model": wire,
            "answer": answer,
            "chars": len(body),
            "truncated": truncated,
        }

    async def themes(self):
        mp = await _build_library_map()
        block = _render_map_block(
            "What are the overarching themes, clusters of ideas, and recurring "
            "concepts across this entire library?",
            mp,
        ) or ""
        return await query_llm(
            "What are the overarching themes, clusters of ideas, and recurring "
            "concepts across this entire library? Group related concepts and "
            "name each theme.",
            system_prompt=(
                "You are a librarian. Using ONLY the provided library map, list "
                "the overarching themes, clusters of ideas, and recurring "
                "concepts across the library, grouping related concepts and "
                "naming each theme." + block
            ),
        )

    async def status(self):
        manifest = _load_manifest()
        file_stats = []
        total_bytes = 0
        for rel in sorted(manifest):
            path = KNOWLEDGE_ROOT / rel
            size = path.stat().st_size if path.exists() else 0
            total_bytes += size
            file_stats.append({"path": rel, "size": size})

        new_files, changed_files, removed, _ = self._scan_changes()
        settings = _load_settings()

        info = {
            "documents": len(manifest),
            "total_bytes": total_bytes,
            "knowledge_root": str(KNOWLEDGE_ROOT),
            "storage_dir": str(STORAGE_DIR),
            "extract_model": DEEPSEEK_MODEL if DEEPSEEK_API_KEY else OLLAMA_LLM_MODEL,
            "query_model": model_label(settings.get("model") or ""),
            "embed_model": OLLAMA_EMBED_MODEL,
            "thinking": settings["thinking"],
            "history_turns": settings["history_turns"],
            "mode": settings["mode"],
            "routing": settings.get("routing", "hybrid"),
            "offline": bool(settings.get("offline", False)),
            "temperature": settings["temperature"],
            "lens_active": bool((settings.get("lens") or "").strip()),
            "pending_files": len(new_files) + len(changed_files),
            "files": file_stats,
        }
        try:
            info["chunks"] = _library_db().execute(
                "SELECT count(*) FROM chunks"
            ).fetchone()[0]
        except Exception:
            info["chunks"] = len(_load_chunk_texts())
        return info

    async def forget(self, rel):
        if not _store_ok():
            return {"ok": False, "reason": STORAGE_STALE_MSG}
        manifest = _load_manifest()
        if rel not in manifest:
            return {"ok": False, "reason": "not indexed"}
        for doc_id in (_entry_docs(manifest[rel]) or [_doc_id(rel)]):
            await self._delete_chunks_by_doc(doc_id)
        del manifest[rel]
        _save_manifest(manifest)
        return {"ok": True, "path": rel}
