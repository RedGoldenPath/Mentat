#!/usr/bin/env python
"""Probe: does the chunked gated-delta patch let a 27B training step fit 48GB
at full 4096-sequence length? Hard 30GB wired cap so an OOM raises instead of
flooding the machine.
"""
import sys

import mlx.core as mx
import mlx.nn as nn
from mlx_lm import load
from mlx_lm.tuner.trainer import grad_checkpoint
from mlx_lm.tuner.utils import linear_to_lora_layers

import chunked_delta

CAP_GB = 30
mx.set_wired_limit(CAP_GB * 1024**3)


def _f(name):
    return getattr(mx, name, None) or getattr(mx.metal, name)


def _leaves(tree):
    if isinstance(tree, dict):
        for v in tree.values():
            yield from _leaves(v)
    elif isinstance(tree, (list, tuple)):
        for v in tree:
            yield from _leaves(v)
    elif isinstance(tree, mx.array):
        yield tree


def mem(clear=False):
    if clear:
        mx.clear_cache()
    return round(_f("get_active_memory")() / 1e9, 2), round(_f("get_peak_memory")() / 1e9, 2)


chunk = int(sys.argv[1]) if len(sys.argv) > 1 else 256
chunked_delta.enable(chunk)

model, _ = load("models/qwen3.8-27b-4bit")
model.freeze()
linear_to_lora_layers(model, 16, {"rank": 16, "dropout": 0.05, "scale": 16.0})
grad_checkpoint(model.layers[0])
model.train()
print(f"chunk={chunk} cap={CAP_GB}GB loaded: {mem(True)}", flush=True)

for S in [1024, 4096]:
    toks = mx.array([[1] * S])

    def loss_fn(m):
        out = m(toks)
        return nn.losses.cross_entropy(out[:, :-1, :], toks[:, 1:], reduction="mean")

    lg = nn.value_and_grad(model, loss_fn)
    before = mem(True)[0]
    try:
        loss, grads = lg(model)
        mx.eval(loss, grads)
        a, p = mem()
        gnorm = sum(float((g * g).sum()) for g in _leaves(grads)) ** 0.5
        print(f"S={S:4d} ok loss={float(loss):.3f} grad_norm={gnorm:.3f} "
              f"before={before} active={a} peak={p}", flush=True)
    except Exception as exc:
        print(f"S={S:4d} FAIL {type(exc).__name__}: {str(exc)[:300]}", flush=True)
        break
    del loss, grads, lg, toks
    mx.clear_cache()
