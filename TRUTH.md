# TRUTH.md — Mentat v2 (single source of truth)

> Interface source of truth: **[`UX.md`](UX.md)**. Structure: [`ARCHITECTURE.md`](ARCHITECTURE.md).

This is the ONLY planning document. Chat and session todos mirror it; nothing else
counts. **It is rewritten at every phase boundary — not appended.** Deferred ideas go
straight into the Backlog with a reason. If it is not here, it is not real.

Owner: Raphael · Machine: Apple M5 Max, 48 GB RAM · Offline-first.

---

## 0 · Purpose & definition of done

A single-user, **offline-first** second brain over the library: find any quote in any
book, reason across books, and think **dialectically as a mechanism** — an **Aufhebung
spiral**, never thesis/antithesis/synthesis. Local and online run the same architecture.

**Numbers that mean "good":** grounding 0 unverified quotes; judged movement within ~1
point of online; offline full answer < ~60 s (warm); peak RAM ≤ ~34 GB; offline coverage
= quote search, counts, philosophy, cross-compare, memory.

**Done:** v2 clears the eval gate vs v1, offline meets the targets, one doc, one gateway,
one router, no silent fallbacks, MCP + app cut over.

---

## 1 · Principle — the engine computes the movement; the model describes it

The dialectic is **in the material** (the corpus and its contradictions), not a method of
thought; the discourse that reveals it is *descriptive* (Hegel EL §79 via Kojève). So:

- **The engine computes** the movement: retrieval, the attack/contradiction graph, the
  grounded labelling, the **immanent contradiction**, **cancel/preserve**, the **new
  immediacy**, the **Return**, the invariants, grounding.
- **The model proposes/describes**: it names each passage's claim, proposes the raised
  **product** (one sentence), and writes the final prose. It may **not invent negations**.

This is the honest form of "the engine computes; the model renders."

---

## 2 · The spiral (the dialectic we implement)

The three Hegelian moments (abstract / dialectical / speculative) are the **texture of one
turn**; the **spiral** is the turn repeated on its own result.

**One turn (a `Round`):**
1. **immediate** — a determinate position from the material (a claim bound to a quote).
2. **immanent contradiction** — the position's *own* one-sidedness, same-ground (not an
   external opponent; not the see-saw).
3. **Aufhebung** — cancel the one-sided aspect **and preserve** the truth (**empty
   preservation = Nihilism**, flagged), and **raise** one determinate product.
4. **the product is the next immediate** — the spiral climbs.
5. **Return** — the raised whole **re-determines the parts** (re-weight entrenchment,
   recompute the grounded labelling) to a fixed point.

**Termination — Totality:** stop when the product generates **no grounded new
contradiction** (nothing immediate left to mediate). A turn that produces no advance is a
**stall** (flagged), not Totality. `max_rounds` is only a safety cap.

**Two registers:** *within an answer* the spiral is an **explicit chain** (each `Round`
keeps `parent`); *across turns* it is **state-carried** (the prior position, via memory).

**Anti-triad invariants** (`invariants.py`, observed every turn): immanence, non-empty
preservation, one determinate product, Return executed, next-immediacy-or-Totality,
product advances, material grounding. Violations are recorded on the Round and logged
(observe-first) — never silently dropped.

*(Theory: Hegel EL §79–82; Kojève, "The Dialectic of the Real and the Phenomenological
Method" and the Master–Slave lectures; Stalin 1938 (four features: interconnection,
motion, quantity→quality, internal contradiction); Marx's materialist inversion — the
criterion of truth is material practice, "fighting and work" = grounding.)*

---

## 3 · Module map (`app/mentat2/`)

- `config.py` — typed config + env bridge.
- `registry.py` — `ModelProfile` table + `resolve(job,model)` + `normalize_usage()`.
- `gateway.py` — the ONLY model access; adapters (ollama | openai-compat); structured
  outputs (Ollama JSON-schema, DeepSeek `json_object`); no silent fallbacks.
- `contracts.py` — typed vocabulary (**spiral** model: Claim/Attack/Sublation/Round).
- `router.py` — the one decider (chat | strict | search | dialectic), auto-detected.
- `pipeline.py` — declared stages (graph); telemetry per stage.
- `retrieve.py` — BM25 + vectors + RRF + reranker + quote-hunt + census (+ span_hunt).
- `claims.py` / `attacks.py` — claim per passage (cached); NLI contradiction + immanence.
- `semantics.py` — Dung grounded labelling (+ `new_contradictions`).
- `loop.py` — the **spiral** (`Round`s, Totality stop, the Return).
- `sublation.py` — proposes the product; the engine computes cancel/preserve.
- `invariants.py` — the anti-triad rules (observed).
- `writer.py` — describes the computed movement; `verify.py` + `repair.py` — grounding.
- `memory.py` / `store.py` — bi-temporal store (v2.db); the spiral carried across turns.
- `telemetry.py` — event spans (tokens + cache now recorded).
- `diagnose.py` — the diagnostic sweep (`cli doctor`).
- `eval/` — cases, metrics, judge, runner.
- `fronts/` — cli, server (HTTP), mcp.

---

## 4 · Data model

**Spiral contracts:** `Claim{id,text,chunk_id,work,loc,entrenchment,span_start,span_end,
page,mediated}` · `Attack{id,src,dst,kind,scope,confidence,immanent}` ·
`Sublation{immediate,cancelled,preserved,product,raised,new_immediate}` ·
`Round{immediate,negation,sublation,return_delta,next_immediate,parent,invariants_ok,
violations}` · `Verdict{grounded,citations,ungrounded,counts}` · `Session{query,route,
evidence,rounds,answer,verdict,prior}` · `Span{name,session,parent,stage,model,seconds,
tokens_in,tokens_out,payload}`.

**Tables (v1 read-only):** `library.db` (chunks 8214, spans 283k), `fts.db`, `vec.db`
(nomic-embed 768d), `graph.db`. **v2.db:** `claims`, `attacks`(incl. `immanent`),
`events`, `sessions`, `memory`(bi-temporal `valid_at`/`invalid_at`).

---

## 5 · Models & runtime

Online: DeepSeek `deepseek-flash` / `deepseek-v4-pro` (reasoning; `thinking:{type}` +
`reasoning_effort`; automatic prefix caching → `prompt_cache_hit_tokens`). Helper:
`qwen2.5:7b`. Offline writer default: **`qwen3.5:35b-a3b-nvfp4`** (MoE, ~3B active,
MLX/FP4) — best offline latency; fallback `qwen3.8:27b-mlx`.

**Upgrade plan (2026-10-02, §11):** A/B `qwen3.6:35b-a3b` (or `qwen3.8:35b-a3b` if released)
as the offline writer — same 3B-active MoE shape, better record, ~same speed. The dense
`qwen3.8:27b-mlx` stays an **opt-in specialist** (picker/vision), **never co-resident** with
the writer (22 + 18 GB → swap). Measured here: MoE 22 GB / 123.5 tok/s; dense 27B 18 GB /
65.6 tok/s.

**Registry (data, per model):** context / reasoning / sampling / structured / cache /
usage / job_overrides. Verified against docs: Ollama `think` ∈ `bool|low|medium|high|max`;
`format` = `json` **or a JSON schema**; `keep_alive:0` unloads; usage
`prompt_eval_count`/`prompt_eval_cached_count`/`eval_count`.

**Serving rules:** set `num_ctx` (dynamic); Qwen sampler (thinking/non-thinking); output
budget = thinking **+** answer; read `message.thinking`; local empty-content retry.

---

## 6 · Retrieval & index

BM25(FTS5) + vectors(nomic/sqlite-vec) + RRF(60) + `bge-reranker-base`; deterministic
**quote-hunt** and **census**. **Upgrades (P5):** Contextual Retrieval (Anthropic: 50–100
token chunk context prepended to embed+BM25, then rerank, top-20); sentence-window +
auto-merge; span-anchored citations.

## 7 · Memory

Session: the prior position carried forward (**state-carried spiral**). Persistent:
bi-temporal facts (invalidate, never delete) + remembered **preserved** content
("preservation is memory" — Kojève).

## 8 · Eval & telemetry

Every stage emits a `Span` (→ `events`) with **tokens and cached tokens**. Eval:
deterministic grounding/citations + RAGAS-style faithfulness + anchored G-Eval + MT-Bench
pairwise. Offline scorecard at P7.

## 9 · Diagnostics

`mentat2/diagnose.py` + `cli doctor`: ~15 **lean, high-signal** checks (index counts +
sqlite-vec, v2 schema drift, registry↔config models, job resolution, Ollama reachability,
**attack/memory/session round-trips**, verify fixtures, telemetry, invariants, eval import,
RAM). Rule: *a check that cannot name the bug it prevents does not ship.*

## 10 · Safety & ops

**Reference-first:** before a step, name the system it copies and cross-check it (docs /
source / paper); record it here; verify with a test. Novel work may borrow sub-pieces
(cite each).

- **RAM:** one heavy model at a time; unload after; abort if free < ~35%; check `ollama ps`.
- **Disk:** keep model disk < ~200 GB; delete nothing without asking.
- **Scope:** only `app/` and `mentat2_data/`; no sudo, no system changes, no `rm -rf`.
- **Backups:** snapshot indexes before any re-embed; commit only at phase boundaries with ok.

---

## 11 · Decisions log

- 2026-10-02: **Local-model fit study + upgrade plan (not yet executed).** Reviewed the
  machine, the engine's job profile, and the open-weight field (Oct 2026) against the
  question "is a better local model available?". **Machine (measured live):** M5 Max · 48 GB
  · ~614 GB/s · 40-core GPU · macOS 27.0 · Ollama 0.35.0. **Throughput (100% GPU):**
  `qwen3.5:35b-a3b-nvfp4` **123.5 tok/s** decode / 32.7 prompt; `qwen3.8:27b-mlx`
  **65.6** / 13.8. **RAM (measured):** loading the MoE added **+20.4 GB** wired (Ollama
  reports **SIZE 22 GB**); the dense 27B reports **18 GB**; both are GatedDeltaNet hybrids
  whose KV is cheap (22 GB at both 8k and 32k ctx). **Conclusion:** the dense 27B is
  *cheaper* in RAM but ~2× slower and, per P10, failed as an auto-writer — and the two
  **cannot co-reside** (22 + 18 + ~2 helpers + ~10 OS ≈ 52 GB → swap), so "one heavy model
  resident" is a hardware law, not a preference. The **35B-A3B MoE is the Pareto point** for
  this workload (grounded instruction-following + JSON + moderate reasoning; not
  coding/agentic). Helpers (nomic-embed-text · bge-reranker-base · nli-deberta-v3-base
  ≈ 2.1 GB) stay; frontier opens (DeepSeek V4.1 Flash 552B, Kimi K3 2.8T, GLM-5.3-Flash,
  Qwen3.8-Flash-Next 125B) are **not 48 GB-local** → remain on the DeepSeek online profile.
  **Plan:** (1) check `qwen3.8:35b-a3b` (leaked in a ModelScope commit 2026-08-15); else
  `ollama pull qwen3.6:35b-a3b` — a same-shape MoE (~3B active) with a better benchmark
  record (GPQA 86.0, SWE-bench 73.4, AIME26 92.7) at ~the same speed. (2) A/B it against the
  current MoE on `mentat2.eval.head2head`/`bench.py` (quality + latency + peak RAM, same
  prompts/context). (3) On a win, add its profile to `models.json` and set
  `MENTAT2_LOCAL_WRITER` (env, reversible); keep the old tag on disk as instant rollback; do
  **not** change `gateway.py`/`registry.py` logic. (4) Leave `qwen3.8:27b-mlx` registered as
  the opt-in picker/vision model; **no per-job dual-model routing** (RAM-unsafe; P10 showed
  swaps hurt). (5) Re-verify the TRUTH targets (offline < 60 s warm, ≤ 34 GB) and record the
  result. Optional later: MLX/DFlash speculative decoding (unproven here — P10 MTP gave no
  gain; Lily reports −18% for this MoE).
- 2026-10-01: **Performance + crash pass (same product, faster).** AppKit layout crash fixed
  (window/appearance mutations deferred + change-only; `WindowAppearance` observers torn down;
  uncaught-exception logger added). Sand light rendered at **half resolution** + cadence
  **120/60/paused**; app persistence debounced, regexes cached, titlebar loop removed. Engine
  (v2 only): **WAL + busy_timeout**, read-only v1 pragmas, embed keep-alive + online embed
  warmup, batched claim lookup, cached route classification, Ollama timeout. No product change.
- 2026-09-23: v2 built beside v1. Computed dialectic; one gateway, no silent fallbacks.
- 2026-09-23: Reasoning-model budgeting + retry; `thinking:{type:disabled}` for cheap calls.
- 2026-09-23: Grounding-repair loop; tolerant verifier; eval subsystem; Return fixed-point.
- 2026-09-23: **P0/P1.** TRUTH.md consolidated; `registry.py` + `models.json` (resolve,
  usage normalization); `MENTAT2_PROFILE` override.
- 2026-09-23: **P2/P3.** `graph.py` declared runner; MLX chosen (73 s vs GGUF 118 s).
- 2026-09-23: **P6/P8.** Bi-temporal memory; MCP front-end. `span_hunt`; offline judge.
- 2026-09-23: **P10.** Offline default = MoE `qwen3.5:35b-a3b-nvfp4` (best 62 s); local
  empty-content retry; fallback `qwen3.8:27b-mlx`.
- 2026-09-23: **P4 (corrected).** Cache-first stable `_SYSTEM` (DeepSeek prefix caching
  verified); verify does **structured grounding** — a citation naming a book absent from
  the evidence is `miscited`; matcher accepts human titles ↔ filenames (token overlap).
- 2026-09-23: **Spiral build (architecture pass).** Rewrote the data model and engine to
  the **spiral**: `Attack.id` + `immanent` (persisted — the table was silently empty);
  `Sublation` cancel/preserve/product/new-immediate (all consumed); `Round` explicit
  chain + `parent`; **Totality stop**; the **Return to a fixed point**; **real
  invariants** observed each turn; memory read back (`prior`) + sessions persisted;
  gateway token/cache telemetry wired per stage; Ollama JSON-schema structured output;
  `diagnose.py` + `cli doctor`. Online + offline spiral validated end-to-end.
- 2026-09-23: **Latent bug fixed (found via the invariants).** `sublation._PROMPT.format()`
  raised `KeyError` on its own JSON braces, so **sublation always returned `{}`** and the
  spiral never climbed (the "raised" silently fell back to the position). Fixed the prompt;
  sublation now yields a real product + new immediacy. Also fixed the continuation attack
  direction so the product's own contradiction negates it at the next rung.
- 2026-09-23: **Head-to-head (6 cases, online judge, pairwise bias-swapped).** Offline
  default promoted: **`qwen3.5:35b-a3b-nvfp4`** — lat 87 s mean, movement 5.5, quality 4.33,
  grounded 0.97, invariants 4/6; **`qwen3.8:27b-mlx`** failed (≈300 s, movement 0, empty
  answers under the writer config) → registered as *fallback*. Pairwise 5–0–1. `max_rounds`
  default set to 2. Latency still above the 60 s target → streaming/tuning in Backlog.
- 2026-09-23: **Parity tests.** Thinker-only (isolate the `brief`/sublation model, judge the
  product): **3.8 6.0 > MoE 4.33 > 7B 3.33** — the thinker *is* the quality lever. End-to-end
  3 questions: **online 6.67/5.0**, local MoE 4.33, 3.8-thinker/MoE-writer 4.0 (variance + 2
  model swaps). Conclusion: keep **single-model MoE** offline (RAM, time, stability); 3.8 is
  the registered quality-thinker option. Scorecard: `python -m mentat2.eval.scorecard`.
- 2026-09-23: **Writer = describer (thinking off).** With thinking on, DeepSeek streams the
  whole budget as `reasoning_content` and sends **no content** (probe: 2200 reasoning chunks,
  0 content). The engine already computed the movement, so the writer job is `reasoning:off`
  (`writer_think` default false). Fixes empty/stream-starved answers.
- 2026-09-23: **App cut-over (P8b) + streaming (P10).** `app/server.py` is now a launcher →
  `mentat2.fronts.server` on **127.0.0.1:8765**, serving the full Swift contract (/status,
  /ask, **/ask/stream ndjson**, /conversations, /conversation[/open|/new|/delete], /books,
  /book, /passage, /settings, /command, /stats). Writer streams token-by-token
  (`gateway.chat_stream`): online 787 chunks, **offline first token ~29 s, full 36 s**.
- 2026-09-23: **Continuous chat (conversations).** Each ask is no longer its own
  conversation. Added `conversations` + `sessions.conv`; `/ask` and `/ask/stream` accept a
  `conversation` id and **return** it; `/conversations` aggregates by thread (count,
  title, last_ts); `/conversation?id` returns ordered turns; `new/open/rename/delete`
  implemented. The engine carries the **cross-turn spiral** (`memory.prior(conv)`) and a
  **history window** (last K turns) into the writer. Old lone sessions migrated to
  one-conversation-each (idempotent). The app sends `currentConv`, adopts the returned id,
  and `/clear` starts a fresh thread.
- 2026-09-23: **Threading bug fixed.** `ThreadingHTTPServer` + a shared sqlite connection
  meant concurrent writes silently failed (turns went missing). `store` now uses
  **thread-local** connections (`check_same_thread=False`).
- 2026-09-23: **Message edit/delete/regenerate + interrupt.** The app names the operation
  (edit turn i / delete turn i / regenerate turn i) and the **engine owns the rules**: new
  `turn` index on `sessions`+`memory`, `store.truncate_conversation(conv,keep)` and
  `store.delete_turn(conv,index)`, exposed as `/conversation/truncate` and
  `/conversation/delete_turn`. Editing/regenerating truncates then re-asks; deleting a user
  message removes its answer and closes the thread gap; memory is forgotten from that turn
  on, so the spiral prior stays exact. The app re-projects the transcript from
  `/conversation` after any op (single source of truth, no duplicated logic). `MessageRow`
  gained hover **Edit/Copy/Delete** (user) and **Regenerate/Copy/Delete** (assistant, plus
  Stop while streaming) and an inline editor.
- 2026-09-23: **Lean purge + repurpose.** Deleted dead code (`gateway.default_fast`
  duplication removed by consolidating `pipeline._fast`; `telemetry.last_spans`;
  `store.get_spans_for_chunk`/`all_claims`/`load_attacks`; `eval.judge.judge_local`;
  `contracts.Passage`; `config.EMBED_DIM`; unused server import; `Engine.reAsk`). Repurposed
  `retrieve.span_hunt` → **page-accurate citations** for quote mode, and
  `eval.metrics.faithfulness` → the offline harnesses + scorecard (objective quality, no
  judge). TRUTH's earlier "span citations wired" claim is now actually true.
- 2026-09-23: **Audit: router bug + reference-driven tuning.** Cross-checked Adaptive-RAG,
  Self-RAG, CRAG, Semantic Router, RouterQueryEngine.
  - **Bug fixed:** the chat router used **substring** matching (`hi` fired on "this", `hey`
    on "they", `no` on "knowledge", `counts` on "accounts") → real questions misrouted to
    chat. Now **word-boundary/whole-token** matching; regression tests added.
  - **`_ctx_ready` memoized** (was 4 `COUNT(*)` per retrieve).
  - **CRAG evidence gate evaluated → NOT shipped.** Data: rerank top-scores and lexical
    overlap do **not** separate good from nonsense (good "master" top=0.05 ≈ nonsense 0.05;
    "capital of France" overlap 0.50) — bge-reranker-base isn't a trained retrieval
    evaluator. A gate would reject valid questions. Kept post-generation grounding; backlog:
    a stronger reranker.
  - **Adaptive rounds** (Adaptive-RAG): 2 rungs only for multi-source evidence, else 1 →
    online dialectic **6.5–8.1 s** (was ~11 s).
  - **Chat job wired** (reasoning off) → chat ~1 s, no retrieval, no citations.
  - **History compaction** (400-char prior turns); **empty-evidence fallback** answers
    plainly instead of dressing up a failed retrieval; doc drift fixed.
  - Verified: `tests` 9/9 · `doctor` 16/16.
- 2026-09-23: **Intent router + chat/search modes.** Cross-checked architecture: **Semantic
  Router** (embedding-similarity intent, no LLM, local) + **LlamaIndex RouterQueryEngine**
  (selector over named engines) + **Self-RAG/Adaptive-RAG** (decide whether to retrieve).
  `router.classify` now returns **chat | strict | search | dialectic** — deterministic signals
  first (so the 14 dialectic eval cases can never silently drift), then a **nomic embedding
  vote** as tie-break, then a safe default. **chat** skips retrieval entirely (no citations,
  conversational prompt, uses thread history); **search** retrieves + grounded cited answer,
  no spiral; **dialectic** unchanged; **strict** unchanged. `compare` (dead — identical to
  dialectic) **removed**. Adaptive escalation: a chat turn naming the library → search
  (Self-RAG). Verified online: chat (0 evidence, ~100 chars) · search (grounded, no rungs) ·
  dialectic (2 rungs) · strict · "tell me about the Muqaddimah" → search. New router regression
  test (`tests` 9/9). App receives the mode via `meta.route_reason`.
- 2026-09-23: **Thread continuity fixed (evidence-based).** A follow-up in the essay thread
  (`find me quotes…`) was routed **strict**, and strict was the one path that dropped **both
  the history and the document** → "continuity lost." References: **DeepSeek** (stateless —
  always concatenate prior turns), **OpenAI** (thread + compaction), **LlamaIndex**
  CondenseQuestion. Fixes: (1) **no mode drops the thread** — `strict` now includes history;
  (2) **document precedence** — a conversation with a document stays `document` mode for every
  follow-up (doc + history + library evidence); (3) **condense** short/anaphoric follow-ups
  into a standalone query with history before routing/retrieval; (4) **compaction** — older
  turns summarized into `conversations.summary` (no silent 6000-char drop; prior answers kept
  at 1000 chars); (5) the app **persists the active conversation** and restores it on launch.
  Acceptance: 3-turn document thread → all `document:online`, one thread. `tests` 10/10.
- 2026-09-23: **Appearance + 2-column reading (referenced).** Dark↔Hue bug: appearance was
  **baked into the OKLCH theme** (`ColorControls.light/monochrome` from `AppTheme`) and the
  toggle re-ran **full image analysis** async (cancellable → stale/monochrome palette) + `.id(theme)`
  rebuilds the rail. Fix (refs: Apple HIG Dark Mode; Material 3 dynamic color — one seed →
  light+dark schemes; CSS multicol): appearance is now a **composition** — `Palette.forTheme`
  returns Mono grayscale for `.mono` else the image theme — and `Engine.setAppearance` swaps
  **O(1)** from the **cached** palette + region samples (no re-analysis), crossfaded unless
  Reduce Motion; removed `.id(theme)`. Reading columns defaulted **3→2** (`maxColumns`,
  our `column-count`; one-time migration of the saved token) — verified persisted
  (`typography.maxColumns: 2`). App rebuilt.
- 2026-09-23: **Process lifecycle — restart-with-new-code (root cause of the "whats up"
  dialectic).** The engine never hot-reloads and the app reused whatever was on :8765, so a
  stale process ran old code invisibly. Fix (reference: gunicorn `pidfile` + systemd/uvicorn
  graceful shutdown): the engine writes `mentat2_data/engine.pid`, **reaps its predecessor**
  on start, exposes **`POST /shutdown`**, and `/status` returns a **`code` id** (git hash +
  newest `mentat2/*.py` mtime). `EngineProcess` now **retires any running engine on launch**
  and starts fresh. Verified: B reaps A, pidfile tracks the live pid, `/shutdown` frees the
  port; fresh engine routes `whats up`→chat, lookup→search, dialectic→dialectic.
  Also: social→chat fires only for **primarily-social** messages (greeting + no
  dialectic/library content), so "what's up with the master/slave dialectic" → dialectic.
- 2026-09-23: **File attachments (drag-and-drop) + `ARCHITECTURE.md`.** The composer now
  accepts **drag-and-drop and a paperclip** (Qwen/DeepSeek/Kimi/ChatGPT UX): file chips
  (name·size·✕), sent as `attachments:[{path,name}]`; the engine extracts text via
  `extract.py` (v1's txt/md/html/pdf+OCR/epub/docx, +csv/code) and routes a **`document`**
  mode (edit/critique/rewrite), keeping the document **per conversation** (`documents` table)
  so follow-ups continue editing; re-attaching replaces (no dupes); unreadable/unsupported
  files don't force document mode. New **`app/ARCHITECTURE.md`** = the living *structure*
  source of truth (TRUTH.md stays the goals/decisions truth). Verified end-to-end: attach →
  document, follow-up → document, bad/missing/space-path files → no crash, delete removes docs.
  App rebuilt.
- 2026-09-23: **Composer: scrolling input + paste-to-file + “+”.** Replaced the capped
  `TextField` (which clipped long messages with no scroll) with `ComposerTextView` (AppKit
  `NSTextView`): grows then **scrolls internally**; **Enter sends / Shift+Enter newline**;
  **paste > 2000 chars or > 15 lines → a `.txt` attachment** under
  `mentat2_data/attachments/` (Qwen/Kimi behaviour); file drag-and-drop; leading **“+”**
  (accent) replaces the subtle paperclip. The app now also **stops the engine on quit**
  (`applicationWillTerminate` → pidfile SIGTERM), so quitting frees the port + RAM. App rebuilt.
- 2026-09-23: **System-wide online benchmark (`mentat2.eval.bench`) + fixes.** Controlled per-stage floors
  (online): bm25 ~2 ms · vector ~35 ms · retrieve ~190 ms · claims ~0.4 ms (cached) · attacks ~0.8 ms cold
  (NLI + embed model load; cached warm) · loop ~5 s (2 sublation calls) · writer ~5 s · total ~11 s.
  Retrieval quality: **top-1 6/8, in-top-6 8/8** (misses are same-series books) · **census exact**
  (1591=1591). Flaws found & fixed: **loop ran NLI twice per claim** (preserve + new-immediacy) → now
  **one batched pass reused by the Return**; added `gateway.nli_batch` (batched cross-encoder — measured
  ~1.1× on 24 pairs, so modest, but halves the loop's NLI work) and wired it into `metrics.faithfulness`.
  Confirmed **online still uses local helpers** (embed/rerank/NLI) — intentional for an offline-first,
  zero-cost app (reference: API rerankers exist but cost; local is fine here).
  Backlog: a stronger reranker (bge-reranker-large/Cohere) for same-series top-1.
- 2026-09-23: **Latency work (reference-checked).** The "29 s" was a **cold model load**, not
  a quirk. Built on vLLM Automatic Prefix Caching ("free lunch, no output change"), vLLM
  MTP/speculative decoding ("lossless"), and Ollama `keep_alive`:
  - **Warm start**: the engine preloads the local model on launch; `keep_alive` 30 m
    (`LOCAL_KEEP_ALIVE`), idle unload. Cold was **11.1 s** (7.7 s load) → warm **2.8 s**.
  - **End-to-end offline (warm): first token 7.3 s, total 14.3 s** (was 29 s / 36 s),
    grounded 0 ungrounded. Prefix cache makes warm prefill ~0 ms.
  - **Movement cache** (`loop`): the spiral is a pure function of (query, evidence, brief
    model, max_rounds), so it's reused across turns/regenerations — the writer still
    re-samples fresh prose. Lossless.
  - **Context sizing**: dropped the 16k `num_ctx` floor → size KV to the prompt (8k min).
  - **MTP / `draft_num_predict` tested → no gain** for this MoE under Ollama (124.0 vs 124.8
    tok/s); left **off** by default. Honest negative result.
  - Duration telemetry (load/prefill/decode ms) now recorded per stage; fixed the latent
    `writer_think` default.
- 2026-09-23: **Audit fixes (references: PEP 20, pytest tmp-path, OTel).** Fixed the broken
  **MCP** `ask_brain` (`sublation.new_contradiction` → `new_immediate`; now returns
  product/invariants). **Tests + `doctor` now run against a throwaway DB** (`store.ephemeral`)
  — they no longer write to the user's real `v2.db`; live junk (test conversations, `diag`
  facts, orphan memory) was purged, a genuine user fact kept. Added a small **error sink**
  (`store.note_error`/`errors`, wired into previously-swallowed writes) and stopped `graph`
  eating guard errors. Dropped the unused `roles` metadata and dead settings
  (`claim_model`/`extract_limit`/`judge`); removed a duplicate function; unified `book_of`;
  replaced `__import__` shims; public `verify.norm/CITE/bound`; non-stream `/ask` now reports
  real token/cache usage. Deprioritized **P9** (distillation) to Backlog — low ROI here.
- 2026-09-23: **P5 Contextual Retrieval (done).** Built `mentat2/index.py` +
  `mentat2_data/ctx.db` per Anthropic's method: each chunk gets a short contextual prefix
  (`From <book> — <chapter>:`) **before** it is embedded and BM25-indexed (Anthropic's
  "custom contextualizer" variant — deterministic, free, no LLM). Resumable; full library
  indexed in ~3.3 min (8214 chunks) via `python -m mentat2.index`. `retrieve.bm25`/`vector`
  transparently use the contextual index when it fully covers the library, else v1. `doctor`
  reports coverage.
- 2026-09-23: **Latency: removed unused work.** The spiral ran a *full retrieval + rerank per
  rung* whose result only fed a telemetry string — deleted (an embed + cross-encoder pass per
  rung saved).
- 2026-09-23: **Reference pass + weird-behavior fixes.** Cross-checked against OpenAI
  (conversation-state guide), Anthropic, DeepSeek, RAG conventions:
  - **History window is now budgeted by characters** (`history_chars` 6000, `history_turns`
    8), not a fixed 4 turns — OpenAI manages context by size and compacts.
  - **Spiral convergence guard**: a product whose token-overlap with the immediate ≥ 0.9 is a
    fixed point → stop (no near-duplicate rungs). Loop is a bounded fixed-point iteration.
  - **Stable turn order by `rowid`** (was `created`, whole seconds → non-deterministic within
    a second; a real ordering bug).
  - **Attack-graph cache** (contradiction structure over a claim set is stable → skip repeat NLI).
  - **Assistant messages: Regenerate/Copy only** (no Delete) — matches ChatGPT/DeepSeek/Claude
    and avoids turn-index ambiguity; delete lives on user turns and removes the answer.
- 2026-09-23: **History rail edit/delete.** `ConversationCard` gained hover-revealed
  **edit (rename)** and **delete** buttons (+ menu items); `Engine.renameConversation`;
  `/conversation/rename` endpoint. App rebuilt (`MentatApp/build.sh`, Swift 6.4).
- 2026-09-23: **Single-model offline + tests.** Local helper model defaults to the writer so
  exactly **one heavy model** is resident (RAM-safe, no swap). Fixed `semantics.grounded`
  (unattacked claims were never IN — the grounded extension was broken). Added a model-free
  suite `python -m mentat2.tests` (contracts, invariants, verify, semantics, the spiral with a
  stubbed gateway, store, citations) — **8/8**. `diagnose` 15/15.

- 2026-09-24: **UI systematization — the app *is* the system (no prototype).** An earlier
  standalone `MentatShell` target (interface-as-data prototype) was **built, tested, then
  rejected and deleted** — it had no design DNA and shared nothing with the shipping app. Pivot:
  systematize the shipping app in place, modelled on **DeepSeek Harness** (`dsh`, MIT: modular
  UI packages composed via a named **slot** system + one `--dsw-*` token namespace) and the
  **Qwen**/**Kimi** product anatomy (model picker; session files; context meter;
  artifacts/inspector); canonical chat = left rail · capped centre stream (~720–768 px) ·
  optional right panel. Direction locked: Apple-native material/tonal with **Liquid Glass as one
  `MaterialRole`** (not the rule); target shell = rail · capped centre stream · collapsible right
  Inspector (artifacts · citations · source · files · context meter). Sacred (kept): layout
  armature + baseline snapping, adaptive ink from artwork + OKLCH, wordmark hero / quiet band,
  debug/layout tools, and the drip-down glass menu → vertical floating icon bar.
  **Phase 0 (done):** deleted dead code — `SettingsMenu`/`SettingsSheet`, `ThemeToggleButton`,
  `GridLinesLayer`, `StarField`, `PaletteGraph`, `NestedShape`, `BubbleSurface`/`.bubble`,
  `.glassButton`, and the entire legacy colour system (`ColorPalette.swift` + `Engine.analysis`
  / `PaletteStore`). **Phase 1 (done):** added token groups `space` (8-pt grid) · `material`
  (`MaterialRole`) · `elevation`; added `DesignSystem/Primitives.swift` — `.surface(role:…)`
  plus `MentatChip`/`MentatPanel`/`MentatListRow`/`MentatBadge`/`MentatEmptyState`; accessors
  `Spacing.*`/`Elev.*`. Verified: builds clean; tests **41/41** (+6 new token tests); app
  launched, no visual regression.
  **Phase 2 (done):** added the DeepSeek-Harness-style **`SlotRegistry`** (named slots in the
  Environment, `SlotView` renders them) + **`AppFrame`**, giving the real 3-pane shell — left
  rail, capped centre column, and a collapsible right **Inspector** (`InspectorPane`:
  Citations · Source · Files · Context with a token meter; state in `InspectorStore`, toggled by
  ⌘I or the hero-layer disc). Verified: builds clean; tests **44/44** (+3 slot tests);
  screenshot-confirmed the Inspector with a live citation.
  **Phase 3 (done):** one **`Command` registry** (`Commands/Command.swift`) — id · title · help ·
  icon · section · kind (`.slash` runs a server command, `.ui` resolves a `UIAction` through
  `\.runUIAction`) — now feeds the `/` menu, the ⌘K palette (grouped, with icons + shortcut chips),
  the debug tool rail, and the menu-bar "Mentat" menu, replacing `CommandItem` + `DebugTool` +
  hardcoded menu buttons. One **`SettingSection.group`** is the single grouping rule for the
  Settings panel and the Developer panel. Verified: builds clean; tests **51/51** (+7); palette
  screenshot-confirmed.
  **Phase 4 (done):** the Conversation module (`Screens/Conversation/`) — a Qwen-style
  **`ModelPicker`** replaces the static model pill (options come from the engine's settings
  spec: deepseek-flash, deepseek-v4-pro, qwen3.5:35b-a3b-nvfp4, qwen3.8:27b-mlx, qwen3.8:27b,
  qwen2.5:7b; health refreshed on switch) — and the Inspector gained an **Artifacts** tab
  (`ArtifactParser` lifts fenced code blocks into copyable cards; 5 tabs now). Verified: builds
  clean; tests **56/56** (+5 artifact tests); screenshot-confirmed.
  **Phase 5 (done):** the floating debug panel became a first-class **Developer scene**
  (`Screens/Developer/DeveloperScene.swift`): header "DEVELOPER", registry-driven tool chips,
  Grid & Armature, Colour system · OKLCH, the design-token editor (`DesignPanel`), the perf HUD,
  and the niche settings — plus a **`developerPanels` slot**; `EngineInfoPanel` (model · status ·
  build · route/tokens) registers into it from `RootView.init`, so the scene holds no hard-coded
  tooling. `SlotRegistry` is now `@Observable`. Also gave the right-hand Inspector toggle a
  distinct glyph (`rectangle.righthalf.inset.filled`, was a mirror of the history `sidebar.left`).
  Verified: builds clean; tests **56/56**; screenshot-confirmed the ENGINE slot panel inside the
  scene.
  **Phase 6 (done):** one material mechanism — `ShapeSurface`/`SurfaceStyle` resolve **any**
  shape from a `MaterialRole` (`material · tonal · outline · solid · glass`), replacing the
  ad-hoc blur/fill/stroke literals on the chrome (settings pills, developer chips + section
  cards, find field, suggestion list, offline banner). The default role is the token
  `DesignTokens.material.role` (`.tonal`, Apple-native), with a segmented picker in the Developer
  scene's Design panel; switching it re-skins the app live (verified tonal ↔ glass). Glass is now
  one role, kept for floating controls. Verified: builds clean; tests **56/56**; two screenshots
  (tonal default, glass role). **UI systematization P0–P6 complete.**

## 12 · Backlog (each with a reason)
- Higher quant (Q5/Q6) quality check; a second MoE sibling.
- DSPy/GEPA prompt compile (after eval-as-spans).
- Local distillation of a small writer from verified online traces (only if needed).
- ColBERT / late interaction (index overhead not justified at 8k chunks).
- GraphRAG/HippoRAG global search (LLM indexing cost unjustified at this scale).
- Full online-only path (cloud embed/rerank/NLI) — helper seam abstracted, cloud helpers
  not chosen (local cross-encoders are faster and cost-free).
- Voices/lenses cosmetics (out of scope for brain quality).

## 13 · Phase status (current only)
- [x] P0 — this document.
- [x] P1 — registry + serving fairness.
- [x] P2 — pipeline-as-data (`graph.py`).
- [x] P3 — offline runtime/quant benchmark.
- [x] P4 — cache-first prompt block + structured grounding/citations.
- [x] P6 — bi-temporal memory.
- [x] P8 — MCP front-end.
- [x] P10 (partial) — offline default = MoE.
- [x] **Spiral** — engine rewritten to the Aufhebung spiral (contracts, loop, invariants,
  memory, telemetry, diagnosis). Online + offline validated.
- [x] **Head-to-head** — offline default = MoE `qwen3.5:35b-a3b-nvfp4`; MLX dense → fallback.
- [x] **Parity tests** — thinker-only (3.8 > MoE > 7B); end-to-end vs online reference.
- [x] **Writer=describer** — thinking off; content no longer starved.
- [x] **P8b app cut-over** — `server.py` → `mentat2.fronts.server` on :8765, full contract.
- [x] **P10 streaming** — `/ask/stream` ndjson + token streaming.
- [x] **Tests + scorecard** — `python -m mentat2.tests` (8/8), `cli doctor` (15/15),
  `python -m mentat2.eval.scorecard`.
- [x] **Continuous chat** — conversations (threads, turns, history window, cross-turn spiral),
  history-rail edit/delete/rename, thread-local store, app rebuilt.
- [x] **Message actions** — per-message edit/delete/regenerate with interrupt; engine-owned
  truncate/delete_turn (single source of truth).
- [x] **Lean + span citations** — dead code purged; `span_hunt` → page-accurate citations;
  faithfulness in the scorecard.
- [x] **P5 contextual retrieval** — `mentat2_data/ctx.db` built (8214/8214), retrieval uses it.
- [x] **Latency** — warm start + keep_alive + prefix cache + movement cache; warm offline
  first token 7.3 s / total 14.3 s (was 29 s / 36 s). MTP tested (no gain, off).
- [x] **Chat/search routing** — intent router (chat | strict | search | dialectic), auto-detected;
  normal chat works, no forced dialectic. `compare` removed.
- [x] **UI Phase 0** — dead code + legacy colour system deleted; app is the system (no shell).
- [x] **UI Phase 1** — tokens (`space`/`material`/`elevation`) + `Primitives.swift` surface roles;
  tests 41/41.
- [x] **UI Phase 2** — `SlotRegistry` + `AppFrame`; 3-pane shell (rail · capped stream ·
  right Inspector: citations/source/files/context, ⌘I toggle); tests 44/44.
- [x] **UI Phase 3** — one `Command` registry (slash + UI actions) feeding `/`, ⌘K, debug
  rail, and the menu bar; one `SettingSection.group` for all settings surfaces; tests 51/51.
- [x] **UI Phase 4** — Conversation module: Qwen-style `ModelPicker` in the composer (reads the
  engine's model options, refreshes health on switch) + Inspector **Artifacts** tab
  (`ArtifactParser` for fenced blocks); tests 56/56.
- [x] **UI Phase 5** — Developer scene (`Screens/Developer/`) with registry tools, armature,
  colour, token editor, perf HUD, niche settings; `EngineInfoPanel` registered via the
  `developerPanels` slot; Inspector disc given a distinct glyph
  (`rectangle.righthalf.inset.filled`).
- [x] **UX unification (P7–P9)** — token graph (W3C aliases/composite types + `.tokens.json`
  I/O); bubble element (token-driven material + opacity, distinct user/assistant, legibility
  floor); dsh slot kinds + declaration discipline. Interface source of truth: `UX.md`.
- [~] **UX generative slice (P12)** — model-authored `SceneSpec` (KPI/chart/table/diagram)
  rendered via an element registry + sandboxed HTML widgets. P10 (one store) + P11 (authoring)
  pending.
- [x] **UX visibility pass** — Looks studio (Atlas/Noir/Paper presets + live controls) with a
  new frosted **Atlas** default, distinct inspector icon, generated views rendered inline, and
  right-click bubble restyling. The system is now felt, not just built.
- [x] **UX surface-first rebuild** — colour is a closed set of surface+ink roles
  (`SurfaceLook` system/paper/mono/noir → `ColorTheme.look`), not image-sampled. No photo behind
  reading text; artwork is an optional sidebar/hero accent. Messages are plain prose + a
  subtle user surface. Paper is a real warm theme again. **Purged** the image-driven
  legibility subsystem (`BubblePlate`/`Legibility`/grid/frame sampling) and its tests.
- [x] **Semantic text + chrome** — `TextInk` colours headings/quotes/links/numbers/citations
  per look (wordmark = brand sand); inspector folded into the hamburger rail as an in-content
  pane (native `.inspector` removed — it resized the window); `HideTrafficLights` crash fixed
  (deferred, change-guarded window mutation).
- [x] **Shell + polish** — native `.inspector` (AppFrame deleted); titlebar safe-area inset
  (no clipping); white wordmark with **no halo/glow**; non-destructive background hidden set;
  `design-review` skill for worst-case, reference-cited visual review.
- [x] **Sand surface (Metal)** — the default canvas is a fragment shader (`SandCore/`):
  **Langevin dust** in a dark room, lit by a **volumetric light engine** — the shaft is a
  **screen-space ray-march** through the medium (an integral, so it reads as light in air, not a
  painted cone), **supersampled 2× and temporally accumulated** (light-only) so it is free of
  jagged edges. It's a real **beam system**: one source, a fan of **distinct beams**
  (a mix of big and small/sharper ones) with near-black gaps, wavering and flickering — no
  pointer coupling. Distance is **Beer–Lambert extinction**. The beams are the
  **light source for the dust** (same field → flicker syncs; Tyndall). Dust is **four parallax
  depth layers** (nearer = faster across the screen; big soft spice bokeh in front) with
  **per-layer debug toggles** (Developer scene). One **exposure + ACES tonemap** keeps additive
  light off white; sparkles are **spice-orange**; a subtle static dither hides banding. Motion is
  a **sum of decaying impulses** (`SandMotionStore`, `exp(-dt/τ)`) now plumbed to the GPU, with
  global moves as **forces (no full-span walls)**. Adaptive cadence (120 active → 60 rest → paused
  on Reduce Motion / inactive / Low Power). `SandStyle` + `SandMotion` + `DesignTokens.sand`
  (data-driven); `build.sh` compiles `SandShaders.metal` → `default.metallib` (needs the Metal
  Toolchain; Canvas fallback otherwise). `app/SandLab/` is the live-slider tuning harness; see
  `SandCore/TRUTH.md` for the doctrine.
- [x] **UX motion pass** — Apple-referenced motion: spring presets + `gentle`/`pop`, a
  reduce-motion `.motion(_:value:)` modifier, symbol effects as state (pulsing `sparkles`
  while streaming, bouncing send/toggles/actions), and `defaultScrollAnchor(.bottom)` to kill
  per-token scroll jank.
- [x] **UI Phase 6** — one material mechanism (`ShapeSurface`/`SurfaceStyle` over `MaterialRole`);
  chrome surfaces migrated; token-driven default role (`.tonal`) with a picker in the Developer
  scene; glass demoted to one role. **The UI systematization (P0–P6) is complete.**
- [ ] **P9 distillation** — Backlog (low ROI).

## 14 · Open plans (approved · NOT yet executed)

> Written 2026-10-01. **Sand/UX is done** (see [`SandCore/TRUTH.md`](SandCore/TRUTH.md) §4/§11).
> This section now tracks the engine work: execute in order A → B. Nothing is done until it is
> moved into §13 with a dated line.

### Plan A — Citation integrity + full-passage reader (engine `mentat2`)
**Status:** approved, not executed. **No re-index required** (all fixes are query-time).

**Problem (verified against live data).** v2 dropped three v1 mechanisms, so citations are junk:
- **No front/back-matter filter.** `mentat2` indexes and retrieves every chunk; `storage/library.db`
  holds **332 obvious boilerplate chunks** ("PRAISE FOR…", "ACE… Penguin Random House… Copyright ©",
  "CONTENTS", "INTRODUCTION (ch6)"). v1's filter (`brain_core.py:3508-3571`, `_is_boilerplate` /
  `_boiler_section_of` / `_query_sections`, applied at `4117/4181/4971/7088`) was not ported.
- **Labels are spine indices / filenames.** `retrieve.to_passages` (`retrieve.py:186-198`) sets
  `loc = c["chapter"]` (a 1..N file-order number) and `work = book_of(file_path)` (raw filename).
  The real heading is already in `file_path` (`… · Chapter 44 (ch50)`). v1's `_citation_for` /
  `_display_book` / `_PDF_DISPLAY` (`brain_core.py:8459-8514`) handled this.
- **No label validation.** `pipeline.citations_of` (`pipeline.py:302`) and Swift
  `Engine.extractCitations` (`Engine.swift:758`) treat any `(… · …)` as a citation.

Observed junk in stored answers: `Kojeve_IntroToHegel.pdf · Introduction to the Reading of Hegel`
(×9), `… · In Place of an Introduction` (front matter), `Children of Dune · 6` (Brian Herbert intro),
`Dune Messiah · 6` (death-cell interview = front matter), `Children of Dune · 50` (really Ch.44),
`The Muqaddimah · p. xxx`, `book · location` (template leak).

**Steps.**
1. New `mentat2/boilerplate.py` (port v1's filter verbatim; extend signals with `published by`,
   `copyright ©`, `isbn`). Apply in `retrieve.retrieve()`, `hunt()`, `span_hunt()` before rerank;
   pass `_query_sections(query)` so explicit front-matter asks still work.
2. New `cite_label(file_path, content)` → clean work (strip ext + trailing `(Author)`, `_PDF_DISPLAY`
   map, de-underscore) and loc from the ` · ` marker minus `(chN)`; PDFs derive `p. N` from the
   nearest `## Page N`. Use in `to_passages()` and `span_hunt()` so `writer._evidence_block` gets
   real labels.
3. Guard the extractors: drop `book`/`location` placeholders and empty locs in `pipeline.citations_of`
   and `Engine.extractCitations`.
4. `writer._CITE` (`writer.py:5`): cite the text only, never front matter, use the exact label given.
5. `/ask/stream` runs the same verify → repair → strip as `/ask` (`pipeline.py:369-389`).
6. **Full-passage reader:** each citation carries its `chunk_id`; `/passage` (`server.py:155`) accepts
   it and returns the **whole section** (all chunks of that book+chapter), quote highlighted;
   fall back to book·loc for old answers. Touch `Models.swift` (`Citation`), `MentatClient.swift`,
   `Engine.openSource` (`Engine.swift:307`), `SourceReader.swift` (already paginates).

**Verify:** re-ask a saved question → no front-matter / `p. xxx` / spine-number citations; tapping a
citation opens the full section; `python -m mentat2.tests`; `cli doctor`.

**Related engine gaps (from the v1→v2 audit; not in Plan A, log for later):**
front/back-matter filter (above) · telemetry-driven learn-to-rank + reask demotion (v1
`brain_core.py:3901-4086`) · spelling/phonetic quote rescue (v1 `_phonetic_match:909`) · cross-book
sweep / scope / whole-book mode (v1 `_resolve_scope:4856`, `book_ask:11892`) · `graph.db` never
opened (`store.py:121-136`) · bi-temporal facts write-only · dead code
(`semantics.new_contradictions`, `eval.metrics.context_relevance`, `registry` `plan` job, `attacks`
never emits `undercut`/`defeater`) · `loop._MOVE_CACHE` key omits claims · `store.ephemeral` misses
`CTX_DB`. §6 claim of **sentence-window + auto-merge** is not implemented — correct §6 or build it.

### Plan B — Artifacts usefulness + Inspector tab order (app)
**Status:** approved, not executed; lands **after Plan A**.

- **Reorder** `InspectorTab` so the icon row is **Citations · Source · Files · Artifacts · Context**
  (`InspectorStore.swift:6-28`); the strip renders `allCases` (`InspectorPane.swift:70-94`) so order
  follows the enum. Persisted selection is by rawValue → unaffected.
- **Make artifacts earn their place.** Add an intent/prompt rule so the writer emits a ` ```scene `
  (or ` ```html `) block for comparison / count / map / structure asks, plus a few library templates:
  the **dialectic diagram** (render the computed claim→attack spiral), a comparison table, a **census
  bar chart**, and a relationship/family diagram. Optional: pin/save an artifact to the conversation.
  Machinery already exists: `ArtifactParser`/`ArtifactsView.swift`, `SceneParser` (`GenerativeUI.swift`),
  `GenCards.swift`, `HTMLWidget.swift`.

## 15 · References (verified ✓ unless noted)
- **Pipelines:** LangGraph `StateGraph`; Haystack `Pipeline`; LlamaIndex Workflows.
- **Retrieval:** Anthropic Contextual Retrieval ✓ (`anthropic.com/news/contextual-retrieval`);
  LlamaIndex `SentenceWindowNodeParser`/`AutoMergingRetriever`; Haystack `DocumentJoiner`
  (RRF); RAGFlow span citations.
- **Argumentation/memory:** Dung AF; AGM entrenchment; TMS/ATMS; Graphiti bi-temporal;
  Mem0; Letta; Generative Agents.
- **Reasoning/verification:** Self-RAG, CRAG, CoVe, RARR; DSPy; RAGAS; G-Eval; MT-Bench.
- **Serving/registry:** Ollama API ✓ (`github.com/ollama/ollama/docs/api.md`: `think`
  levels, `format` JSON-schema, `keep_alive`, usage fields); DeepSeek ✓
  (`api-docs.deepseek.com/guides/kv_cache`: automatic prefix caching, `prompt_cache_hit_tokens`;
  `quick_start`: `deepseek-flash`/`deepseek-v4-pro`, `thinking`/`reasoning_effort`); vLLM;
  SGLang; llama.cpp; LiteLLM; OpenRouter; MCP `MCPServer`.
- **Dialectic theory:** Hegel (EL §79–82: abstract/dialectical/speculative; Aufhebung;
  determinate negation); Kojève (the real dialectic; the spiral; Master–Slave; memory);
  Stalin 1938 (four features); Marx (materialist inversion; being determines
  consciousness).
- **Not yet verified:** OpenTelemetry GenAI semantic conventions (internal telemetry only).
