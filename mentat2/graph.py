"""A tiny declared-stage graph runner (LangGraph/Haystack-shaped, no deps).

Topology is data: an ordered list of named stages, each a function over a shared
typed-ish state dict, with an optional `when` guard. Every stage emits a telemetry
span. This is the seam where the pipeline stops being an if-stack.
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from . import telemetry


@dataclass
class Stage:
    name: str
    fn: Callable[[dict], None]
    when: Optional[Callable[[dict], bool]] = None


@dataclass
class Graph:
    stages: list = field(default_factory=list)

    def add(self, name: str, fn: Callable[[dict], None], when: Optional[Callable[[dict], bool]] = None):
        self.stages.append(Stage(name=name, fn=fn, when=when))
        return self

    def run(self, state: dict) -> dict:
        from . import gateway        # drained per stage so spans carry real token/cache cost
        for st in self.stages:
            try:
                if st.when is not None and not st.when(state):
                    continue
            except Exception:
                continue
            try:
                gateway.take_usage()     # clear before the stage
            except Exception:
                pass
            t = time.time()
            st.fn(state)
            secs = round(time.time() - t, 3)
            try:
                used = gateway.take_usage()
            except Exception:
                used = []
            tin = sum(int(u.get("prompt_tokens", 0)) for u in used)
            tout = sum(int(u.get("completion_tokens", 0)) for u in used)
            cached = sum(int(u.get("cached_prompt_tokens", 0)) for u in used)
            reasoning = sum(int(u.get("reasoning_tokens", 0)) for u in used)
            load_ms = round(sum(float(u.get("load_ms", 0)) for u in used), 1)
            prefill_ms = round(sum(float(u.get("prefill_ms", 0)) for u in used), 1)
            decode_ms = round(sum(float(u.get("decode_ms", 0)) for u in used), 1)
            acc = state.setdefault("usage", {"tokens_in": 0, "tokens_out": 0,
                                             "cached": 0, "reasoning": 0,
                                             "load_ms": 0, "prefill_ms": 0, "decode_ms": 0})
            acc["tokens_in"] += tin
            acc["tokens_out"] += tout
            acc["cached"] += cached
            acc["reasoning"] += reasoning
            acc["load_ms"] += load_ms
            acc["prefill_ms"] += prefill_ms
            acc["decode_ms"] += decode_ms
            telemetry.record(st.name, state.get("sid", ""), stage=st.name, seconds=secs,
                             tokens_in=tin, tokens_out=tout, model=",".join(
                                 sorted({u.get("model", "") for u in used if u.get("model")})),
                             cached_tokens=cached, reasoning_tokens=reasoning,
                             load_ms=load_ms, prefill_ms=prefill_ms, decode_ms=decode_ms,
                             calls=len(used))
        return state
