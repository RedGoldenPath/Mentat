#!/usr/bin/env python
"""Build the mixed fine-tune set: default register + dialectical reasoning.

Goal: bake dialectical thinking into the model for the *interpretive* register
while keeping quote/count answers strict. Dialectic traces are upsampled to a
target share of the training mix; both splits are length-filtered to the
training window (chunked gated-delta makes 4096 tokens fit 48GB).

Usage:
  .venv/bin/python train/prep_mix.py --max-tokens 4000 --dialectic-share 0.4
"""
import argparse
import json
import random
from pathlib import Path

APP = Path(__file__).resolve().parent


def est_tokens(row):
    return sum(len(m.get("content", "")) for m in row["messages"]) // 4


def make_len_fn(model_dir):
    """Real token count per example (chars/4 underestimates badly for the
    long, citation-heavy evidence blocks). Falls back to the estimate."""
    try:
        from transformers import AutoTokenizer

        tok = AutoTokenizer.from_pretrained(str(APP / model_dir))

        def nte(text):
            return len(tok(text)["input_ids"])

        def fn(row):
            # +8 per message for role/template overhead
            return sum(nte(m.get("content", "")) + 8 for m in row["messages"])

        return fn
    except Exception as exc:  # pragma: no cover
        print(f"[prep_mix] tokenizer unavailable ({exc}); using char estimate")
        return est_tokens


def load(path):
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--default-dir", default="data")
    ap.add_argument("--dialectic-dir", default="data_dialectic")
    ap.add_argument("--out", default="data_mix")
    ap.add_argument("--model", default="models/qwen3.8-27b-4bit")
    ap.add_argument("--max-tokens", type=int, default=1400)
    ap.add_argument("--dialectic-share", type=float, default=0.4)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    base, dia, out = APP / args.default_dir, APP / args.dialectic_dir, APP / args.out
    out.mkdir(parents=True, exist_ok=True)
    nt = make_len_fn(args.model)

    for split in ("train", "valid"):
        d = [r for r in load(base / f"{split}.jsonl") if nt(r) <= args.max_tokens]
        x = [r for r in load(dia / f"{split}.jsonl") if nt(r) <= args.max_tokens]
        if split == "train" and x:
            share = min(max(args.dialectic_share, 0.0), 0.9)
            target = int(len(d) * share / max(1e-6, 1 - share))
            if len(x) < target:
                reps, rem = divmod(target, len(x))
                x = x * reps + x[:rem]
        rows = d + x
        rng.shuffle(rows)
        (out / f"{split}.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
            encoding="utf-8",
        )
        kinds = {}
        for r in rows:
            kinds[r.get("kind", "?")] = kinds.get(r.get("kind", "?"), 0) + 1
        print(f"{split}: default={len(d)} dialectic={len(x)} total={len(rows)} kinds={kinds}")


if __name__ == "__main__":
    main()
