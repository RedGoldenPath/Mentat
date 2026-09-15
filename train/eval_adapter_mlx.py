#!/usr/bin/env python
"""Test the dialectic adapter directly in MLX (no Ollama).

Loads the base 27B, optionally with the LoRA adapter, and generates on a real
library prompt (a held-out dialectic example's evidence+question). Compare the
base vs adapter output to see whether the fine-tune changed the *reasoning*,
and run deterministic grounding checks (citations, ungrounded quotes).

Usage:
  .venv/bin/python eval_adapter_mlx.py                 # base only
  .venv/bin/python eval_adapter_mlx.py --adapter adapters/mentat-dialectic
"""
import argparse
import json
import re
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

CITE_RE = re.compile(r"\([^()\n]{3,90} · [^()\n]{1,90}\)")
REFUSAL = ("not in", "no such", "does not contain", "no passage", "cannot find",
           "no mention", "is not in", "isn't in", "no quote", "not reproduced")
MOVEMENT = ("contradict", "aufhebung", "sublat", "negat", "spiral", "unity",
            "opposite", "threshold", "preserve", "higher")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", default="")
    ap.add_argument("--example", default="data_dialectic/valid.jsonl")
    ap.add_argument("--idx", type=int, default=0)
    ap.add_argument("--max-tokens", type=int, default=700)
    args = ap.parse_args()

    from mlx_lm import load, generate
    from transformers import AutoTokenizer

    p = Path(args.example)
    rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    ex = rows[args.idx]
    msgs = ex["messages"]
    htok = AutoTokenizer.from_pretrained("models/qwen3.8-27b-4bit")
    try:
        prompt = htok.apply_chat_template(
            msgs[:-1], tokenize=False, add_generation_prompt=True, enable_thinking=False
        )
    except TypeError:
        prompt = htok.apply_chat_template(
            msgs[:-1], tokenize=False, add_generation_prompt=True
        )

    print(f"== kind={ex.get('kind')} | adapter={args.adapter or 'none'} | q: {msgs[-2]['content'][:80]}")
    model, tok = load("models/qwen3.8-27b-4bit", adapter_path=(args.adapter or None))
    out = generate(model, tok, prompt=prompt, max_tokens=args.max_tokens, verbose=False)

    import brain_core as bc
    passages = [{"file_path": (msgs[0]["content"] or "")[:0], "content": msgs[0]["content"]}]
    cites = len(CITE_RE.findall(out))
    ungr = bc._verify_quotes(out, [{"content": msgs[0]["content"], "file_path": "x"}]) or []
    low = out.lower()
    hits = [m for m in MOVEMENT if m in low]
    print(f"citations={cites} ungrounded={len(ungr)} refused={int(any(r in low for r in REFUSAL))} "
          f"movement_terms={hits}")
    print("\n--- ANSWER ---\n" + out[:2500])


if __name__ == "__main__":
    main()
