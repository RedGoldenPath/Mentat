#!/usr/bin/env python
"""Equivalence test for the chunked gated-delta patch.

The patch only exists to bound memory; it must not change the math. This runs
the same short sequence through the ORIGINAL O(T) recurrence and the CHUNKED
recurrence and asserts the loss and every LoRA gradient are identical.
"""
import mlx.core as mx
import mlx.nn as nn
from mlx_lm import load
from mlx_lm.tuner.trainer import grad_checkpoint
from mlx_lm.tuner.utils import linear_to_lora_layers

import chunked_delta


def _leaves(tree):
    if isinstance(tree, dict):
        for v in tree.values():
            yield from _leaves(v)
    elif isinstance(tree, (list, tuple)):
        for v in tree:
            yield from _leaves(v)
    elif isinstance(tree, mx.array):
        yield tree


mx.set_wired_limit(30 * 1024**3)
S = 384
toks = mx.array([[1, *((list(range(1, 200)) * 4)[: S - 1])]]).astype(mx.int32)

model, _ = load("models/qwen3.8-27b-4bit")
model.freeze()
linear_to_lora_layers(model, 4, {"rank": 8, "dropout": 0.0, "scale": 16.0})
grad_checkpoint(model.layers[0])
model.train()


def step():
    def loss_fn(m):
        out = m(toks)
        return nn.losses.cross_entropy(out[:, :-1, :], toks[:, 1:], reduction="mean")

    lg = nn.value_and_grad(model, loss_fn)
    loss, grads = lg(model)
    mx.eval(loss, grads)
    return float(loss), [g for g in _leaves(grads)]


chunked_delta.disable()
loss_a, grads_a = step()
mx.clear_cache()
grad_scale = max(float(mx.max(mx.abs(g))) for g in grads_a)

for chunk in (S, 192, 64):
    chunked_delta.enable(chunk)
    loss_b, grads_b = step()
    mx.clear_cache()
    assert abs(loss_a - loss_b) < 1e-5, f"loss mismatch at chunk={chunk}"
    max_delta = max(float(mx.max(mx.abs(ga - gb))) for ga, gb in zip(grads_a, grads_b))
    rel = max_delta / grad_scale
    print(f"chunk={chunk:4d} loss_delta={abs(loss_a-loss_b):.2e} "
          f"max|grad_delta|={max_delta:.3e} rel={rel:.2e}")
    assert rel < 1e-3, f"gradient mismatch at chunk={chunk}"

print(f"PASS: chunked recurrence equivalent to original (grad scale ~{grad_scale:.3g})")
