# ARCHITECTURE.md — Mentat v2

A **living** map of the system: module responsibilities, data flow, contracts, and the
reference each mechanism copies. Keep it current — rewrite at phase boundaries, not append.
`TRUTH.md` is the *goals/decisions* source of truth; **this** is the *structure* source of truth.

Owner: Raphael · Machine: Apple M5 Max, 48 GB RAM · Offline-first.

---

## 1 · Topology

```
┌─────────────────────────────┐        HTTP 127.0.0.1:8765       ┌──────────────────────────────┐
│ Mentat.app (SwiftUI)        │  /ask · /ask/stream (ndjson)      │ engine: mentat2.fronts.server │
│  Engine (@Observable)       │  /conversations · /conversation   │  (python -m … or server.py)   │
│  EngineProcess (actor)      │  /books · /book · /passage        │                               │
│  MentatClient (typed HTTP)  │  /settings · /command · /status   │  pipeline.ask / ask_stream    │
│  ChatView / MessageRow      │ <───────────────────────────────> │  gateway (only model access)  │
└─────────────────────────────┘                                   └──────────────┬───────────────┘
        │ spawns/retires                                                    │
        ▼                                                                   ▼
  server.py launcher                                              Ollama (local models) + DeepSeek (online)
  (+ engine.pid)                                                  + local cross-encoders (rerank/NLI)
```

- The app **owns** the engine process: on launch it **retires any running engine and starts a
  fresh one** (a fresh start must run current code — the engine has no hot reload); on **quit**
  it terminates the engine (via the pidfile), freeing the port + RAM.
- **Process lifecycle** (ref: gunicorn `pidfile`, uvicorn/systemd graceful shutdown):
  engine writes `mentat2_data/engine.pid`, **reaps its predecessor** on start, exposes
  `POST /shutdown`; `/status` returns `pid` and a `code` id (git hash + newest `mentat2/*.py`
  mtime).

### App UI (`MentatApp/Sources/MentatApp/`)
- `Engine` (@Observable) — state, transcript, attachments, calls `MentatClient`.
- `EngineProcess` (actor) — spawns/retires/kills the engine; health.
- `MentatClient` — typed HTTP for every route.
- `ChatView`/`MessageRow` — transcript + composer. **Composer** = `ComposerTextView`
  (AppKit `NSTextView`): grows then **scrolls**; Enter sends, Shift+Enter newline;
  **paste > 2000 chars / > 15 lines → a `.txt` attachment chip** (Qwen/Kimi behaviour);
  file drag-and-drop; leading **“+”** attach.
- **Theme & appearance** — surface-first, **one authority**. Colour resolves from
  `DesignTokens.look` (`SurfaceLook`: system/paper/mono/noir, default **noir**) →
  `ColorTheme.look(_:isDark:)`, published on `Engine.colorTheme` and mapped to `Palette`
  by `Palette.from(_:)`. `AppTheme` is only light/dark, and only matters for `.system`.
  **No image sampling anywhere.** The wallpaper subsystem is deleted: no bundled photos,
  no `BackgroundAnalysis`/`ImageAnalyzer`/`ColorResolver`/`ColorControls`/`PaletteScheme`,
  no `artworkAccent`. The app ships **no art** — the only background is the procedural
  sand. Reading columns cap = `DesignTokens.typography.maxColumns` (default **1**, single
  column) — `TextStyle.measure` as `column-width` (CSS Multi-column).
- **Sand surface (`DesignSystem/Sand/`)** — the procedural canvas behind the reading text,
  and the app's only background. A Metal fragment shader (`SandShaders.metal`) draws
  near-black with **dust in five parallax depth layers** lit by a fan of **crepuscular light
  beams** from one source (a moving big/small noise field — light through a cloud), plus a
  haze band, bloom, and an in-shader **dither** that kills 8-bit banding. The light is the
  only light source for the dust (a mote lights up inside a beam). `SandStyle` (look) +
  `SandMotion` (couplings) → `SandCanvas`. **The sand doctrine is
  [`SandCore/TRUTH.md`](SandCore/TRUTH.md)** — read that for the model.
  **It is always alive.** An ambient clock (`at = time·ambient`) drives the travel; motion is
  a sum of decaying impulses (`SandMotionStore`, `exp(-dt/τ)`) on top — framerate-free,
  interruptible. Events arrive through the `\.sandMotion` environment seam (`SandEvent`: send ·
  panel · scroll · modeChange · resize · pulse) with an **amplitude ladder**: pointer/scroll are
  tiny, panels/send/mode are bigger — calm by default, surging on big moves, never fully still.
  The store is `@MainActor @Observable`; only the sand leaf reads it, so hover/scroll never
  invalidate the transcript. **Cadence adapts** (120 fps while interacting → 60 fps at rest →
  paused under Reduce Motion / inactive scene / Low Power; never 30). The light is a **single
  pass at half resolution**, upscaled (soft, so no visible loss) — the dominant GPU cost after
  the earlier march/supersample/TAA removal; the dust runs five depth layers (Close-up · Near ·
  Mid · Far · Haze). The shader falls back to a Canvas approximation when the library is
  absent, so dev builds/tests never go blank. Compilation is a **`build.sh`** step
  (`SandShaders.metal` → `default.metallib` in `Contents/Resources`, found by
  `ShaderLibrary.default`), so SwiftPM never sees the `.metal`. Needs the Metal Toolchain
  (`xcodebuild -downloadComponent MetalToolchain`). Data-driven via `DesignTokens.sand`
  (`enabled · intensity · waveScale · warp · drift · grain · scrim · ambient · wander ·
  grainFlow · colorShift · idleWindow · impulseScale`), which overrides `SandStyle.noir`; the
  values also round-trip through the token graph (`TokenCatalog`, `sand.*`). The standalone
  `app/SandLab/` harness compiles **the same shader** (single source of truth) with live sliders.

---

## 1b · Design system & UI architecture (the systematization)

> Interface source of truth: **[`UX.md`](UX.md)** (tokens · element catalog · composition · actions · generative UI).

The shipping app **is** the system — no parallel prototype. Everything routes
through one token vocabulary, one primitive library, and (next) one modular
layout with a named slot registry, modelled on **DeepSeek Harness** (`dsh`, MIT)
+ **Qwen**/**Kimi** product anatomy. (An earlier standalone `MentatShell` target
came and went — it was rejected for having no design DNA — and has been deleted.)

**Tokens (`DesignSystem/DesignTokens.swift`).** One `DesignTokens` (Codable,
tolerant `AnyKey` decode) holds every group: `typography`, `motion`, `metrics`,
`composition`, `chrome`, `inspector`, plus **`space`** (8-pt grid), **`material`**
(`MaterialRole`), **`elevation`** (one shadow per level). Read live via
`DesignTokens.current`; accessors `Spacing.*`, `Elev.*`, `TypeScale.*`,
`ChromeShape.*`. Persisted to `UserDefaults["designTokens"]`; migrations are
additive and only ever raise legibility (`columnsMigrated1/2`, `legibilityV1`).

**Material roles (`DesignSystem/Primitives.swift`).** `MaterialRole` =
`material | tonal | outline | solid | glass` — **glass is one option, not the
rule**. One `.surface(role:corner:tint:elevation:interactive:)` modifier resolves
all of them (Reduce Transparency falls back to material). No view hand-rolls its
own blur/fill/stroke/shadow.

**Primitives.** `MentatChip`, `MentatPanel`, `MentatListRow`, `MentatBadge`,
`MentatEmptyState` — one implementation each, replacing the app's duplicated
chip / panel / settings-row recipes.

**Shell & slots (`Layout/`, `Slots/`).** `AppFrame` composes the detail region:
the capped centre column plus an optional, collapsible right **Inspector**
(`InspectorPane` — citations · source · files · context, with a token meter),
animated in/out, toggled by ⌘I or the hero-layer disc. Its state lives in
`InspectorStore` (persisted). A DeepSeek-Harness-style **`SlotRegistry`** (named
slots carried in the Environment; `SlotView` renders them) is the seam features
register into instead of editing the shell.

**Commands & settings.** One `Command` registry (`Commands/Command.swift`)
defines each command once — id · title · help · icon · section · kind
(`.slash` → `engine.runCommand`, `.ui` → a `UIAction` resolved by the shell via
`\.runUIAction`) — and feeds the `/` menu, the ⌘K palette, the debug tool rail,
and the menu-bar "Mentat" menu, so they can never drift. One
`SettingSection.group` (`Screens/Settings/SettingsSchema.swift`) is the single
grouping rule for both the everyday Settings panel and the Developer panel.

**Materials (`DesignSystem/Primitives.swift`).** Every surface resolves through
`ShapeSurface`/`SurfaceStyle` from a `MaterialRole` (`material · tonal · outline ·
solid · glass`), so a blur, a themed fill, a hairline, an opaque fill and Liquid
Glass are one mechanism — glass is now **one role, not the rule**. The default
role is `DesignTokens.material.role` (default `.tonal`, Apple-native) and is
editable from the Developer scene's Design panel; switching it re-skins the chrome
(settings pills, chips, section cards, find field, suggestion list, offline
banner). Glass is kept for the floating controls (hero discs, composer, menu).

**Developer scene (`Screens/Developer/`).** A first-class panel (revealed by
`/debug` or ⇧⌘D): registry-driven tool chips, `Grid & Armature`, the design-token
editor (`DesignPanel`), the perf HUD (`PerfHUD`), and the niche settings. Tooling
that doesn't belong in the scene registers through the
**`developerPanels` slot** — the `EngineInfoPanel` (model · status · build ·
route/timing/tokens) is registered from `RootView.init`, not hard-coded.

**Conversation module (`Screens/Conversation/`).** The composer carries a
Qwen-style **`ModelPicker`** — it reads the model list from the engine's settings
spec and refreshes health on switch, so the pill reflects the serving model. The
Inspector's **Artifacts** tab lifts fenced code blocks out of the current answer
(`ArtifactParser`) into copyable artifacts.

**Target shell anatomy (canonical chat):** left **rail** (history) · centre
capped **message stream** (~720–768 px, single column) · right collapsible
**Inspector** (artifacts · citations · source · files · context) — all three panes
implemented (P2), with the model picker and artifacts tab added at P4.

**Reference mapping.** Apple native material/tonal (Liquid Glass demoted to one
role) · DeepSeek Harness (modular packages + named slots + one token namespace) ·
Qwen (model picker, compare, artifacts/preview) · Kimi (session files, context
meter) · VSCO Capture (art-first strip) · Safari Reader (measured single column) ·
Apple Journal (timeline + suggestion seeding).

**Migration phases:** P0 dead-code + unification ✓ · **P1 tokens + primitives ✓** ·
**P2 slot registry + AppFrame + Inspector ✓** · **P3 unified Commands + Settings ✓** ·
**P4 Conversation module (model picker + artifacts) ✓** · **P5 Developer scene ✓** ·
**P6 materials/theme ✓** — systematization complete.

---

## 2 · Module map (`app/mentat2/`)

| module | responsibility | key API |
|---|---|---|
| `config.py` | typed config + env bridge; settings load/save | `load_settings`, `DEFAULTS`, `LOCAL_WRITER`, `LOCAL_KEEP_ALIVE` |
| `registry.py` | models-as-data + job→params resolver + usage normalizer | `resolve(job,model)`, `normalize_usage` |
| `gateway.py` | **the only** model access (ollama \| openai-compat); streaming; warmup; embed/rerank/NLI (batched) | `chat`, `chat_stream`, `warmup`, `embed`, `rerank`, `nli_batch` |
| `contracts.py` | the dataclasses that cross module lines | `Route, Claim, Attack, Sublation, Round, Verdict, Session, Span` |
| `router.py` | the one decider → `chat\|strict\|search\|dialectic\|document` | `route`, `classify` |
| `graph.py` | declared-stage runner (topology as data) + per-stage spans | `Graph.run` |
| `pipeline.py` | stage functions + `ask`/`ask_stream` | `ask`, `ask_stream`, `citations_of` |
| `retrieve.py` | BM25(FTS5)+vector(sqlite-vec)+RRF+rerank+hunt+span_hunt+census; contextual index | `retrieve`, `hunt`, `span_hunt`, `census`, `book_of` |
| `index.py` | Contextual Retrieval index builder (own db) | `build`, `status` |
| `claims.py` / `attacks.py` | claim per passage (cached); immanent contradiction (embed gate + batched NLI) | `claims_for_passages`, `find_attacks` |
| `semantics.py` | Dung grounded labelling | `grounded` |
| `loop.py` | the **spiral**: Round chain, Totality stop, Return to fixed point, movement cache | `run` |
| `sublation.py` | proposes the raised product (model); engine computes cancel/preserve | `build` |
| `invariants.py` | anti-triad rules (observed each turn) | `check_turn` |
| `writer.py` | renders modes: `chat`/`interpretive(search)`/`strict`/`dialectical`/**`document`** | `render_*` (+ `_stream`) |
| `verify.py` / `repair.py` | deterministic grounding; repair/strip ungrounded quotes | `check`, `repair`, `strip_unbound` |
| `extract.py` | attachment text extraction (txt/md/html/pdf+OCR/epub/docx/csv/code) | `extract_text` |
| `memory.py` / `store.py` | bi-temporal memory + all persistence | `prior`, `remember_*`; `save_*`, `truncate_conversation`, `documents_for`, `ephemeral` |
| `telemetry.py` | event spans (tokens/cache/load/prefill/decode); error sink | `record`, `summary` |
| `diagnose.py` / `tests.py` | diagnostic sweep; model-free self-tests | `run` |
| `fronts/` | `cli`, `server` (HTTP :8765), `mcp` (stdio) | — |
| `eval/` | cases, judge, metrics, bench, thinker, head2head, scorecard, runner | — |

**Principle:** the engine **computes** the structure; the model only **proposes/describes**.
All model calls go through `gateway`.

---

## 3 · Control graph (pipeline as data)

```
route → retrieve → census → claims → attacks → loop → write → verify/repair → memory → END
```
Stage gating by `route.mode`:

| mode | retrieve | claims/attacks/loop | writer |
|---|---|---|---|
| `chat` | – | – | `render_chat` (no citations) |
| `search` | ✓ | – | `render_interpretive` (cited, no spiral) |
| `strict` | ✓ (span_hunt for quotes) | – | `render_strict` (+ census facts) |
| `dialectic` | ✓ | ✓ | `render_dialectical` (fallback → interpretive) |
| `document` | ✓ (library evidence) | – | `render_document` |

`census` (deterministic count) runs only for strict + "how many/count". `verify/repair`
always runs. Empty evidence in search/dialectic → `render_chat` (don't dress up a failed
retrieval).

---

## 4 · Modes & the router

`router.classify` (auto-detected; ~no LLM): **whole-token** deterministic signals first
(strict keywords → dialectic signals → social → question shapes), then a **local nomic
embedding vote** as tie-break, then a safe default. Modes: **chat · strict · search ·
dialectic · document**. `document` is forced when the turn carries an attachment, or when a
conversation already holds a document and the turn is chat/search (continue editing).
Adaptive escalation: a chat turn naming the library → `search` (Self-RAG).

References: **Adaptive-RAG** (complexity → no/single/multi-step), **Self-RAG** (retrieve on
demand), **Semantic Router** (embedding intent), **LlamaIndex RouterQueryEngine** (selector).

---

## 5 · The spiral (dialectic engine)

One turn = **immediate → immanent contradiction → Aufhebung (cancel/preserve/raise) → the
product becomes the next immediate → Return**. Stops at **Totality** (no grounded new
contradiction) or on a non-advancing product (convergence). `max_rounds` is adaptive
(2 only for multi-source evidence). Invariants observed each turn (immanence, non-empty
preservation, determinacy, Return, productivity, advance). Movement is a **pure function of
(query, evidence, brief model, rounds)** → cached and reused (writer still re-samples prose).

---

## 6 · Retrieval

BM25(FTS5) + vectors(sqlite-vec) → **RRF(60)** → **bge-reranker** top-N. Deterministic
quote-hunt (`hunt`) and span-anchored (`span_hunt`, page-accurate). **Contextual Retrieval**
(`ctx.db`, Anthropic): chunk text prefixed with `From <book> — <chapter>:` before embedding +
BM25; `retrieve.bm25/vector` use it when it fully covers the library (memoized check).

---

## 7 · Conversations, memory, documents

- **Threads:** `conversations` + `sessions(conv, turn, …)`. Turns ordered by `rowid`
  (stable). `/ask` returns the conversation id; the app adopts it and **persists it**
  (`currentConversation`) so reopening the app continues the thread. Edit/delete/regenerate
  are **engine-owned** (`truncate_conversation`, `delete_turn`) — the app names the op and
  re-projects `/conversation`.
- **Thread continuity is inviolable** (evidence: DeepSeek stateless = always concatenate prior
  turns; OpenAI thread + compaction; LlamaIndex condense): **no mode drops history** (`strict`
  includes it); a conversation **with a document stays `document` mode** for every follow-up;
  short/anaphoric follow-ups are **condensed with history** into a standalone query
  (`_condense`, LlamaIndex CondenseQuestion) before routing/retrieval; and old turns are
  **compacted** into a per-conversation summary (`conversations.summary`, OpenAI compaction)
  rather than silently truncated.
- **Cross-turn spiral:** `memory.prior(conv)` (positions/contradictions/preserved) feeds the
  writer; **history window** is char-budgeted (`history_chars` 6000) + compacted summary.
- **Documents (attachments):** `extract.extract_text` → `documents` table per conversation;
  `document` mode edits/critiques the draft (library evidence optional). The app sends local
  file paths (`attachments:[{path,name}]`); **pasted text over the threshold is written to
  `mentat2_data/attachments/*.txt`** and attached the same way (persists across restarts);
  re-attaching the same path replaces; unreadable/unsupported files don't force document mode.

---

## 8 · Models & serving

- Registry data per model: context / reasoning / sampling / structured / cache / usage /
  job_overrides. **Online** DeepSeek `deepseek-flash`/`deepseek-v4-pro` (prefix caching,
  `thinking:{type}`, `reasoning_effort`). **Offline** default `qwen3.5:35b-a3b-nvfp4` (MoE),
  fallback `qwen3.8:27b-mlx`.
- **Serving:** local **warm start** on engine launch + `keep_alive` 30 m (idle unload);
  **prefix caching** (stable `_SYSTEM` first); `num_ctx` sized to the prompt (8k min);
  structured outputs (Ollama JSON-schema, DeepSeek `json_object`); **writer thinking off**
  (describer); empty-content retry. **MTP/speculative** tested → no gain, off.
- Helpers: `nomic-embed-text` (embed), `bge-reranker-base`, `nli-deberta-v3-base` (batched).

---

## 9 · Persistence (`mentat2_data/`)

- `v2.db`: `claims`, `attacks`, `events`, `conversations`, `sessions`, `memory`, `documents`.
- `ctx.db`: contextual retrieval index (`ctx_meta`, `ctx_fts`, `ctx_vec`).
- `engine.pid`: the live engine PID.
- Read-only v1 indexes reused: `storage/{library,fts,vec,graph}.db`.
- `store.ephemeral()` runs tests/doctor against a throwaway db (never the user's data).

---

## 10 · Observability & quality

- **Telemetry:** every stage emits a `Span` (seconds, tokens_in/out, cached, reasoning,
  load/prefill/decode ms); `store.note_error` error sink.
- **Tests:** `python -m mentat2.tests` (model-free: contracts, invariants, verify, semantics,
  spiral-with-stub, store, citations, router). **Doctor:** `cli doctor` (16 checks).
- **Eval:** `eval.bench` (per-stage floors + retrieval quality), `eval.thinker`,
  `eval.head2head` (bias-swapped pairwise), `eval.scorecard` (aggregate).

---

## 11 · References (verified)

LangGraph/Haystack (declared pipelines) · Anthropic Contextual Retrieval · RAGFlow span
citations · Dung AF · Kojève/Hegel/Stalin/Marx (dialectic) · Self-RAG, Adaptive-RAG, CRAG
(routing/retrieval) · Semantic Router, LlamaIndex RouterQueryEngine (intent) · OpenAI
conversation state · vLLM Automatic Prefix Caching + speculative decoding · Ollama
`think`/`format`/`keep_alive`/`draft_num_predict` · DeepSeek context caching · gunicorn
`pidfile` / uvicorn shutdown (process lifecycle) · RAGAS/G-Eval/MT-Bench (eval).

## 12 · Known limitations / backlog

- Same-series retrieval top-1 (a stronger reranker, e.g. `bge-reranker-large`, is the fix).
- CRAG-style retrieval *gate* not shipped (rerank/overlap don't separate good from nonsense —
  measured). Post-generation grounding is the guard.
- Large-document handling is truncation (chunk+retrieve within the doc is future).
- Online still uses local helper models (intentional: offline-first, zero cost).
- P9 distillation — Backlog (low ROI).
