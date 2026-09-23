#!/usr/bin/env python
"""Fit distillation examples to the training window by trimming EVIDENCE.

Long evidence in the system prompt pushes examples past `max_seq_length`, the
truncation drops the assistant turn, `mask_prompt` then supervises ZERO tokens,
and the loss goes NaN (the failure recorded in storage/BACKGROUND.md). This
trims each example's system/evidence content so the user+assistant turn always
survives inside the window.
"""
import json
import sys
from pathlib import Path

from transformers import AutoTokenizer

ROOT = Path(__file__).resolve().parent
MODEL = sys.argv[2] if len(sys.argv) > 2 else "models/Qwen2.5-7B-Instruct-4bit"
TOK = AutoTokenizer.from_pretrained(str(ROOT / MODEL))
MAX = int(sys.argv[1]) if len(sys.argv) > 1 else 1900


def toks(s):
    return len(TOK.encode(s or ""))


for name in ("train", "valid"):
    p = ROOT / "data_distill" / f"{name}.jsonl"
    if not p.exists():
        continue
    kept, dropped = [], 0
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        msgs = row.get("messages") or []
        other = sum(toks(m.get("content")) for m in msgs if m.get("role") != "system") + 30
        budget = MAX - other
        if budget < 160:
            dropped += 1
            continue
        sysm = next((m for m in msgs if m.get("role") == "system"), None)
        if sysm:
            ids = TOK.encode(sysm.get("content") or "")
            if len(ids) > budget:
                sysm["content"] = TOK.decode(ids[:budget])
        kept.append(json.dumps(row, ensure_ascii=False))
    p.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    print(f"{name}: kept {len(kept)}, dropped {dropped}")
