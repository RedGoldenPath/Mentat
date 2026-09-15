#!/usr/bin/env python
"""Debug wrapper: log MLX memory at every mx.eval during a short LoRA run."""
import sys

import mlx.core as mx

_orig_eval = mx.eval
CALL = {"n": 0}


def mem():
    g = lambda n: getattr(mx, n, None) or getattr(mx.metal, n)  # noqa: E731
    try:
        return (round(g("get_active_memory")() / 1e9, 1),
                round(g("get_peak_memory")() / 1e9, 1))
    except Exception:
        return ("?", "?")


def logged_eval(*args, **kwargs):
    CALL["n"] += 1
    a, p = mem()
    print(f"eval#{CALL['n']} active={a}GB peak={p}GB", flush=True)
    return _orig_eval(*args, **kwargs)


mx.eval = logged_eval
try:
    mx.metal.set_wired_limit(40 * 1024**3)
except Exception as exc:
    print("wired:", exc)

from mlx_lm.lora import main  # noqa: E402

if __name__ == "__main__":
    main()
