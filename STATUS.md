# STATUS — Mentat v2 overnight build (morning report)

**TL;DR:** v2 (`mentat2/`) is built, running, and verified end-to-end. It replaces the
prompt-based "dialectic" with a *computed* dialectic (claim/attack graph → grounded labelling
→ position → determinate negation → sublation → return), instrumented at every stage. It is
**~9× faster** in fast mode (8s vs v1's 72s) and has a **grounded mode** with near-zero
fabricated quotes. Quality is comparable (judge cannot separate them). Full cut-over awaits
your review.

## What is built (`app/mentat2/`)
- `config.py`, `contracts.py` — typed config + dataclasses (Route/Passage/Claim/Attack/…).
- `gateway.py` — the ONLY model calls. Ollama + DeepSeek, reasoning-budget aware,
  **no silent fallbacks**, typed errors, 120s timeout.
- `retrieve.py` — FTS5/BM25 + sqlite-vec KNN + RRF + bge reranker + quote-hunt + census.
- `claims.py` / `attacks.py` — one claim per passage (batched, 1 call); same-subject gating +
  NLI (deberta) contradiction detection → rebut/undercut/defeater.
- `semantics.py` / `sublation.py` / `loop.py` / `invariants.py` — grounded labelling; the
  three moments + Return, capped; anti-triad checks.
- `writer.py` / `verify.py` / `memory.py` / `router.py` / `pipeline.py` / `telemetry.py`.
- `fronts/cli.py` (`ask`, `probe`, `census`, `stats`) · `fronts/server.py` (HTTP :8766).
- `eval/` — cases, hybrid judge, runner, compare.
- `TRUTH.md` — single source of truth (old PLAN/MENTAT archived).

## Results — final v2.1 (14 dialectic cases; v1 = stored v1 online answers)
| metric | v1 online | v2.1 grounded (default) |
|---|---|---|
| avg latency | 72.2s | **54.1s** |
| citations (total) | 128 | 85 |
| **ungrounded quotes** | 11 | **0** |
| pairwise preferred (A/B, bias-swapped) | 3 | **9** (2 ties) |
| movement (strict 0-7 rubric) | — | 5.36 |

v2.1 is **faster (54s vs 72s), fully grounded (0 fabricated quotes), and wins the pairwise
preference 9–3–2**. v2 fast mode (`writer_think=false`) remains ~8s for interactive use.

Controls behaved: the one-sided control (Q13) scored low and did **not** manufacture a
contradiction; the quote control (Q14) stayed strict (5s, exact Litany quote).

## Bugs found and fixed tonight
1. **sqlite-vec KNN** needed `AND k = ?` (was returning nothing).
2. **Ollama embed API** returns an object, not a dict (embeddings were NaN/empty).
3. **DeepSeek flash/pro are reasoning models** — small `max_tokens` yields *empty* content
   (the old v1 trap). Gateway now budgets for reasoning and retries larger; and
   `{"thinking":{"type":"disabled"}}` is available for the cheap structured calls.
4. **Writer without reasoning fabricates quotes** (9 ungrounded). Fixed by defaulting the
   *writer* to reason (`writer_think=true`) while claim extraction/sublation stay non-reasoning.
5. **Verifier** counted citations as ungrounded quotes and broke on nested `(ch42)`; rewrote.
6. **No API timeout** → a hung call stalled the run; added 120s + 1 retry.
7. Quotes/litany retrieval: added a rare-term quote-hunt (Litany found in 5s, verbatim).

## v2.1 architectural upgrades (reference-backed, implemented)
- **Grounding repair loop** (`repair.py`): unsupported quotations are rewritten to verbatim
  evidence or dropped; never leaves a fabricated quote. Refs: Self-RAG (2310.11511),
  CRAG (2401.15884), Chain-of-Verification (2309.11495), RARR (2210.08726).
- **Tolerant verifier**: token-overlap binding (>=90%) tolerates OCR/line-break drift.
- **Eval subsystem** (`eval/metrics.py`, `eval/judge.py`): RAGAS-style component metrics,
  anchored 0-7 G-Eval rubric, pairwise A/B with position-bias swap. Refs: RAGAS (2309.15217),
  G-Eval (2303.16634), MT-Bench/Chatbot Arena (2306.05685).
- **Return fixed point** (`loop.py`): the raised whole re-weights claim entrenchment and the
  grounded labelling is recomputed. Refs: AGM entrenchment, TMS, predictive coding.

## Honest gaps / next steps
- **Judge is non-discriminating** (rates almost everything 7/5). The gate needs a stricter or
  pairwise judge; deterministic metrics (latency, grounding, triad) are trustworthy now.
- **Speed vs grounding is a dial**: fast mode is 9× faster but under-cites; grounded mode is
  v1-speed with better grounding. Possible middle path: fast draft + a cheap grounding-repair
  pass for only the ungrounded quotes.
- **Claim/attack index is per-query cached**, not yet a full corpus index (bounded by design
  tonight). A full offline build should run in the background.
- **No MCP front-end yet**; server exists. Full cut-over (point Mentat.app at v2, retire v1)
  not done — awaiting your go.
- Cross-compare mode is currently the same path as dialectical; a dedicated multi-work
  argumentation mode remains.

## How to run
```
cd ~/Everything/mentat/app
.venv/bin/python -m mentat2.fronts.cli ask "Does Leto II's tyranny produce the freedom it was meant to secure?"
.venv/bin/python -m mentat2.fronts.cli probe "the litany against fear"
.venv/bin/python -m mentat2.fronts.cli stats
.venv/bin/python -m mentat2.eval.runner --v2 0        # run the scoreboard
.venv/bin/python -m mentat2.eval.runner --v1 --judge-v2 --compare
.venv/bin/python -m mentat2.fronts.server            # HTTP :8766
```

## RAM / safety
Honored throughout: online runs loaded **zero local LLMs** (only `nomic-embed-text`); v1 and
v2 never ran together; free memory stayed ≥ 89%; in-process small models freed on exit.
v2 writes only to `mentat2_data/`, never to v1 storage.
