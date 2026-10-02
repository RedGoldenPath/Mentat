# Mentat — How It Works, In Plain English

A macro map first (the whole machine), then micro (every component, one by one).

---

## Macro: the whole machine in one page

When you ask Mentat a question, seven things happen in order:

1. **The librarian understands you.** A fast model reads your question and
   decides what kind of answer you want (a quote? a count? a comparison?), what
   exact phrase matters, and which books you mean. It also writes a fake
   "perfect passage" (HyDE) to help the search engine find matching text.
2. **The search engine looks everywhere, several ways at once.** Exact words
   (keyword index), meaning (embeddings), sentences (span index), the whole
   book text (for counts) — all deterministic code, milliseconds to seconds.
3. **The reranker picks winners.** A small local model reads your question
   against the top candidates and keeps only the genuinely relevant passages.
4. **The thinker writes.** A strong reasoning model receives the chosen
   passages — with book and chapter labels — and writes the answer, quoting
   verbatim.
5. **The trust layer checks.** Missing quote citations get filled in
   automatically; quotes that can't be found in the evidence get marked; the
   reference list is trimmed to what was actually cited; a fast editor reads
   the draft against the evidence and asks for one revision.
6. **The diary records.** Every question, passage, model, timing, and test
   result is written to a telemetry database.
7. **Your conversation is saved** with the answer and its evidence, so
   follow-ups inherit context.

The mental model that matters: **the search engine is the product; the model
is the interface.** A brilliant model given bad pages is useless; a good
search engine given a decent model is a research assistant.

---

## Micro: every component, one by one

### 1. The vault

**What it is:** the folder `~/Everything/mentat/` — your books (`books/`),
saved web pages (`web/`), memory notes (`memory/`), lenses (`lenses/`).
Subfolders are scanned recursively.
**What it does:** it is the only source of truth. Anything dropped here can be
indexed.
**Checked by:** `mentat status` (file count, pending changes).

### 2. The indexer

**What it is:** the code that turns files (epub, pdf, txt, md, docx) into
searchable data.
**What it does:** extracts text (preserving chapter markers and paragraph
breaks), splits it into ~4,000-character verbatim chunks with a small overlap,
deduplicates repeated content, skips boilerplate (copyright pages, praise
pages), embeds each chunk, and writes everything into the indexes.
**Checked by:** `mentat index` reports indexed/updated/deleted/errors;
`mentat audit` verifies nothing is pending.

### 3. The chunk store (`storage/library.db`)

**What it is:** a SQLite table of every chunk: its id, book, chapter, sequence,
and the raw text.
**What it does:** it is the ground truth for what the library contains. Nothing
is summarized or compressed — these are verbatim slices.
**Checked by:** `mentat verify` compares chunk count against the keyword and
vector indexes (they must match exactly).

### 4. The sentence-span index (`spans` + `spans_fts`)

**What it is:** the same text, re-cut at paragraph/sentence granularity —
283,226 spans, each with exact character offsets inside its chunk.
**What it does:** lets a quote hunt land on the exact sentence rather than a
4,000-character window, and gives citations a precise anchor. Derived from the
chunk store, so no book re-processing is needed; new files get spans
automatically as they are indexed.
**Checked by:** `mentat spans` (coverage %), `mentat verify` (`search.spans`).

### 5. The keyword index (`storage/fts.db`, FTS5)

**What it is:** a classic search-engine index (BM25 ranking) over every chunk.
**What it does:** instant exact and near-exact word search. It powers the
`/search` command, the quote hunt's phrase/rare-word passes, and scope
resolution ("which books actually contain these words?"). It is
diacritic-folding, so `Allāh` and `allah` are the same word.
**Checked by:** `mentat verify` (`data.integrity`, `census.diacritics`).

### 6. The vector index (`storage/vec.db`)

**What it is:** one 768-dimension embedding per chunk from the local model
`nomic-embed-text`.
**What it does:** semantic recall — finding passages by *meaning* even when
your words differ ("the idea that fear destroys the mind" finds the Litany).
**Checked by:** `mentat verify` (`retrieval.probe` must return real passages).

### 7. Enrichment (context lines)

**What it is:** a one-line, model-written locator for every chunk ("Dune,
Ch.31 — Paul and Jessica meet Stilgar; Jessica recognizes the Fremen language
of Ilm and Fiqh"). All 8,214 chunks have one.
**What it does:** each chunk is embedded together with its context line, which
noticeably sharpens vague-query recall. The embeddings are rebuilt into a
separate file and swapped atomically, so a stopped run can never leave search
half-broken; the previous file is kept as `vec.db.bak`.
**Checked by:** `mentat verify` (`enrichment.state`), `mentat enrich --status`.

### 8. The entity graph (`storage/graph.db`)

**What it is:** 5,441 names and 25,616 co-occurrence edges, built
deterministically from the chunk text (no LLM extraction).
**What it does:** answers "what does X keep company with?" across books —
useful for concept maps and cross-book synthesis. `mentat graph "Fremen"`.
**Checked by:** `mentat verify` (`graph.entities`).

### 9. The librarian

**What it is:** the fast model tier (DeepSeek flash by default). It classifies
intent, extracts the exact phrase for counts/quotes, resolves which books you
mean, and proposes search angles.
**What it does:** converts messy human phrasing ("that bit about the eyes,
you know the blue ones") into precise search instructions. It never decides
facts — only where to look. Every proposal is verified by deterministic code
afterwards.
**Checked by:** `mentat verify` (`census.phrase_shapes`, `router.roles`).

### 10. The retriever (`_build_passages`)

**What it is:** the orchestration layer that decides how to search.
**What it does:** runs semantic + keyword searches, optionally an agent loop
(the planner proposes follow-up searches, up to a configurable number of
rounds, remembering what it tried in a scratchpad), then per-book sweeps so a
multi-book question cannot be swallowed by one book. It merges everything,
removes boilerplate, and diversifies results across books.
**Checked by:** `mentat probe "..."` shows exactly what would be retrieved,
with no LLM calls; `mentat verify` (`retrieval.probe`, `search.scope_priority`).

### 11. The quote hunt

**What it is:** a dedicated half-remembered-quote mode (`/find`, `mentat find`,
or ask "where does it say…").
**What it does:** four deterministic passes — exact phrase, rarest-words
together, spelling rescue (`eys` → `eyes`), phonetic rescue (`feer` → `fear`)
— then scores by term coverage and returns verbatim windows anchored on the
matching sentence. Results are cached for a configurable TTL.
**Checked by:** `mentat verify` (`search.hunt`, `search.phonetic`,
`search.gold`).

### 12. The census

**What it is:** the exact-counting engine ("how many times does X appear?").
**What it does:** scans the full text of the books in scope and counts every
occurrence, tolerating missing little words ("eyes of ibad" = "eyes of the
Ibad"), diacritics, and multiple variants in one question ("allah or god").
It distinguishes story text from front/back matter, and its numbers are marked
authoritative to the model. Answers are audited afterwards: a number that
contradicts the census gets flagged.
**Checked by:** `mentat verify` (`census.e2e_or`, `census.e2e_ibad`).

### 13. The reranker

**What it is:** a small local cross-encoder model (`bge-reranker-base`).
**What it does:** reads the question and each candidate passage together and
scores true relevance — far more accurate than keyword or vector similarity
alone. Keeps the top slice for the thinker and compresses the prompt.
**Checked by:** covered by `retrieval.probe` (the pipeline must produce
sensible passages) and by the fact that answers cite what it kept.

### 14. The thinker

**What it is:** the synthesis tier — DeepSeek v4-pro by default, or any model
you pin in settings (`synth_model`).
**What it does:** receives the selected passages with citations and writes the
answer: prose, verbatim quotes, book · chapter citations. If it runs long it
resumes itself; if the stream dies mid-sentence it repairs the ending; if it
produces nothing, it retries with a different model rather than failing.
**Checked by:** every answer is timed and recorded; the editor pass below
checks the draft against evidence.

### 15. The trust layer

Four independent mechanisms that run after the model writes:
- **Auto-attribution** — any quote the evidence can locate gets `(Book · Chapter)`
  inserted after it.
- **Quote verification** — quotes that cannot be found in the provided passages
  are marked `⟪…⟫` with a warning line.
- **Reference filtering** — the reference list is trimmed to works actually cited
  (no more 11-book lists on a one-book answer).
- **Critique and revise** — a fast editor reads the draft against the evidence
  and requests one revision for numbers, grounding, and silent-book claims.
**Checked by:** `mentat verify` (`citation.attribution`,
`citation.references`).

### 16. Memory

**What it is:** two kinds.
- *Session memory*: what this conversation already understood and counted, so
  "the whole series, I need a number" inherits the prior census.
- *Permanent memory*: `mentat remember "fact"` writes a dated note that gets
  indexed and injected into future prompts when its words match your question.
**Checked by:** `mentat verify` (`thinking.memory`, `thinking.structures`).

### 17. Feedback learning

**What it is:** the reask/stop signals you already generate in the app.
**What it does:** when you re-ask or stop an answer, the passages that answer
used are gently demoted in future ranking. (Can be turned off with the
`learning_from_feedback` setting.)
**Checked by:** `mentat verify` (`ranking.budget`).

### 18. The model router

**What it is:** the rules that decide which model does which job.
**What it does:** librarian and planner on the cheap fast model; synthesis on
the reasoning model; whole-book mode on the long-context model; local qwen
when offline or when the API fails. Every call has a timeout budget
(synthesis 4 minutes, small calls 45–90 seconds) so a half-dead connection
can never hang a question — it fails over to local instead.
**Checked by:** `mentat verify` (`router.roles`, `ranking.budget`);
`mentat status` shows the active models.

### 19. Whole-book mode

**What it is:** `mentat book "Dune" "question"` — the entire work loaded into
Kimi K3's 1-million-token context.
**What it does:** sends the staged full text once as a stable prefix; Kimi's
automatic caching makes follow-up questions cheap. Capped so the request fits
the context window with room for the answer. Requires `MOONSHOT_API_KEY`.
**Checked by:** `mentat verify` (`book.mode`); without a key it returns a
clear message instead of failing.

### 20. The interfaces

- **Chat app (TUI)** — `mentat` with no arguments. Commands: `/find`, `/search`,
  `/graph`, `/verify`, `/settings`, `/model`, `/index`, `/health`, and more.
- **CLI** — `mentat ask/find/book/index/status/settings/verify/graph/enrich/spans/...`.
- **MCP server** — `brain_mcp.py`, used by the `mentat` agent inside opencode;
  exposes `ask_brain`, `find_quote`, `entity_graph`, `verify_system`,
  `index_knowledge`, `remember`, and more.
- **`brain` alias** — kept so nothing you learned before breaks.

### 21. Telemetry and the verification suite

**What it is:** `storage/telemetry.db` (every ask, passage, timing, action)
and `storage/verification.jsonl` (every test result ever run).
**What it does:** `mentat stats` shows the research diary; `mentat verify`
runs 24+ checks and appends results — the history is visible in the app, and
failures stay visible until actually fixed.
**Checked by:** itself. That is the point.

### 22. Settings

**What it is:** 28 settings with plain-English descriptions, editable from
three places:
- CLI: `mentat settings` (the debug menu), `mentat settings set <key> <value>`
- TUI: `/settings` — a scrollable menu with toggles, pickers, and fields
- MCP: `brain_settings` from inside opencode
The TUI menu is generated from one spec (`SETTINGS_SPEC`), so no feature can
exist without appearing in the menu.
**Checked by:** `mentat verify` (`settings.spec`): every declared setting must
be coercible, documented, and actually read by the code.

### 23. Launchers and where things live

- `mentat` → chat app; `mentat <command>` → CLI; `mentat help` → command list
- `mentat-code` → opencode with the Mentat agent
- `Mentat.command` → double-click launcher
- Vault: `~/Everything/mentat/` · App: `~/Everything/mentat/app/`
- Indexes: `storage/library.db` (chunks + spans), `storage/fts.db` (keywords),
  `storage/vec.db` (embeddings), `storage/graph.db` (entities),
  `storage/telemetry.db` (diary)

---

## What runs where

| Tier | Runs on | Cost |
|---|---|---|
| Search, spans, census, graph, rerank, embeddings | your Mac (local) | free |
| Librarian, planner, quote hunts, census wording | DeepSeek flash (API) | fractions of a cent |
| Answer synthesis | DeepSeek v4-pro (API) | cents per answer |
| Whole-book mode | Kimi K3 (API) | ~$1 first load, ~13¢ after |
| Offline fallback | local qwen | free |

## When something feels wrong

1. `mentat status` — is everything indexed?
2. `mentat verify` — did a subsystem stop working? (read the failures)
3. `mentat probe "your question"` — what would actually be retrieved?
4. `mentat stats` — what happened lately (fallbacks, timing, actions, spend)?
5. `mentat audit` — full report card.
6. `mentat enrich --status` / `mentat spans` / `mentat graph` — subsystem state.
7. `mentat kill` — reclaim the lock from a stuck instance.

---

## Model routing, providers, and cost (2026-09)

- **Canonical ids**: `deepseek-flash` is V4.1-Flash (thinking mode, 1M
  context, the workhorse tier); `deepseek-v4-pro` is the deep tier; legacy
  names (`deepseek-chat`, `deepseek-v4-flash`) resolve to canonical ones so
  old saved settings keep working.
- **Provider seam**: any model id may be prefixed — `openrouter/<vendor>/<model>`
  routes through OpenRouter (one key, an endpoint corporate networks rarely
  block, hundreds of models including DeepSeek/Qwen/Claude/Gemini, plus $0
  reasoning models), `moonshot/…` routes to Kimi (dormant until a key is
  added), `deepseek/…` forces the direct API. The `models.canary` verify check
  records what each id actually serves, so silent re-routes show up in the
  diary.
- **Offline mode**: `offline: true` (or `/offline`) makes every tier local
  qwen — search, censuses, hunts, graph, and reranking are already local, so
  only synthesis changes. A startup/tick canary pings the configured provider;
  when unreachable it shows a banner, and `auto_offline` flips to local
  automatically until the network returns.
- **Cost telemetry**: every answer records tokens in/out and estimated USD
  (peak/off-peak aware) in the diary; `/served` shows the model, tokens, cost,
  and the routing reason; `mentat stats` shows today's and all-time spend. A
  positive `daily_budget` demotes the automatic tier to flash once the day's
  ledger passes it.
- **Whole-book mode** now defaults to DeepSeek's own 1M-context model
  (`long_context_model: deepseek-v4-pro`) — no Kimi key required; a
  `moonshot/…` setting routes it to Kimi K3 if a key ever exists.

Table update for "what runs where": librarian/planner = `deepseek-flash`;
synthesis = `deepseek-flash` or `deepseek-v4-pro` (pinned via `synth_model`);
whole-book = `deepseek-v4-pro` (1M context, cache-aware); offline = local qwen
(free); Kimi = dormant.

---

## Register, self-heal, and the M0 layer (2026-09)

- **Register ("kind")**: every question is classified — `count`, `quotes`,
  `concept`, `compare`, `commentary`, `research` — and the rules follow the
  register. Definitions and commentary may retrieve front/back matter
  (glossaries, appendices) and may answer from labeled context when the library
  is silent; verbatim/count questions stay strict. The detected kind shows in
  the status bar (`KIND …`), the stat line, and the telemetry diary. Concept
  questions now reach the Terminology of the Imperium instead of over-hedging.
- **Self-heal ("the Litany Loop")**: a sweep runs every minute (and on
  `/heal` / `mentat heal`) checking index integrity, locks, graph presence,
  and recent failure signals. Deterministic remedies run automatically
  (FTS/spans/graph rebuilds, stale-lock clearing); major repairs (full
  re-embed, schema) ask for approval when `self_heal = full`. Every action
  logs a **voice-aware quip** (e.g. "Hunter-seeker in the code — it must be
  destroyed." in the default voice; each voice gets its own wording).
- **`self_heal` setting**: `off` / `detect` / `remediate` (default) / `full`
  (approval-gated code proposals).
- **Input box** grows with your text up to 16 rows and scrolls beyond.
- **`/stats`** (TUI) mirrors `mentat stats`; `KIND …` appears in the status bar.
- **Offline roles** now follow the Gom Jabbar evidence: synthesis =
  `qwen3.8:27b` (best local), librarian/planner = `qwen3:30b-a3b` (fastest).

---

## M1/M2 — offline contract and citation anchors (2026-09)

- **Offline answer contract** (`_offline_answer_rules`): 32k context, brief
  internal thinking, verbatim quotes with inline `(Book · Chapter)` citations,
  up to ~400 words, and a poison guard — when evidence is missing, say so once
  and paraphrase from general knowledge; never reproduce a quote from memory
  or mint a location the evidence does not show.
- **Think-routing**: quote/count questions answer without thinking (fast);
  concept/compare/commentary/research think first. Offline librarian runs
  `think=False` always.
- **Context guard**: `num_predict` shrinks when the prompt is large, so a long
  synthesis prompt can never starve the answer (the old 16k window could).
- **Page-level PDF citations**: every PDF chunk carries `## Page N` markers
  from extraction; citations render `(Kojeve, Introduction to the Reading of
  Hegel · p. 168)`. Known titles get short display names.
- **Quran verse anchors**: The Study Quran chunks also cite `surah:verse`, so
  answers read `(The Study Quran · 2:255 · p. 88)`.
- **Offline battery (M1)**: 7/7 answered, 0 hedged, 6/7 with inline
  citations, zero empty model calls, avg 56s on the 27B.
- **Poison findings**: raw zero-evidence model calls still fabricate
  (fine-tuning target, M4); through the real retrieval+verifier pipeline the
  same questions refuse correctly and quote only grounded text. See
  `storage/poison_findings.md`.

---

## Reasoning modes — the dialectical method (2026-09)

Every question is answered by one of three reasoning methods, chosen
automatically. There is no mode to switch: factual questions do facts,
interpretive questions close-read, and questions that turn on a contradiction
think dialectically. `reasoning_mode` in settings can force a method, but the
default `auto` is the point.

- **strict** — counts, quotes, lookups. The unchanged grounding pipeline.
- **interpretive** — close reading; inference licensed and labelled.
- **dialectical** — the method. When the question has an internal
  contradiction in it ("why does X destroy itself", "does A negate B",
  "what does the sublation of the state leave behind"), the engine engages.

What the dialectical mode does that the others do not (Hegel's immanent
movement / Aufhebung, and the materialist dialectic of the Stalin text already
in the vault — *not* the thesis→antithesis→synthesis triad, which is banned):

1. **It hunts the contradiction on purpose.** The planner names the tension
   *inside* the subject (not just a second book that disagrees) and retrieval
   gives the negative its own lane; the passages that resist the emerging
   answer are marked `[antithesis]` and protected from the final cut.
2. **It builds a sublation brief before writing.** A cheap helper call names,
   from the evidence: the central contradiction, what is **cancelled**, what is
   **preserved**, what is **raised**, and the new contradiction that result
   generates. The writer performs that movement in prose — the brief is never
   printed as a list.
3. **It checks the draft for movement.** A deterministic pass flags the
   counterfeits — the banned triad, "both sides" hedging without a determinate
   resolution, and erasure (writing that class or the state is "abolished"
   instead of sublated: it is cancelled, preserved, and raised). Online, one
   repair pass fixes them; offline, the movement score and flags are recorded.
4. **It spirals across a conversation.** Each dialectical answer's position is
   remembered, and the next turn is asked to negate and sublate it rather than
   restart.

Cost: the brief adds a few seconds on the helper model and only runs for
dialectical questions; facts and quotes are untouched. Measured locally:
~78–114s per heavy dialectical answer, movement 5–6/7, no triad.

Checked by: `battery.py --group dialectic` (14 gold questions, including a
one-sided control that must *not* manufacture a tension, and a quote control
that must stay strict); the rubric scores movement, cancel/preserve/raise,
both-sides, and erasure. Settings `reasoning_mode`, `dialectic_brief`,
`dialectic_ledger`.
