"""The ONLY place models are called. Two profiles (online|local). No silent fallbacks."""
from __future__ import annotations
import time
import numpy as np
from . import config, registry

_USAGE: list = []            # [{model, profile, seconds, tokens_in, tokens_out, chars}]
_OLLAMA = None
_OPENAI = None
_RERANKER = None
_NLI = None


class GatewayError(RuntimeError):
    pass


def take_usage():
    global _USAGE
    u, _USAGE = _USAGE, []
    return u


def _ollama():
    global _OLLAMA
    if _OLLAMA is None:
        import ollama
        _OLLAMA = ollama.Client(host=config.OLLAMA_HOST)
    return _OLLAMA


def _openai():
    global _OPENAI
    if _OPENAI is None:
        from openai import OpenAI
        if not config.DEEPSEEK_API_KEY:
            raise GatewayError("online profile requested but DEEPSEEK_API_KEY is missing")
        _OPENAI = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL, timeout=120.0, max_retries=1)
    return _OPENAI


def default_writer(profile: str) -> str:
    if profile == "local":
        return config.LOCAL_WRITER
    return config.DEEPSEEK_FLASH


def default_fast(profile: str) -> str:
    if profile == "local":
        return config.OLLAMA_FAST_MODEL
    return config.DEEPSEEK_FLASH


def chat(prompt: str, system: str = "", profile: str = "online", model: str = "",
         job: str = "chat", max_tokens=None, temperature=None, think=None,
         num_ctx=None, json_schema=None, keep_alive: str = None) -> str:
    """``json_schema`` may be a JSON-schema dict (Ollama structured output) or a bool
    (JSON mode). DeepSeek is OpenAI-compatible and supports only ``json_object``."""
    keep_alive = keep_alive or config.LOCAL_KEEP_ALIVE
    """Canonical call. Params resolved from the model registry by ``job`` role."""
    model = model or default_writer(profile)
    prompt_chars = len(prompt or "") + len(system or "")
    override = {}
    if max_tokens is not None:
        override["max_output"] = int(max_tokens)
    if think is False:
        override["reasoning"] = "off"
    elif think is True:
        override["reasoning"] = "high"
    params = registry.resolve(job, model, prompt_chars=prompt_chars,
                              override=override or None)
    if num_ctx:
        params["num_ctx"] = int(num_ctx)
    sampling = dict(params["sampling"])
    if temperature is not None:
        sampling["temperature"] = temperature

    msgs = ([{"role": "system", "content": system}] if system else []) + \
           [{"role": "user", "content": prompt}]
    t0 = time.time()
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "reasoning_tokens": 0,
             "cached_prompt_tokens": 0, "visible_completion_tokens": 0}
    reasoning_text = ""

    if params["wire"] == "ollama":
        opts = dict(sampling)
        opts["num_predict"] = params["max_output"]
        if params["num_ctx"]:
            opts["num_ctx"] = params["num_ctx"]
        if isinstance(json_schema, dict):
            opts["format"] = json_schema          # Ollama structured outputs (schema)
        elif json_schema or params["json"]:
            opts["format"] = "json"
        if config.DRAFT_NUM_PREDICT:
            opts["draft_num_predict"] = config.DRAFT_NUM_PREDICT   # MTP / spec decode (lossless)
        think_val = params["effort"] if (
            params["thinking"] and params["effort"] in ("low", "medium", "high")
        ) else bool(params["thinking"])
        txt, reasoning_text, r = "", "", None
        for attempt in (1, 2):
            try:
                r = _ollama().chat(model=model, messages=msgs, options=opts,
                                   think=think_val, keep_alive=keep_alive)
            except TypeError:
                r = _ollama().chat(model=model, messages=msgs, options=opts)
            msg = _attr(r, "message")
            txt = _attr(msg, "content") or ""
            reasoning_text = _attr(msg, "thinking") or ""
            if txt.strip():
                break
            # reasoning ate the budget: give it more room and retry once
            if reasoning_text and attempt == 1:
                opts = dict(opts)
                opts["num_predict"] = min(int(params["max_output"]) * 2 + 1500, 16000)
                continue
            break
        raw_usage = {k: _attr(r, k) for k in
                     ("prompt_eval_count", "eval_count", "prompt_eval_cached_count")}
        usage = registry.normalize_usage(model, raw_usage)
        for k, dst in (("load_duration", "load_ms"), ("prompt_eval_duration", "prefill_ms"),
                       ("eval_duration", "decode_ms"), ("total_duration", "total_ms")):
            v = _attr(r, k)                        # Ollama reports nanoseconds
            usage[dst] = round(v / 1e6, 1) if isinstance(v, (int, float)) else 0
        if reasoning_text and not usage["reasoning_tokens"]:
            usage["reasoning_tokens"] = int(len(reasoning_text.split()) / 0.75)
    else:
        extra = {}
        if params["thinking"]:
            extra["thinking"] = {"type": "enabled"}
            if params["effort"] in ("low", "high", "max"):
                extra["reasoning_effort"] = params["effort"]
        else:
            extra["thinking"] = {"type": "disabled"}
        if params["json"]:
            # DeepSeek/OpenAI-compatible JSON mode (json_object; not full json_schema)
            extra["response_format"] = {"type": "json_object"}
        mt = int(params["max_output"] or 4000)
        txt = ""
        for attempt in (1, 2):
            try:
                r = _openai().chat.completions.create(
                    model=model, messages=msgs, max_tokens=mt,
                    temperature=sampling.get("temperature", 0.7),
                    extra_body=extra)
            except Exception as exc:
                raise GatewayError(f"online chat failed ({model}): {exc}") from exc
            msg = r.choices[0].message
            txt = msg.content or ""
            reasoning_text = getattr(msg, "reasoning_content", None) or ""
            usage = registry.normalize_usage(model, r.usage)
            if txt.strip():
                break
            if reasoning_text and attempt == 1:
                mt = min(32000, mt * 2 + 2000)
                continue
            break

    _USAGE.append({"model": model, "profile": profile, "job": job,
                   "seconds": round(time.time() - t0, 2), "chars": len(txt or ""),
                   **usage})
    return txt or ""


def _attr(o, key):
    if isinstance(o, dict):
        return o.get(key)
    return getattr(o, key, None)


def chat_stream(prompt: str, system: str = "", profile: str = "online", model: str = "",
                job: str = "writer", max_tokens=None, temperature=None, think=None,
                num_ctx=None, keep_alive: str = None):
    """Yield the visible content tokens of a chat call. Usage is appended to _USAGE
    when the generator is exhausted (call ``take_usage()`` afterwards).

    Streaming is used only by the writer (the long pole) to cut perceived latency.
    """
    keep_alive = keep_alive or config.LOCAL_KEEP_ALIVE
    model = model or default_writer(profile)
    prompt_chars = len(prompt or "") + len(system or "")
    override = {}
    if max_tokens is not None:
        override["max_output"] = int(max_tokens)
    if think is False:
        override["reasoning"] = "off"
    elif think is True:
        override["reasoning"] = "high"
    params = registry.resolve(job, model, prompt_chars=prompt_chars, override=override or None)
    if num_ctx:
        params["num_ctx"] = int(num_ctx)
    sampling = dict(params["sampling"])
    if temperature is not None:
        sampling["temperature"] = temperature
    msgs = ([{"role": "system", "content": system}] if system else []) + \
           [{"role": "user", "content": prompt}]
    t0 = time.time()

    if params["wire"] == "ollama":
        opts = dict(sampling)
        opts["num_predict"] = params["max_output"]
        if params["num_ctx"]:
            opts["num_ctx"] = params["num_ctx"]
        if config.DRAFT_NUM_PREDICT:
            opts["draft_num_predict"] = config.DRAFT_NUM_PREDICT
        think_val = params["effort"] if (
            params["thinking"] and params["effort"] in ("low", "medium", "high")
        ) else bool(params["thinking"])
        try:
            stream = _ollama().chat(model=model, messages=msgs, options=opts,
                                    think=think_val, keep_alive=keep_alive, stream=True)
        except TypeError:
            stream = _ollama().chat(model=model, messages=msgs, options=opts, stream=True)
        last = None
        for part in stream:
            last = part
            c = _attr(_attr(part, "message"), "content")
            if c:
                yield c
        raw_usage = {k: _attr(last, k) for k in
                     ("prompt_eval_count", "eval_count", "prompt_eval_cached_count")}
        usage = registry.normalize_usage(model, raw_usage)
        for k, dst in (("load_duration", "load_ms"), ("prompt_eval_duration", "prefill_ms"),
                       ("eval_duration", "decode_ms"), ("total_duration", "total_ms")):
            v = _attr(last, k)
            usage[dst] = round(v / 1e6, 1) if isinstance(v, (int, float)) else 0
    else:
        extra = {}
        if params["thinking"]:
            extra["thinking"] = {"type": "enabled"}
            if params["effort"] in ("low", "high", "max"):
                extra["reasoning_effort"] = params["effort"]
        else:
            extra["thinking"] = {"type": "disabled"}
        if params["json"]:
            extra["response_format"] = {"type": "json_object"}
        mt = int(params["max_output"] or 4000)
        try:
            stream = _openai().chat.completions.create(
                model=model, messages=msgs, max_tokens=mt,
                temperature=sampling.get("temperature", 0.7),
                extra_body=extra, stream=True,
                stream_options={"include_usage": True})
        except Exception as exc:
            raise GatewayError(f"online stream failed ({model}): {exc}") from exc
        usage = None
        for part in stream:
            if getattr(part, "usage", None):
                usage = registry.normalize_usage(model, part.usage)
            if not part.choices:
                continue
            d = part.choices[0].delta
            c = getattr(d, "content", None)
            if c:
                yield c
        if usage is None:
            usage = {"prompt_tokens": 0, "completion_tokens": 0, "reasoning_tokens": 0,
                     "cached_prompt_tokens": 0, "visible_completion_tokens": 0}
    _USAGE.append({"model": model, "profile": profile, "job": job,
                   "seconds": round(time.time() - t0, 2), "chars": 0, **usage})


def embed(texts, profile: str = "local"):
    """Embeddings are always local (Ollama nomic-embed-text)."""
    if isinstance(texts, str):
        texts = [texts]
    texts = list(texts)
    c = _ollama()
    try:
        r = c.embed(model=config.OLLAMA_EMBED_MODEL, input=texts)
        embs = _attr(r, "embeddings")
        if embs:
            return np.asarray(embs, dtype=np.float32)
    except Exception:
        pass
    out = []
    for t in texts:
        r = c.embeddings(model=config.OLLAMA_EMBED_MODEL, prompt=t)
        out.append(np.asarray(_attr(r, "embedding"), dtype=np.float32))
    return np.vstack(out)


def rerank(query: str, docs: list[str]) -> list[float]:
    global _RERANKER
    if _RERANKER is None:
        from sentence_transformers import CrossEncoder
        _RERANKER = CrossEncoder(config.RERANKER_MODEL)
    scores = _RERANKER.predict([[query, d] for d in docs])
    return [float(s) for s in scores]


def nli(premise: str, hypothesis: str) -> tuple[str, float]:
    """Single-pair convenience wrapper over nli_batch."""
    return nli_batch([(premise, hypothesis)])[0]


def nli_batch(pairs: list) -> list:
    """Return [(label, confidence), ...] for [(premise, hypothesis), ...] in ONE batched
    cross-encoder pass. Labels: contradiction|entailment|neutral. Batching is the
    reference pattern for cross-encoders — one forward pass for N pairs, not N passes."""
    if not pairs:
        return []
    global _NLI
    if _NLI is None:
        from sentence_transformers import CrossEncoder
        _NLI = CrossEncoder(config.NLI_MODEL)
    logits = _NLI.predict([[p, h] for p, h in pairs])
    import numpy as _np
    p = _np.exp(logits) / _np.exp(logits).sum(axis=1, keepdims=True)
    labels = getattr(_NLI.model.config, "id2label", {}) or {}
    out = []
    for i in range(len(pairs)):
        j = int(p[i].argmax())
        label = labels.get(j, ["contradiction", "entailment", "neutral"][j] if j < 3 else "neutral")
        label = str(label).lower()
        if "contra" in label:
            label = "contradiction"
        elif "enta" in label:
            label = "entailment"
        else:
            label = "neutral"
        out.append((label, float(p[i][j])))
    return out


def unload_local(*models: str):
    c = _ollama()
    for m in models:
        try:
            c.generate(model=m, prompt="", keep_alive=0)
        except Exception:
            pass


def warmup(model: str = "", embed: bool = True):
    """Preload the local model(s) so the first real query skips the cold load.
    An empty prompt loads a model in Ollama and honours keep_alive."""
    model = model or config.LOCAL_WRITER
    c = _ollama()
    loaded, errors = [], []
    targets = [model] + ([config.OLLAMA_EMBED_MODEL] if embed else [])
    for m in targets:
        try:
            if m == config.OLLAMA_EMBED_MODEL:
                c.embed(model=m, input=["warmup"])
            else:
                c.generate(model=m, prompt="", keep_alive=config.LOCAL_KEEP_ALIVE)
            loaded.append(m)
        except Exception as e:
            errors.append(f"{m}: {e}")
    return {"loaded": loaded, "errors": errors}
