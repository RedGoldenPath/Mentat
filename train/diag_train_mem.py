#!/usr/bin/env python
"""Stage-by-stage memory diagnostic for the 27B QLoRA step.

The trainer hits a fixed ~35.5GB peak even on a 132-token batch, so the extra
~20GB over the direct probe is structural (optimizer state, model.state
materialisation, or the eval pass). This prints active/peak after each stage.
"""
import mlx.core as mx
import mlx.nn as nn
import mlx.optimizers as optim
from mlx_lm import load
from mlx_lm.tuner.trainer import grad_checkpoint
from mlx_lm.tuner.utils import linear_to_lora_layers

import chunked_delta


def _f(name):
    return getattr(mx, name, None) or getattr(mx.metal, name)


def mem(label, clear=False):
    if clear:
        mx.clear_cache()
    a = round(_f("get_active_memory")() / 1e9, 2)
    p = round(_f("get_peak_memory")() / 1e9, 2)
    print(f"{label:<28} active={a:>6} peak={p:>6}", flush=True)
    return a, p


mx.set_wired_limit(36 * 1024**3)
chunked_delta.enable(256)

model, _ = load("models/qwen3.8-27b-4bit")
mem("after load", True)
model.freeze()
linear_to_lora_layers(model, 16, {"rank": 16, "dropout": 0.05, "scale": 16.0})
mem("after lora")
grad_checkpoint(model.layers[0])
model.train()
mem("after train()")

opt = optim.Adam(learning_rate=1e-5)
state = [model.state, opt.state, mx.random.state]
mx.eval(state)
mem("after eval(state)")

toks = mx.array([[1, *((list(range(1, 120)) * 2)[:127])]]).astype(mx.int32)


def loss_fn(m):
    out = m(toks)
    return nn.losses.cross_entropy(out[:, :-1, :], toks[:, 1:], reduction="mean")


lg = nn.value_and_grad(model, loss_fn)
loss, grads = lg(model)
mx.eval(loss, grads)
mem("after fwd/bwd S=128")
opt.update(model, grads)
mx.eval(model.state, opt.state)
mem("after opt.update", True)
