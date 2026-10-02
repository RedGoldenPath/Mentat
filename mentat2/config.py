"""Typed config for Mentat v2. Small, explicit, no sprawling settings."""
import os
import json
from pathlib import Path

APP = Path(__file__).resolve().parent.parent          # .../app
V1_STORAGE = APP / "storage"
V2_DATA = APP / "mentat2_data"
V2_DATA.mkdir(parents=True, exist_ok=True)


def _load_env():
    p = APP / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and v and k not in os.environ:
            os.environ[k] = v


_load_env()

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
# Offline writer default: the MoE (35B-A3B, ~3B active, MLX/FP4) — best offline latency
# in the P10 benchmark. The dense `qwen3.8:27b-mlx` is the registered fallback.
LOCAL_WRITER = os.getenv("MENTAT2_LOCAL_WRITER", "qwen3.5:35b-a3b-nvfp4")
# Local helper/fast model. Defaults to the SAME model as the writer so that offline
# keeps exactly ONE heavy model resident (RAM: one-at-a-time; no swap churn).
# Override with a smaller model (e.g. qwen2.5:7b) only if you accept two model loads.
OLLAMA_FAST_MODEL = os.getenv("OLLAMA_FAST_MODEL", LOCAL_WRITER)
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
# Keep the local model resident this long after the last use (warm start; Ollama
# unloads on idle). Quality-neutral; removes the cold-load first-query penalty.
LOCAL_KEEP_ALIVE = os.getenv("MENTAT2_KEEP_ALIVE", "30m")
# Multi-token prediction / speculative draft depth (Qwen3.5 MTP). 0 = off. Speculative
# decoding is lossless (same output distribution) — a pure latency lever.
DRAFT_NUM_PREDICT = int(os.getenv("MENTAT2_DRAFT_NUM_PREDICT", "0"))
# Preload the local model when the engine starts (skips the first-query load).
WARMUP = os.getenv("MENTAT2_WARMUP", "1") not in ("0", "false", "no")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_FLASH = os.getenv("MENTAT2_FLASH_MODEL", "deepseek-flash")
DEEPSEEK_PRO = os.getenv("MENTAT2_PRO_MODEL", "deepseek-v4-pro")

RERANKER_MODEL = os.getenv("MENTAT2_RERANKER", "BAAI/bge-reranker-base")
NLI_MODEL = os.getenv("MENTAT2_NLI", "cross-encoder/nli-deberta-v3-base")

V1_SETTINGS = V1_STORAGE / "settings.json"
V2_SETTINGS = V2_DATA / "settings.json"
V2_DB = V2_DATA / "v2.db"
# v2's own contextual retrieval index (Anthropic Contextual Retrieval) — built by
# `mentat2.index`; separate from v2.db so it can be rebuilt/backed up on its own.
CTX_DB = V2_DATA / "ctx.db"

DEFAULTS = {
    "profile": "online",     # online | local
    "writer": "",            # blank = profile default
    "max_rounds": 2,
    "top_k": 6,
    "context_chars": 12000,
    "writer_think": False,
    "history_turns": 8,      # cap on turns fed back (also bounded by history_chars)
    "history_chars": 6000,   # character budget for the conversation window
    "repair": True,
    "repair_think": False,
}


def load_settings():
    s = dict(DEFAULTS)
    try:
        if V2_SETTINGS.exists():
            saved = json.loads(V2_SETTINGS.read_text())
            s.update({k: v for k, v in saved.items() if k in DEFAULTS})
    except Exception:
        pass
    # Honor the v1 app's offline toggle (no model cross-contamination; just a flag).
    try:
        v1 = json.loads(V1_SETTINGS.read_text())
        if v1.get("offline") is True:
            s["profile"] = "local"
    except Exception:
        pass
    # Explicit override for tests: MENTAT2_PROFILE=local|online
    env_p = os.getenv("MENTAT2_PROFILE", "").strip().lower()
    if env_p in ("local", "online"):
        s["profile"] = env_p
    return s


def save_settings(s):
    try:
        V2_SETTINGS.write_text(json.dumps(s, indent=2, ensure_ascii=False))
    except Exception:
        pass
