#!/usr/bin/env python
"""M4 memory fix: chunk the O(T) gated-delta recurrence with gradient
checkpointing.

`gated_delta_ops` (the training/eval-off-kernel path) unrolls a Python loop
over the whole sequence, building an O(T) autograd graph and retaining every
recurrent state. At 4096 tokens that is >100GB for a 27B hybrid, so QLoRA
cannot fit 48GB.

This replaces the module-global `gated_delta_ops` with a version that processes
the sequence in fixed-size chunks, checkpointing each chunk so the backward
pass recomputes it from the carried state. Peak memory becomes O(chunk_size)
instead of O(T), with identical math and gradients.
"""
from typing import Optional, Tuple

import mlx.core as mx

from mlx_lm.models import gated_delta as gd

_ORIG_OPS = gd.gated_delta_ops
CHUNK_SIZE = 256
_ENABLED = False


def chunked_gated_delta_ops(
    q: mx.array,
    k: mx.array,
    v: mx.array,
    g: mx.array,
    beta: mx.array,
    state: Optional[mx.array] = None,
    mask: Optional[mx.array] = None,
) -> Tuple[mx.array, mx.array]:
    B, T, Hk, Dk = q.shape
    Hv, Dv = v.shape[-2:]
    if state is None:
        state = mx.zeros((B, Hv, Dv, Dk), dtype=mx.float32)

    if (repeat_factor := Hv // Hk) > 1:
        q = mx.repeat(q, repeat_factor, -2)
        k = mx.repeat(k, repeat_factor, -2)

    ys = []
    for start in range(0, T, CHUNK_SIZE):
        end = min(start + CHUNK_SIZE, T)
        qc, kc, vc, gc, bc = (
            q[:, start:end], k[:, start:end], v[:, start:end],
            g[:, start:end], beta[:, start:end],
        )
        mc = None if mask is None else mask[:, start:end]

        def scan(state, qc, kc, vc, gc, bc, mc):
            out = []
            for t in range(qc.shape[1]):
                y, state = gd._gated_delta_step_ops(
                    qc[:, t], kc[:, t], vc[:, t], gc[:, t], bc[:, t], state,
                    None if mc is None else mc[:, t],
                )
                out.append(y)
            return mx.stack(out, axis=1), state

        y_chunk, state = mx.checkpoint(scan)(state, qc, kc, vc, gc, bc, mc)
        ys.append(y_chunk)

    return mx.concatenate(ys, axis=1), state


def enable(chunk_size: int = 256):
    global CHUNK_SIZE, _ENABLED
    CHUNK_SIZE = chunk_size
    gd.gated_delta_ops = chunked_gated_delta_ops
    _ENABLED = True
    return gd.gated_delta_ops


def disable():
    global _ENABLED
    gd.gated_delta_ops = _ORIG_OPS
    _ENABLED = False
