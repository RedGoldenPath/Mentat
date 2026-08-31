import asyncio
import hashlib
import html
import json
import logging
import os
import re
import sys
import threading
import time
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent
STORAGE_DIR = PROJECT_ROOT / "storage"
MANIFEST_PATH = STORAGE_DIR / "manifest.json"
HISTORY_PATH = STORAGE_DIR / "history.json"
SETTINGS_PATH = STORAGE_DIR / "settings.json"
KNOWLEDGE_ROOT = Path(
    os.getenv("SECONDBRAIN_ROOT", str(Path.home() / "Everything" / "second brain"))
).expanduser()

AUTO_INDEX_MAX_FILES = int(os.getenv("AUTO_INDEX_MAX_FILES", "8"))
AUTO_INDEX_MAX_BYTES = int(os.getenv("AUTO_INDEX_MAX_BYTES", str(2 * 1024 * 1024)))

os.environ.setdefault("CHUNK_F_SIZE", "1200")
os.environ.setdefault("CHUNK_F_OVERLAP_SIZE", "200")

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_LLM_MODEL = os.getenv("OLLAMA_LLM_MODEL", "qwen3.8:27b")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
EMBED_DIM = int(os.getenv("EMBED_DIM", "768"))

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

CHUNK_TOKEN_SIZE = int(os.getenv("CHUNK_TOKEN_SIZE", "1200"))
CHUNK_OVERLAP_TOKEN_SIZE = int(os.getenv("CHUNK_OVERLAP_TOKEN_SIZE", "200"))

SKIP_SUFFIXES = {".ds_store", ".ini", ".cfg", ".json", ".db", ".sqlite", ".sqlite3", ".parquet", ".txt~"}

SETTINGS_DEFAULTS = {
    "thinking": "false",
    "history_turns": 6,
    "mode": "mix",
    "model": "deepseek-chat",
    "temperature": None,
    "top_k": 40,
    "chunk_top_k": 10,
    "lens": "",
}

VALID_MODES = ("naive", "local", "global", "hybrid", "mix")
VALID_THINKING = ("false", "true", "low", "medium", "high")


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

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

DEEPSEEK_FLASH_MODEL = "deepseek-v4-flash"
DEEPSEEK_THINK_MODEL = "deepseek-v4-pro"

MODEL_PRESETS = {
    "qwen": OLLAMA_LLM_MODEL,
    "deepseek-flash": DEEPSEEK_FLASH_MODEL,
    "deepseek-think": DEEPSEEK_THINK_MODEL,
}


def resolve_model(model_setting):
    if model_setting:
        key = str(model_setting).strip()
        return MODEL_PRESETS.get(key, key)
    return ""


def model_label(model_setting):
    key = (model_setting or "").strip()
    if key in ("deepseek-chat", "deepseek"):
        return "deepseek chat"
    if key in ("deepseek-flash",):
        return "deepseek flash"
    if key in ("deepseek-think",):
        return "deepseek think"
    if key in ("qwen", "") or not key:
        return "qwen (local)"
    resolved = resolve_model(key)
    if resolved.startswith("deepseek"):
        return f"deepseek ({resolved})"
    return f"{resolved} (local)"


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
    if key in ("top_k", "chunk_top_k"):
        n = int(value)
        if n < 1:
            raise ValueError(f"{key} must be >= 1")
        return n
    if key == "lens":
        return str(value)
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


def quiet_lightrag():
    import lightrag.utils as _lr_utils  # ensure the lightrag logger + handler exist

    logger = logging.getLogger("lightrag")
    if _progress_log_handler not in logger.handlers:
        logger.addHandler(_progress_log_handler)
    for handler in list(logger.handlers):
        if handler is not _progress_log_handler:
            try:
                handler.setLevel(logging.WARNING)
            except Exception:
                pass
    for name in (
        "nano-vectordb",
        "httpx",
        "httpcore",
        "openai",
        "openai._base_client",
        "uvicorn",
        "asyncio",
    ):
        try:
            logging.getLogger(name).setLevel(logging.WARNING)
        except Exception:
            pass
    logging.getLogger().setLevel(logging.WARNING)


quiet_lightrag()

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


async def deepseek_llm(prompt, system_prompt=None, history_messages=None, model=None, **kwargs):
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        base_url=DEEPSEEK_BASE_URL, api_key=DEEPSEEK_API_KEY, timeout=300
    )
    try:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        for message in history_messages or []:
            messages.append(message)
        messages.append({"role": "user", "content": prompt})
        params = {"model": model or DEEPSEEK_MODEL, "messages": messages}
        if kwargs.get("response_format") is not None:
            params["response_format"] = kwargs["response_format"]
        if kwargs.get("max_tokens"):
            params["max_tokens"] = kwargs["max_tokens"]
        if kwargs.get("temperature") is not None:
            params["temperature"] = kwargs["temperature"]
        response = await client.chat.completions.create(**params)
        return response.choices[0].message.content
    finally:
        await client.close()


async def ollama_llm(prompt, system_prompt=None, history_messages=None, local_model=None, **kwargs):
    from lightrag.llm.ollama import ollama_model_complete

    settings = _load_settings()
    if "enable_cot" in kwargs:
        kwargs["think"] = settings["thinking"]
        temperature = settings.get("temperature")
        if temperature is not None:
            options = dict(kwargs.get("options") or {})
            options["temperature"] = float(temperature)
            kwargs["options"] = options
    hashing_kv = kwargs.get("hashing_kv")
    if hashing_kv is not None:
        try:
            hashing_kv.global_config["llm_model_name"] = (
                local_model or resolve_model(settings.get("model") or "") or OLLAMA_LLM_MODEL
            )
        except Exception:
            pass
    return await ollama_model_complete(
        prompt,
        system_prompt=system_prompt,
        history_messages=history_messages or [],
        **kwargs,
    )


async def keyword_llm(prompt, system_prompt=None, history_messages=None, **kwargs):
    return await ollama_llm(
        prompt,
        system_prompt=system_prompt,
        history_messages=history_messages,
        local_model=OLLAMA_LLM_MODEL,
        **kwargs,
    )


async def query_llm(prompt, system_prompt=None, history_messages=None, **kwargs):
    settings = _load_settings()
    chosen = resolve_model(settings.get("model") or "")
    if chosen and chosen.startswith("deepseek") and DEEPSEEK_API_KEY:
        try:
            return await deepseek_llm(
                prompt,
                system_prompt=system_prompt,
                history_messages=history_messages,
                model=chosen,
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


async def nomic_embed(texts, context="document", **kwargs):
    import ollama

    prefixes = {"document": "search_document: ", "query": "search_query: "}
    prefix = prefixes.get(context)
    if prefix:
        texts = [prefix + text for text in texts]
    client = ollama.AsyncClient(host=OLLAMA_HOST, timeout=60)
    try:
        data = await client.embed(model=OLLAMA_EMBED_MODEL, input=texts)
        return np.array(data["embeddings"])
    finally:
        await client._client.aclose()


def _extract_txt(path):
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return Path(path).read_text(encoding=encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return Path(path).read_text(errors="ignore")


def _extract_pdf(path):
    import pymupdf

    doc = pymupdf.open(str(path))
    try:
        parts = []
        for index, page in enumerate(doc, start=1):
            text = page.get_text().strip()
            if text:
                parts.append(f"## Page {index}\n\n{text}")
        return "\n\n".join(parts)
    finally:
        doc.close()


def _strip_html(text):
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def _extract_epub(path):
    import ebooklib
    from ebooklib import epub

    book = epub.read_epub(str(path))
    parts = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        content = item.get_body_content().decode("utf-8", errors="ignore")
        text = _strip_html(content)
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def _extract_epub_chapters(path):
    import ebooklib
    from ebooklib import epub

    book = epub.read_epub(str(path))
    chapters = []
    seq = 0
    for item_id in book.spine:
        item = book.get_item_with_id(item_id[0])
        if item is None:
            continue
        name = item.get_name()
        content = (item.get_body_content() or b"").decode("utf-8", errors="ignore")
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
        url, headers={"User-Agent": "Mozilla/5.0 (SecondBrain RAG)"}
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
    for path in sorted(KNOWLEDGE_ROOT.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(KNOWLEDGE_ROOT).parts
        if any(part.startswith(".") for part in rel_parts):
            continue
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
    from lightrag.utils import compute_mdhash_id

    return compute_mdhash_id(str(KNOWLEDGE_ROOT / rel_path), prefix="doc-")


def _chapter_doc_id(rel_path, suffix):
    from lightrag.utils import compute_mdhash_id

    return compute_mdhash_id(str(KNOWLEDGE_ROOT / rel_path) + "::" + suffix, prefix="doc-")


def _entry_hash(entry):
    if isinstance(entry, dict):
        return entry.get("hash", "")
    return entry


def _entry_docs(entry):
    if isinstance(entry, dict):
        return entry.get("docs", [])
    return []


def _chapter_display(rel_path, marker):
    return f"{rel_path} · {marker}"


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


def _load_history():
    if HISTORY_PATH.exists():
        try:
            return json.loads(HISTORY_PATH.read_text())
        except Exception:
            return []
    return []


def _append_history(entry):
    history = _load_history()
    history.append(entry)
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(json.dumps(history, indent=2, ensure_ascii=False))


class Brain:
    def __init__(self):
        self._rag = None
        self._lock = asyncio.Lock()

    def _build_rag(self):
        from lightrag.lightrag import EmbeddingFunc, LightRAG
        from lightrag.llm_roles import RoleLLMConfig

        STORAGE_DIR.mkdir(parents=True, exist_ok=True)

        extract_func = deepseek_llm if DEEPSEEK_API_KEY else ollama_llm
        role_configs = {
            "extract": RoleLLMConfig(func=extract_func, max_async=8, timeout=600),
            "keyword": RoleLLMConfig(func=keyword_llm, max_async=4),
            "query": RoleLLMConfig(func=query_llm, max_async=4, timeout=600),
        }

        return LightRAG(
            working_dir=str(STORAGE_DIR),
            llm_model_func=ollama_llm,
            llm_model_name=OLLAMA_LLM_MODEL,
            role_llm_configs=role_configs,
            embedding_func=EmbeddingFunc(
                embedding_dim=EMBED_DIM,
                max_token_size=8192,
                func=nomic_embed,
                model_name=OLLAMA_EMBED_MODEL,
                supports_asymmetric=True,
            ),
            chunk_token_size=CHUNK_TOKEN_SIZE,
            chunk_overlap_token_size=CHUNK_OVERLAP_TOKEN_SIZE,
            max_parallel_insert=3,
            entity_extraction_use_json=True,
            enable_llm_cache=True,
        )

    async def open(self):
        if self._rag is None:
            quiet_lightrag()
            self._rag = self._build_rag()
            await self._rag.initialize_storages()
            quiet_lightrag()
        return self._rag

    async def close(self):
        if self._rag is not None:
            try:
                await self._rag.finalize_storages()
            finally:
                self._rag = None

    def _scan_changes(self, only=None):
        manifest = _load_manifest()
        current = {}
        new_files = []
        changed_files = []
        for path in _iter_knowledge_files():
            rel = str(path.relative_to(KNOWLEDGE_ROOT))
            if only and not rel.startswith(only):
                continue
            digest = _file_hash(path)
            current[rel] = digest
            if rel not in manifest:
                new_files.append(path)
            elif _entry_hash(manifest[rel]) != digest:
                changed_files.append(path)
        removed = [rel for rel in manifest if rel not in current]
        if only:
            removed = [rel for rel in removed if rel.startswith(only)]
        return new_files, changed_files, removed, current

    async def _insert_document(self, rag, path, rel):
        suffix = Path(path).suffix.lower()
        if suffix == ".epub":
            chapters = _extract_epub_chapters(path)
            if not chapters:
                raise ValueError("epub produced no chapters")
            doc_ids = []
            for chapter in chapters:
                doc_id = _chapter_doc_id(rel, chapter["suffix"])
                await rag.ainsert(
                    chapter["text"],
                    ids=[doc_id],
                    file_paths=[_chapter_display(rel, chapter["marker"])],
                )
                doc_ids.append(doc_id)
            return doc_ids
        text = extract_text(path)
        if not text.strip():
            raise ValueError("file produced no extractable text")
        doc_id = _doc_id(rel)
        await rag.ainsert(text, ids=[doc_id], file_paths=[str(path)])
        return [doc_id]

    async def index(self, verbose=False, only=None):
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
        total_bytes = sum(_file_size(p) for p in work)
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
                        await rag.adelete_by_doc_id(doc_id)
                    del manifest[rel]
                    stats["deleted"] += 1
                except Exception as exc:
                    stats["errors"].append(f"{rel}: {exc}")

            for path in changed_files:
                rel = str(path.relative_to(KNOWLEDGE_ROOT))
                try:
                    for doc_id in (_entry_docs(manifest.get(rel)) or [_doc_id(rel)]):
                        await rag.adelete_by_doc_id(doc_id)
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
        return stats

    async def ask(self, question, mode=None, lazy=True):
        settings = _load_settings()
        mode = mode or settings["mode"]

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
        from lightrag.lightrag import QueryParam

        history = _load_history()
        conversation_history = []
        for entry in history[-settings["history_turns"]:]:
            conversation_history.append({"role": "user", "content": entry["question"]})
            conversation_history.append({"role": "assistant", "content": entry["answer"]})

        top_k = settings["top_k"]
        chunk_top_k = settings["chunk_top_k"]

        evidence_param = QueryParam(
            mode=mode,
            only_need_context=True,
            enable_rerank=False,
            top_k=top_k,
            chunk_top_k=chunk_top_k,
        )
        contexts = await rag.aquery(question, param=evidence_param)

        lens = (settings.get("lens") or "").strip()
        sys_template = None
        cache_disabled = False
        if lens:
            from lightrag.prompt import PROMPTS

            lens_block = lens.replace("{", "{{").replace("}", "}}") + "\n\n"
            sys_template = lens_block + PROMPTS["rag_response"]
            try:
                rag.llm_response_cache.global_config["enable_llm_cache"] = False
                cache_disabled = True
            except Exception:
                cache_disabled = False

        answer_param = QueryParam(
            mode=mode,
            enable_rerank=False,
            include_references=True,
            conversation_history=conversation_history,
        )
        try:
            answer = await rag.aquery(question, param=answer_param, system_prompt=sys_template)
        finally:
            if cache_disabled:
                try:
                    rag.llm_response_cache.global_config["enable_llm_cache"] = True
                except Exception:
                    pass

        if not (answer and str(answer).strip()):
            retry_param = QueryParam(
                mode=mode,
                enable_rerank=False,
                include_references=True,
                conversation_history=conversation_history,
                top_k=24,
                chunk_top_k=6,
            )
            answer = await rag.aquery(question, param=retry_param, system_prompt=sys_template)

        if isinstance(contexts, str):
            context_text = contexts
        else:
            context_text = "\n\n".join(str(c) for c in contexts)

        entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "question": question,
            "mode": mode,
            "answer": answer,
            "contexts": context_text,
        }
        _append_history(entry)
        entry["status"] = "answered"
        return entry

    def history(self, limit=20):
        return _load_history()[-limit:]

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

    async def themes(self):
        rag = await self.open()
        from lightrag.lightrag import QueryParam

        param = QueryParam(
            mode="global",
            enable_rerank=False,
            response_type="Multiple Paragraphs",
        )
        return await rag.aquery(
            "What are the overarching themes, clusters of ideas, and recurring "
            "concepts across this entire library? Group related concepts and "
            "name each theme.",
            param=param,
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
            "temperature": settings["temperature"],
            "lens_active": bool((settings.get("lens") or "").strip()),
            "pending_files": len(new_files) + len(changed_files),
            "files": file_stats,
        }
        rag = await self.open()
        try:
            nodes = await rag.chunk_entity_relation_graph.get_all_nodes()
            edges = await rag.chunk_entity_relation_graph.get_all_edges()
            info["entities"] = len(nodes)
            info["relationships"] = len(edges)
            chunks_path = STORAGE_DIR / "kv_store_text_chunks.json"
            if chunks_path.exists():
                try:
                    info["chunks"] = len(json.loads(chunks_path.read_text()))
                except Exception:
                    info["chunks"] = 0
        except Exception:
            pass
        return info

    async def forget(self, rel):
        manifest = _load_manifest()
        if rel not in manifest:
            return {"ok": False, "reason": "not indexed"}
        rag = await self.open()
        for doc_id in (_entry_docs(manifest[rel]) or [_doc_id(rel)]):
            await rag.adelete_by_doc_id(doc_id)
        del manifest[rel]
        _save_manifest(manifest)
        return {"ok": True, "path": rel}
