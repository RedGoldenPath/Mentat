#!/usr/bin/env python
"""Safe M4 diagnostic: measure a real training step (model.train(), grad
checkpointing) at small sequence lengths under a hard wired-memory cap, so an
OOM raises instead of flooding the machine.

The earlier "cheap" probes silently took the eval path (self.training=False ->
use_kernel=True). The trainer takes gated_delta_ops: an unrolled O(T) loop.
This measures exactly that.
"""
import sys

import mlx.core as mx
import mlx.nn as nn
from mlx_lm import load
from mlx_lm.tuner.trainer import grad_checkpoint
from mlx_lm.tuner.utils import linear_to_lora_layers

CAP_GB = 30
mx.metal.set_wired_limit(CAP_GB * 1024**3)


def _f(name):
    return getattr(mx, name, None) or getattr(mx.metal, name)


def mem(clear=False):
    if clear:
        mx.clear_cache()
    active = round(_f("get_active_memory")() / 1e9, 2)
    peak = round(_f("get_peak_memory")() / 1e9, 2)
    return active, peak


def reset_peak():
    fn = getattr(mx, "reset_peak_memory", None) or getattr(mx.metal, "reset_peak_memory", None)
    if fn:
        fn()


model, _ = load("models/qwen3.8-27b-4bit")
model.freeze()
linear_to_lora_layers(model, 16, {"rank": 16, "dropout": 0.05, "scale": 16.0})
grad_checkpoint(model.layers[0])
model.train()
print(f"wired_cap={CAP_GB}GB loaded: active/peak={mem(True)}", flush=True)

for S in [128, 256, 512]:
    toks = mx.array([[1] * S])

    def loss_fn(m):
        out = m(toks)
        return nn.losses.cross_entropy(out[:, :-1, :], toks[:, 1:], reduction="mean")

    lg = nn.value_and_grad(model, loss_fn)
    reset_peak()
    before = mem(True)[0]
    try:
        loss, grads = lg(model)
        mx.eval(loss, grads)
        lv = float(loss)
        active, peak = mem()
        print(f"S={S:4d} ok  loss={lv:.3f} before={before} active={active} peak={peak}", flush=True)
    except Exception as exc:
        print(f"S={S:4d} FAIL {type(exc).__name__}: {str(exc)[:200]}", flush=True)
        break
    del loss, grads, lg, toks
    mx.clear_cache()
    print(f"        cleared -> active={mem()[0]}", flush=True)
