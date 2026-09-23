# PLAN — Mentat (authoritative checklist)

**This file is the single source of truth.** The chat and the session todo list only
mirror it. Re-read it at the start of every work session; update it at every step and
phase boundary; never write a "done" summary without diffing against it. A deferred item
MUST be moved to the Backlog with a reason — nothing silently disappears.

Status: in-progress · Focus: **brain/engine (`brain_core.py`, `server.py`, retrieval,
synthesis, dialectic)**. App/UI items deferred (see Backlog).

Gates every step: `python verify.py --quick` (36) · `python eval.py --gold` (13/13) ·
`python eval.py` (82/86). Phase boundary: `battery.py --compare` on time/accuracy/RAM/tokens.

---

## Now — brain/engine

- [x] **A1 · Phase 4.1 — small offline helper.** Default helper is now
  `qwen2.5:7b` (non-thinking instruct; `qwen3:4b` leaked reasoning and broke
  structured output). `OLLAMA_FAST_MODEL` env overrides; `OLLAMA_FAST_KEEP_ALIVE`
  (2m) unloads it fast. Writer keep-alive lowered 30m→10m. Gate: verify 36/36.
  The 21 GB MoE is no longer the default helper (kept only as `qwen-deep` synth).
- [x] **A5 · Phase 2 remainder — structured citations + verbatim verify.**
  `_verify_quotes` now normalizes (curly quotes, de-hyphenation, whitespace) and
  accepts verbatim containment, falling back to a strict 0.8 overlap — real
  quotes stop being flagged for OCR/line-break drift; fabrications still caught.
  Pointer-spliced reader quotes (quote is a verbatim passage substring) landed in
  Phase 2. Gate: verify 36/36, gold 13/13.
- [x] **6a+ · Learn-to-rank default.** Held-out check on `eval.py --gold` (not in
  the citation telemetry): with it 2/2 clean 13/13, without 1 flaky 12/13. Now
  **on by default** (`MENTAT_NO_LEARN2RANK=1` disables). Cached prior, no
  compute cost.
- [x] **Fast-path output cap.** `_offline_gen_kwargs` caps `fast` questions at
  500 tokens (on top of the trimmed evidence) → less sustained load.
- [x] **Quiet tuning (partial).** Helper = `qwen2.5:7b` (2m keep-alive); writer
  keep-alive 30m→10m. (Prompt-prefix cache still open — A2.)
- [x] **A6 · Passage resolution robustness (first-plan item, recovered).**
  `server._citations` splits 3+ part labels; `_passage_source` normalizes
  (diacritic fold, markdown strip, `Ch.`→`chapter`), resolves book aliases
  (subset + difflib) and loc-by-segment, with a hint-overlap fallback. Replay:
  **77/120 → 110/120 resolved** (115/120 with the answer hint, as production
  passes); quotes 100% verbatim substrings. Deterministic.
- [ ] **A2 · Phase 4.2/4.3 — quiet plumbing.** Prompt-prefix cache; merge/cache
  helper calls. Gate: `gen_tokens` / `helper_sec` down, quality flat.
- [x] **Stage 1 · Lean Thinking + merged hybrid planning (DONE).**
  `_plan_needed` (deterministic gate) + `_plan_question` — ONE call returns
  comprehension + HyDE + counter-queries; 7B helper by default, escalates to the
  27B on hard questions; cached. Counts/quotes skip it entirely. Telemetry logs
  `helper_calls` (model-calls/answer). Battery: cites 27→36, ungrounded 0→2 (the
  stricter verifier marking non-verbatim quotes), time flat.
- [x] **A3 · offline comprehension (via merged plan).** Kind/phrase/books/angles
  now populate offline too, so routing/census/strategy see intent.
- [x] **A4 · selective HyDE (via merged plan).** The plan's `hypothetical` feeds
  semantic search; no separate call.
- [x] **C2 · dialectic retrieval (via merged plan).** `counter_queries` appended
  for argumentative questions only; rubric stays a soft signal.
- [x] **Stage 2.5 · Output-cap consistency (DONE).** Non-stream `ask()` now uses
  `_offline_gen_kwargs` like the app; caps **raised** so enumerations aren't
  truncated (quote/list 4000, conceptual 3000, default 1500, fast 600); a
  clean-stop continues a clipped answer once. Battery: cites 34 (≈uncapped 36),
  ungrounded 0. **Context compression was tried and REVERTED** — it cut citations
  (16→1 on the compare); quality > 20% speed.
- [ ] **Format question (answered):** structured/JSON output is NOT faster — it
  adds tokens (keys/braces/escaping) and any typist pass offsets the saving.
  Prose is token-efficient; the real levers are fewer tokens, less evidence
  prefill, and (ultimately) a smaller writer. Structure helps *accuracy*, not speed.
- [ ] **Stage 3 · Living Brain** — turn retrieval switches into weights (soft
  routing) + relaxation/early-exit; consolidate routing into Lisan al-Gaib (C1).
- [ ] **C3 · Phase 6c — cache prewarm + speculative retrieval.** Hit-rate gated;
  auto-disable if net-negative.
- [ ] **C4 · Phase 6d — knob auto-tuner** against held-out gold + Spice Agony.
- [x] **C5 · Phase 6e — Prana Bindu (distillation): RETIRED.** The 7B LoRA
  distilled from the local 27B (`train/adapters/mentat-distill`, 150 iters,
  loss 1.28→0.63; gate 7.9s/9.8GB/0 ungrounded vs 27B 25s/24GB) was wired as an
  MLX-served fast-tier writer. **Ruled not worth it:** it lives in a second
  runtime (MLX) because Ollama refused the MLX-quantized weights, so "automatic"
  meant a *third* model resident (27B + helper + distill) → system RAM spiked to
  ~94%. Retired: removed the `distill` preset, the fast-tier routing
  (`_fast_route_enabled`/`_fast_tier_ready`), and the MLX autostart; deleted the
  fused model (4 GB) + adapter (352 MB). The whole **MLX runtime is gone**
  (constants, `mlx` preset, `mlx/` provider branches, `_merge_system_messages`),
  and its models deleted (`qwen3.8-27b-4bit` 15 GB,
  `Qwen3-30B-A3B-Instruct-2507-4bit` 16 GB, `Qwen2.5-7B-Instruct-4bit` 4 GB).
  App 110 GB → ~5 GB. Training scripts + small datasets kept for a future local
  model.
- [x] **Runtime = Ollama only.** Writer `qwen3.8:27b` (`qwen`), planner/worker
  helper `qwen2.5:7b` (unchanged, load-bearing: `_plan_question`, enrichment,
  book maps, summaries), embedder `nomic-embed-text`, counts via Thufir.
  `qwen-deep` repointed to `qwen3.8:27b` (was the deleted 30B); default `model`
  is now `qwen`. Ollama's keep-alive eviction keeps RAM ~one model at a time —
  MLX has no such management, so a full MLX migration was rejected (it would
  also force an embedder change + full reindex).
- [x] **Spec-decode ruled out.** MLX speculative decoding requires a *trimmable*
  prompt cache; the 27B's hybrid linear layers use `ArraysCache`
  (`is_trimmable → False`), so a same-tokenizer draft cannot accelerate it.
  Tokenizer match (Qwen3.5 small) is necessary but not sufficient.
- [x] **Naming finding.** The 27B is `model_type: qwen3_5`; "Qwen3.8" is a brand
  on the Qwen3.5 architecture. The small same-family siblings (0.8B/2B/4B/9B,
  vocab 248,320) live under the "Qwen3.5" name — there is **no small 3.8**.
- [x] **D2 · dead `mode` knob removal.** Removed the no-op setting, its spec/
  coercion, `VALID_MODES`, and the `mode` parameter from `ask`/`ask_stream`/
  `_rag_system_prompt`/`_flush_ask_telemetry`, plus all frontends (server,
  brain.py CLI, TUI, MCP) and eval. Telemetry keeps the `mode` column (written
  blank) for history. Gate: compile, verify 36/36, gold 13/13, eval 82/86.
- [ ] **D1 · Phase 5 — split `brain_core.py`** into modules (retrieval, Thufir,
  Lisan al-Gaib, Bene Gesserit, Shai-Hulud, telemetry).
- [x] **D3 · persistent HTTP clients.** Ollama/OpenAI clients cached per event
  loop (`_cached_ollama_client`/`_cached_openai_client`); no more dial-per-call.
- [x] **Lazy warming (RSS).** `warm_models` is now opt-in
  (`MENTAT_WARM_MODELS=1`); idle engine ~100 MB instead of ~1.9 GB (reranker
  ~800 MB + spans ~335 MB + vocab ~187 MB load on demand).
- [x] **Dead-code purge.** Removed `_hypothetical_passage` (superseded by the
  merged plan's `hypothetical`).
- [x] **MoE finding:** MLX cannot LoRA-train Qwen3-30B-A3B (`Cannot calculate
  VJP ... indices`). No longer relevant — MLX is removed; a future student would
  target a dense same-family model (Qwen3.5-9B).
- [x] **RAM hygiene:** no second model runtime; one model at a time via Ollama
  keep-alive; reboot clears residual swap.

### Track B (brain) — retrieved from TIMELINE.md, previously un-tracked
- [ ] B2: GraphRAG-expanded retrieval; neighbour / sentence-window context.
- [ ] B2.2–B2.5: context compression; sparse indexer; retriever mixture/router;
  speculative prefetch; RSS audit.
- [ ] Perf: off-main region sampling; async gallery.

---

## Done
- 0 dead-code cleanup (`rag` plumbing, LightRAG comments) · 0.5 boot self-heal charter ·
  1 Thufir deterministic counts (ask+stream, default-on) · 1 offline meta-call cuts
  (`helper_calls=0`) · 1 heat metric + `ans_path` telemetry · 1 Lisan al-Gaib
  `_answer_path` (fast/standard/heavy) · 2 quote-boundary fix + pointer splicing ·
  6a learn-to-rank (default-on after held-out check) · A5 normalized verbatim quote
  verification · A6 passage-resolution robustness (77/120→110/120) + verify guard ·
  A1 fast helper (`qwen2.5:7b`) + keep-alive tuning · fast-path output cap ·
  C5 distill + MLX runtime retired (Ollama-only; app 110 GB → ~5 GB) ·
  `qwen-deep` repointed to 3.8, default `model` = `qwen`.

---

## Backlog (deferred, with reason) — APP/UI (paused for now)
- Chat ↔ Research modes + indicator bar (Swift UI + engine `chat` path). Reason: user
  deprioritised app work.
- Track A-7 Screens split; ChatView / RootView / MessageRow / palette-theme plumbing.
- Type sweep remainder (role headers/meta literals); composer polish.
- Voice de-emphasis / picker.
- Earlier: hidden traffic lights; `sliderRow` Sendable warning.

## Backlog — ideas discussed, never built
- Architect→typist **JSON brief**; **tagged line protocol** for model handoff;
  **prompt-lookup speculative decoding** (needs an in-process decode loop).

## Not recoverable
- Git history is only 6 commits; nearly all work is uncommitted — archaeology came from
  docs/comments. Going forward: commit at phase boundaries (user-approved) so history is
  real.
