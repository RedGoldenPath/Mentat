import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mcp.server.mcpserver import MCPServer

from brain_core import Brain, SETTINGS_DEFAULTS

server = MCPServer("secondbrain")
_brain = None
_brain_lock = asyncio.Lock()


async def _get_brain():
    global _brain
    if _brain is None:
        _brain = Brain()
        await _brain.open()
    return _brain


@server.tool(
    name="index_knowledge",
    title="Index the knowledge folder",
    description=(
        "Scan the second-brain knowledge folder for new or changed files and "
        "incrementally add them to the knowledge graph. Use this for large "
        "additions such as books (indexing many files can take a while)."
    ),
)
async def index_knowledge(only: str = "") -> str:
    brain = await _get_brain()
    async with _brain_lock:
        stats = await brain.index(verbose=False, only=only or None)
    return json.dumps(stats, indent=2)


@server.tool(
    name="ask_brain",
    title="Reason across indexed texts",
    description=(
        "Ask a question that is answered using the knowledge graph built from the "
        "indexed books. Small new files are auto-indexed first. If many files are "
        "not indexed yet, returns a 'needs_index' message instead of silently "
        "starting a long build; in that case run index_knowledge first. Returns a "
        "grounded draft answer plus the retrieved graph evidence (entities, "
        "relationships, supporting passages)."
    ),
)
async def ask_brain(question: str, mode: str = "") -> str:
    if mode not in ("naive", "local", "global", "hybrid", "mix"):
        mode = ""
    brain = await _get_brain()
    async with _brain_lock:
        result = await brain.ask(question, mode=mode or None)
    if result.get("status") == "needs_index":
        return json.dumps(result, indent=2, ensure_ascii=False)
    payload = {
        "status": "answered",
        "question": result["question"],
        "mode": result["mode"],
        "draft_answer": result["answer"],
        "evidence": result["contexts"],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


@server.tool(
    name="brain_settings",
    title="View or change brain settings",
    description=(
        "View or change settings. To view: call with no arguments. To change: set "
        "set_key and set_value. Valid keys: thinking (false/true/low/medium/high), "
        "history_turns (int), mode (naive/local/global/hybrid/mix), model "
        "(deepseek-chat=default / deepseek-think / qwen=offline / any model name), "
        "temperature (0-2 or none), top_k (int), chunk_top_k (int), lens (free text "
        "framing injected into every answer)."
    ),
)
async def brain_settings(set_key: str = "", set_value: str = "") -> str:
    brain = await _get_brain()
    if set_key:
        result = brain.set_setting(set_key, set_value)
        return json.dumps(result, indent=2, ensure_ascii=False)
    settings = brain.get_settings()
    settings["valid_keys"] = list(SETTINGS_DEFAULTS)
    return json.dumps(settings, indent=2, ensure_ascii=False)


@server.tool(
    name="remember",
    title="Permanently remember a fact",
    description=(
        "Append a fact to the brain's permanent memory (stored as a note in the "
        "knowledge vault and indexed into the graph, so future answers can use it). "
        "topic groups memories into separate notes."
    ),
)
async def remember(text: str, topic: str = "default") -> str:
    brain = await _get_brain()
    async with _brain_lock:
        result = await brain.remember(text, topic=topic)
    return json.dumps(result, indent=2, ensure_ascii=False)


@server.tool(
    name="save_url",
    title="Save a web page into the knowledge vault",
    description=(
        "Fetch a web page by URL, extract its text, save it as a note in the "
        "vault, and index it so future answers can use it. Returns the saved "
        "file path and index stats."
    ),
)
async def save_url(url: str, title: str = "") -> str:
    brain = await _get_brain()
    async with _brain_lock:
        result = await brain.save_url(url, title=title or None)
    return json.dumps(result, indent=2, ensure_ascii=False)


@server.tool(
    name="brain_themes",
    title="Overview of themes across the library",
    description=(
        "Ask the brain for the overarching themes, clusters of ideas, and "
        "recurring concepts across the whole indexed library. Useful for a "
        "high-level map before diving into specific questions."
    ),
)
async def brain_themes() -> str:
    brain = await _get_brain()
    async with _brain_lock:
        themes = await brain.themes()
    return themes


@server.tool(
    name="index_status",
    title="Show indexing status",
    description=(
        "Report whether an index run is currently in progress, its progress "
        "(current chunk, files indexed this run), how many files are pending, "
        "and what is already indexed. Use this to check on background indexing."
    ),
)
async def index_status() -> str:
    from brain import _index_status

    return json.dumps(_index_status(), indent=2, ensure_ascii=False)


@server.tool(
    name="brain_history",
    title="Show conversation history",
    description="Return the most recent past questions and answers from the second brain, newest last. Optionally set a limit (default 10).",
)
async def brain_history(limit: int = 10) -> str:
    brain = await _get_brain()
    entries = brain.history(limit=limit)
    return json.dumps(entries, indent=2, ensure_ascii=False)


@server.tool(
    name="brain_status",
    title="Show index status",
    description="Show what is currently indexed, how many documents/entities/relationships/chunks exist, pending files, and which models and settings are configured.",
)
async def brain_status() -> str:
    brain = await _get_brain()
    async with _brain_lock:
        info = await brain.status()
    return json.dumps(info, indent=2, ensure_ascii=False)


@server.tool(
    name="delete_document",
    title="Remove a document from the index",
    description="Remove a single file from the knowledge graph by its relative path inside the knowledge folder (e.g. 'books/Dune/Dune.epub').",
)
async def delete_document(path: str) -> str:
    brain = await _get_brain()
    async with _brain_lock:
        result = await brain.forget(path)
    return json.dumps(result, indent=2, ensure_ascii=False)


def main():
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
