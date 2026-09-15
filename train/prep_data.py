#!/usr/bin/env python
"""Filter the raw dataset for training: tokenize, drop overlength samples.

mlx-lm truncates sequences by keeping the START and cutting the END — which
would decapitate the assistant answer for long evidence prompts. So we drop
anything longer than the training window (minus a safety margin) instead.

Usage:
  .venv/bin/python train/prep_data.py [--max-tokens 7800]
"""
import argparse
import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / ".venv" / "lib" / "python3.14" / "site-packages"))

MODEL = HERE / "models" / "qwen3.8-27b-4bit"
RAW = HERE / "data"
OUT = HERE / "data_final"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-tokens", type=int, default=7800)
    args = ap.parse_args()

    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(str(MODEL))
    OUT.mkdir(parents=True, exist_ok=True)
    report = {}
    for split in ("train", "valid"):
        src = RAW / f"{split}.jsonl"
        dst = OUT / f"{split}.jsonl"
        kept, dropped = [], []
        lengths = []
        kinds = {}
        if not src.exists():
            print(f"{split}: missing {src}")
            continue
        for line in src.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            ids = tok.apply_chat_template(row["messages"], return_dict=False)
            n = len(ids)
            lengths.append(n)
            if n > args.max_tokens:
                dropped.append(n)
                continue
            kept.append(row)
            kinds[row["kind"]] = kinds.get(row["kind"], 0) + 1
        with open(dst, "w", encoding="utf-8") as fh:
            for row in kept:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        report[split] = {
            "kept": len(kept),
            "dropped": len(dropped),
            "max_kept": max([l for l in lengths if l <= args.max_tokens], default=0),
            "p95": int(statistics.quantiles(lengths, n=20)[18]) if lengths else 0,
            "median": int(statistics.median(lengths)) if lengths else 0,
            "kinds": kinds,
        }
        print(f"{split}: {report[split]}")
    (OUT / "prep_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
