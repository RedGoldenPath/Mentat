#!/usr/bin/env python
"""Wrapper for mlx_lm.lora: enables the chunked gated-delta patch and caps the
Metal wired limit before training.

Why the patch is required: qwen3.8's hybrid linear-attention layers take the
`gated_delta_ops` path during training, which unrolls a Python loop over the
whole sequence and builds an O(T) autograd graph (>100GB at 4096 tokens). The
chunked patch processes the sequence in checkpointed chunks so peak memory is
O(chunk_size) instead. See chunked_delta.py.

The wired limit is set below physical RAM so an unexpected allocation spikes
errors instead of flooding the machine (the crash that forced the last
shutdown was an unbounded 27B step).
"""
import os
import sys

import mlx.core as mx

import chunked_delta

CHUNK = int(os.environ.get("MENTAT_CHUNK", "256"))
WIRED_GB = int(os.environ.get("MENTAT_WIRED_GB", "36"))

chunked_delta.enable(CHUNK)

# mlx_lm compiles the training step. For the hybrid Qwen3.5 recurrence the
# unrolled graph is ~200k ops; compiling it materialises extra buffers and
# pushes peak memory past the wired limit (OOM at iter 2 on a 48GB box), while
# adding no real speedup. Disabling compilation keeps the cached-array path
# that the SAFE probe validated at ~28GB. Set MENTAT_COMPILE=1 to re-enable.
if os.environ.get("MENTAT_COMPILE", "0") != "1":
    def _no_compile(fn=None, **_kwargs):
        if fn is None:
            return lambda f: f
        return fn

    mx.compile = _no_compile

try:
    mx.set_wired_limit(WIRED_GB * 1024**3)
except Exception as exc:
    print(f"wired limit not raised: {exc}", file=sys.stderr)

from mlx_lm.lora import main  # noqa: E402

if __name__ == "__main__":
    main()
