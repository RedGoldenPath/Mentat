"""Model registry + parameter resolver + usage normalizer.

The single place that knows each model's limits and maps one canonical "job" to
provider-specific parameters — the same role LiteLLM's get_supported_openai_params /
model map, OpenRouter's per-model metadata, and Ollama's options play. Keeps local and
online honest and comparable.
"""
from __future__ import annotations
import json
import math
from functools import lru_cache
from . import config

MODELS_PATH = config.V2_DATA / "models.json"

# job role -> canonical policy
#   reasoning: "off" | "low" | "medium" | "high"
#   max_output: cap for the answer/JSON
#   json: request structured output
JOB_POLICY = {
    "extraction": {"reasoning": "off", "max_output": 1400, "json": True},
    "brief":      {"reasoning": "off", "max_output": 900,  "json": True},
    "plan":       {"reasoning": "off", "max_output": 900,  "json": True},
    "summary":    {"reasoning": "off", "max_output": 200,  "json": False},
    "repair":     {"reasoning": "off", "max_output": 5000, "json": False},
    "writer":     {"reasoning": "off", "max_output": 2200, "json": False},
    "judge":      {"reasoning": "high", "max_output": 1600, "json": True},
    "chat":       {"reasoning": "off", "max_output": 1500, "json": False},
}


@lru_cache(maxsize=1)
def _profiles() -> dict:
    try:
        return json.loads(MODELS_PATH.read_text())
    except Exception:
        return {}


def _infer_provider(model: str) -> dict:
    m = (model or "").lower()
    if "qwen" in m or "llama" in m or ":" in m and "/" not in m:
        return {"provider": "ollama", "wire": "ollama"}
    return {"provider": "deepseek", "wire": "openai_compat"}


def profile_for(model: str) -> dict:
    p = _profiles().get(model)
    if p:
        return p
    base = _infer_provider(model)
    if base["wire"] == "ollama":
        base.update({
            "context": {"max_input": 32768, "max_output": 8192,
                        "default_num_ctx": 32768, "hard_max_num_ctx": 65536},
            "reasoning": {"supported": False, "efforts": [], "default": "off",
                          "response_field": ""},
            "sampling": {"non_thinking": {"temperature": 0.7, "top_p": 0.8,
                                          "top_k": 20, "min_p": 0.0,
                                          "presence_penalty": 1.5, "repeat_penalty": 1.0}},
            "structured": {"json_mode": True, "json_schema": True},
            "cache": {"cached_field": "prompt_eval_cached_count"},
        })
    else:
        base.update({
            "context": {"max_input": 1000000, "max_output": 32768,
                        "default_num_ctx": 0, "hard_max_num_ctx": 0},
            "reasoning": {"supported": True, "efforts": ["low", "high", "max"],
                          "default": "high", "response_field": "reasoning_content"},
            "sampling": {},
            "structured": {"json_mode": True, "json_schema": True},
            "cache": {"cached_field": "prompt_cache_hit_tokens"},
        })
    return base


def _thinking_on(profile: dict, reasoning: str) -> bool:
    r = profile.get("reasoning", {})
    if r.get("mandatory"):          # model thinks regardless of think:false
        return True
    if not r.get("supported"):
        return False
    return reasoning not in ("off", "none", "", None)


def resolve(job: str, model: str, prompt_chars: int = 0, override: dict | None = None) -> dict:
    """Canonical params for (job, model). Gateway maps these to the provider wire."""
    profile = profile_for(model)
    pol = dict(JOB_POLICY.get(job, JOB_POLICY["chat"]))
    pol.update(profile.get("job_overrides", {}).get(job, {}) or {})
    if override:
        pol.update({k: v for k, v in override.items() if v is not None})
    reasoning = pol["reasoning"]
    on = _thinking_on(profile, reasoning)

    sampling_key = "thinking" if on else "non_thinking"
    sampling = dict(profile.get("sampling", {}).get(sampling_key, {}))

    ctx = profile.get("context", {})
    max_output = int(pol["max_output"])
    if ctx.get("max_output"):
        max_output = min(max_output, int(ctx["max_output"]))
    # models that think regardless of `think:false` need room for thinking + answer
    if profile.get("reasoning", {}).get("mandatory"):
        max_output = min(int(ctx.get("max_output") or 81920), max_output + 3000)

    # dynamic context: prompt tokens (~chars/4) + answer, rounded up. No 16k floor —
    # size the KV to the actual need (faster load, less RAM); 8k minimum for safety.
    needed = int(prompt_chars / 4) + max_output + 512
    hard = int(ctx.get("hard_max_num_ctx") or 0)
    if hard:
        base = max(needed, 8192)
        num_ctx = min(hard, ((base + 2047) // 2048) * 2048)
    else:
        num_ctx = 0  # server-side

    effort = reasoning if on else "off"
    # clamp effort to supported values
    efforts = profile.get("reasoning", {}).get("efforts") or []
    if on and efforts and effort not in efforts:
        effort = profile["reasoning"].get("default", efforts[-1])

    return {
        "wire": profile.get("wire", "openai_compat"),
        "thinking": on,
        "effort": effort,
        "sampling": sampling,
        "max_output": max_output,
        "num_ctx": num_ctx,
        "json": bool(pol.get("json")) and bool(profile.get("structured", {}).get("json_schema")),
    }


def _dig(d, path):
    cur = d
    for part in path.split("."):
        if cur is None:
            return None
        cur = cur.get(part) if isinstance(cur, dict) else getattr(cur, part, None)
    return cur


def normalize_usage(model: str, raw: dict) -> dict:
    """Map a provider's usage dict to one shape."""
    u = profile_for(model).get("usage", {})
    def g(key, default=0):
        path = u.get(key)
        v = _dig(raw, path) if path else None
        return int(v) if isinstance(v, (int, float)) else default
    prompt = g("prompt")
    completion = g("completion")
    reasoning = g("reasoning")
    cached = g("cached")
    # Reasoning counts INSIDE completion only on providers that report it as a
    # sub-detail (OpenAI-compatible). Ollama reports eval_count as content only.
    visible = (completion - reasoning
               if (u.get("reasoning") and 0 <= reasoning <= completion) else completion)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "reasoning_tokens": reasoning,
        "cached_prompt_tokens": cached,
        "visible_completion_tokens": visible,
    }
