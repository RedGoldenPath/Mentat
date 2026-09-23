#!/usr/bin/env python
"""Prana Bindu — distillation dataset (LOCAL 27B teacher).

Teaches the small local model to reproduce the **27B writer's** grounded, cited
answers. Reuses `build_dataset.py`'s question generation and the verifier
scoring, but swaps the *answer* teacher from the cloud to the **local 27B**
(`qwen3.8:27b` via Ollama), so the target behaviour is exactly what the engine
ships offline. Kept only when the verifier passes (quotes verbatim, citations
resolve). Resume-safe; writes `train/data_distill/{train,valid}.jsonl`.

Run (long — hours; resumable, so run in pieces or overnight):
  .venv/bin/python train/build_distill.py --n 500
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "train"))

import brain_core as bc  # noqa: E402
import build_dataset as bd  # noqa: E402


async def local_teacher(prompt, system=None, model=None, max_tokens=1500, tag="", **kw):
    """Answer teacher = the local 27B writer (offline, free, no API key)."""
    text = await bc.ollama_llm(
        prompt,
        system_prompt=system,
        local_model=bc.OLLAMA_LLM_MODEL,
        think=False,
        max_tokens=max_tokens,
    )
    return (text or ""), 0  # usage 0 (local is free)


def main():
    bd.teacher_call = local_teacher
    # Grounded register only (the shipping behaviour), not the dialectic target.
    default = [
        "--n", "500",
        "--concurrency", "1",          # one 27B resident; serialize
        "--kinds", "concept,compare,commentary,research,quotes,census",
        "--data-dir", "data_distill",
    ]
    sys.argv = ["build_distill.py"] + (sys.argv[1:] or default)
    asyncio.run(bd.main())


if __name__ == "__main__":
    main()
