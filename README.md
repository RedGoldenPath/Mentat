# Mentat

A library search-and-reasoning "thinking partner" that indexes everything in
your knowledge folder and reasons across texts to make novel connections.

- **Content vault:** `~/Everything/mentat/` — drop any text file or
  folder in here (txt, md, pdf, epub, docx). Subfolders are scanned
  recursively.
- **Tooling + index:** `~/Everything/mentat/app/`
- **Models:** librarian + planner on DeepSeek flash, synthesis on
  deepseek-v4-pro (Kimi K3 for huge evidence packs), retrieval and embeddings
  stay local via Ollama (`qwen3.8:27b` + `nomic-embed-text`, free/offline).

## Setup (one time)

1. The DeepSeek key lives in `.env` (`DEEPSEEK_API_KEY=sk-...`). It was copied
   from your opencode login. Without it, indexing falls back to the local
   model (slow for large corpora).
2. Build the index for the whole vault (uses DeepSeek, ~30-60 min for the
   Dune series, ~$2):

   ```bash
   uv run --project ~/Everything/mentat/app python brain.py index
   ```

   Partial builds: add `--only <relpath>` (e.g. `--only notes`).

   When run in a terminal, `brain index` shows a live per-file progress panel:
   each file listed separately with its own percentage and MB amount, plus an
   overall line (e.g. `✓ 100%` done files, `▸ 71%` the current one, `· 0%`
   waiting, and `overall 3/8 files · 24/62 MB (38%)`).

## Usage

`mentat` is the single entry point: run it with no arguments for the chat app,
or with a command for the CLI. (`brain` remains a compatibility alias.)

```bash
mentat                      # chat app (TUI)
mentat ask "..."            # one-shot grounded answer
mentat find "..."           # quote hunt
mentat book "Dune" "..."    # whole-work mode (Kimi K3)
mentat status               # what is indexed
```

| Action                           | Command                                                              |
| -------------------------------- | -------------------------------------------------------------------- |
| Index everything new/changed     | `brain index`                                                        |
| Check indexing status            | `brain index-status` (running? progress? pending?)                   |
| Ask a question                   | `brain ask "..."` (add `--no-lazy` to skip auto-indexing)            |
| Hunt a half-remembered quote     | `brain find "..."` (fuzzy + exact, quotes back)                      |
| Read a whole work (Kimi K3)      | `brain book "Dune" "..."` (needs `MOONSHOT_API_KEY`)                 |
| Sentence-span index              | `brain spans` · rebuild: `brain spans --build`                       |
| Model catalog + prices           | `mentat models`                                                      |
| Stop a stuck instance            | `mentat kill`                                                        |
| Contextual-retrieval enrichment  | `brain enrich --status` · `--contexts` · `--llm` · `--embed`         |
| Entity co-occurrence graph       | `brain graph "Fremen"` · rebuild: `brain graph --build`              |
| Run the verification suite       | `brain verify` (history: `brain verify --history`)                   |
| Interactive chat                 | `brain console` (friendly: help, themes, save, remember, backup)     |
| Save a web page into the vault   | `brain save <url> [--title ...]`                                     |
| Overview of library themes       | `brain themes`                                                       |
| See status + settings            | `brain status`                                                       |
| View past conversations          | `brain history` (or `--limit 20`)                                    |
| View/change settings             | `brain settings` · `brain settings set <key> <value>`                |
| Set a lens (persistent voice)    | `brain lens <name>` · clear with `brain lens --clear`                |
| Remember a fact forever          | `brain remember "fact" [--topic name]`                               |
| Back up the index                | `brain backup` · list: `brain backup --list` · restore: `brain backup --restore <name>` |
| Auto-index on a timer            | `brain schedule on [--every 6]` · off: `brain schedule off`          |
| List all commands                | `brain commands`                                                     |
| Remove one file                  | `brain forget notes/foo.md`                                          |
| Delete the whole index           | `brain reset --yes`                                                  |

Query modes: `--mode local|global|hybrid|mix|naive` (default `mix`).

## How retrieval works

Five tiers, all deterministic until the final synthesis:

1. **Chunks** — verbatim ~4k-char slices of every book (`library.db`).
2. **Spans** — paragraphs/sentences with exact char offsets (`brain spans`),
   used for precise quote anchors and sentence-level recall.
3. **FTS5** — BM25 keyword index over chunks and spans, with phrase and AND
   passes and diacritic folding (`Allāh` = `allah`).
4. **Vectors** — `nomic-embed-text` embeddings of context-enriched text
   (`brain enrich`), rebuilt into a temp db and swapped atomically.
5. **Rerank** — local `bge-reranker-base` cross-encoder prunes candidates.

On top of that: the **quote hunt** (`/find` in the app, `brain find`) runs
phrase → rare-term AND → spelling/phonetic rescue → BM25, scores by coverage,
and returns verbatim windows; **censuses** (`how many times does X appear`)
scan full text and their numbers are authoritative. The **entity graph**
(`brain graph`) maps which names and ideas co-occur across books — the raw
material for cross-book synthesis.


## Settings

Stored in `storage/settings.json`. Keys:

| Key             | Values                                                    | Effect                                  |
| --------------- | --------------------------------------------------------- | --------------------------------------- |
| `thinking`      | `false`, `true`, `low`, `medium`, `high`                  | Qwen reasoning depth (local answers)    |
| `history_turns` | integer (0 = off)                                         | how much prior conversation to feed back|
| `mode`          | `naive`, `local`, `global`, `hybrid`, `mix`               | default query mode                      |
| `model`         | `deepseek-flash` · `deepseek-think` · `qwen` · any name  | which model writes the answers          |
| `temperature`   | `0`-`2` or `none`                                         | answer creativity                       |
| `top_k`         | integer                                                   | how many graph nodes to pull            |
| `chunk_top_k`   | integer                                                   | how many text chunks to pull            |
| `sweep_depth`   | integer (default `6`)                                      | passages pulled per book when the question demands a multi-book sweep |
| `lens`          | free text                                                 | framing injected into every answer      |

When a question spans books — "across the Dune series", "in all your books" —
the brain resolves which works it demands (named works first, then every work
whose text verifiably contains the question's terms), sweeps each one, and
merges duplicate copies of the same book (an EPUB and PDF of one novel count
as one work). Counting questions ("how many times does … appear?") get an
**exact census**: a full-text scan of the books in scope reports per-book,
per-chapter occurrence counts that the answer treats as authoritative.
Censuses and quote-retrieval count the **story text only** — appendices,
glossaries, praise pages, afterwords and other front/back matter are excluded
unless the question explicitly asks for them — and a missing little word
("eyes of ibad" vs "eyes of the Ibad") never zeroes a count.

Counting questions are understood by the **front-end comprehension layer**
(the fast model classifies intent and the exact phrase from any natural
phrasing; keyword rules remain only as the offline fallback), then verified
by deterministic code: the model's phrase is actually counted — typos are
spelling-rescued against the library vocabulary ("eys of ibad" counts as
"eyes of the Ibad") — so a zero is only reported when the phrase is truly
absent, and answers are **audited** after writing: a numeric claim that
contradicts the census is flagged on the answer itself.

Cross-book and interpretive questions are answered by the default synth tier
(**deepseek-flash** online — a 9-question holdout showed it citing ~2× more
sources than pro at ~1.7× the speed, with comparable grounding; the big local
Qwen offline). Pinning `synth_model: deepseek-think` upgrades the synth to
deepseek-v4-pro and enables a final **critique-and-revise pass**: a fast editor
checks the draft against the evidence (numbers, quotes, grounding, silent-book
claims) and the draft is revised once before it reaches you. If a reasoning
model ever thinks but runs out of output budget, the brain retries with the
chat model and, as a last resort, shows the tail of the reasoning rather than a
canned non-answer.

### Choosing the answer model

The brain writes its answers with one of three engines (the retrieval step
always stays on local Qwen for speed):

| Setting value      | Model             | When to use                                  |
| ------------------ | ----------------- | -------------------------------------------- |
| `deepseek-flash`   | deepseek-flash (V4.1) | default — fast, thinking-capable, cheap  |
| `deepseek-think`   | deepseek-v4-pro   | deep reasoning, cross-text synthesis         |
| `qwen`             | qwen3.8:27b (local) | fully offline, free, no internet           |

Provider-prefixed ids work anywhere a model is accepted:
`openrouter/<vendor>/<model>` (one key for DeepSeek/Qwen/Claude/Gemini on an
endpoint corporate networks rarely block), `moonshot/kimi-k3`, or
`deepseek/<id>` to force the direct API. `mentat models` shows the catalog
with keys and per-token prices; `/offline` (or the `offline` setting) switches
everything to local qwen; a startup canary warns when the API is unreachable
and `auto_offline` can flip to local automatically. `daily_budget` (USD/day,
0 = off) demotes heavy answers to flash once the day's ledger passes it.

```bash
brain settings set model deepseek-think     # deep reasoning
brain settings set model qwen               # go offline
brain settings set model deepseek-flash     # back to default
```

If DeepSeek is unreachable (no internet), the brain automatically falls back
to local Qwen so it always answers. In the console, `model <name>` switches
instantly. (In opencode, the `mentat` agent uses opencode's own model
picker — press Tab to switch there too.)

Example:
```bash
brain settings set thinking high
brain settings set history_turns 12
brain settings set mode global
```

## Lens (persistent voice)

The `lens` is a block of instructions injected into the system prompt of
every answer, so the brain keeps a consistent framing without you prompting
each time. Create lens files as ordinary notes in the vault, then activate:

```
~/Everything/mentat/lenses/historical-materialism.md   # write your lens here
brain lens historical-materialism                            # activate it
brain lens --clear                                           # turn it off
```

Example lens (`lenses/historical-materialism.md`): "Analyze every subject
through the lens of Stalin's historical materialism: identify who owns the
means of production, what form the systemic debt takes, which group is bound
to which creditor class, and how the seizure of production cancels that debt..."

## Memory (permanent knowledge)

`remember` appends a dated fact to `~/Everything/mentat/memory/<topic>.md`
and indexes it into the graph, so it is automatically retrieved in future
answers. Use it for personal definitions, beliefs, or decisions you never
want to re-state.

```bash
brain remember "I define revolution as the cancellation of systemic debt through the seizure of productive power." --topic definitions
```

## Backups

`brain backup` snapshots the whole index (including settings + history) into
`backups/`, keeping the last 5. Restore with `brain backup --restore <name>`
or list them with `brain backup --list`.

## Scheduled auto-indexing

`brain schedule on --every 6` installs a macOS launchd agent that runs
`brain index` every 6 hours, so new files get indexed even if you never ask.
This creates a file in `~/Library/LaunchAgents/`. Turn it off with
`brain schedule off`. First run after enabling will index the whole backlog
(deepseek-fast if the key is set).

## Auto-indexing behavior

Small additions (up to 8 files or ~2 MB) are auto-indexed before answering.
Larger backlogs (like the Dune books) are **not** silently indexed — the brain
tells you what needs indexing and waits for an explicit `brain index`, so a
simple question can never kick off a multi-hour build behind your back.

While an index is already running, asking a question reports the live progress
(`index-status`) instead of starting a second, conflicting build, and
`brain index` refuses until the current run finishes.

## Inside opencode

The `mentat` agent connects via MCP. Restart opencode after config
changes, then switch to the `mentat` agent. Use `/settings` to view or
change settings and `/brain` to see all commands.

## Costs & storage

- **Indexing:** ~$2 for the Dune corpus via DeepSeek. Daily queries are local
  and free.
- **Disk:** ~1-1.5 GB (venv ~700 MB, index ~300-600 MB).

## Troubleshooting

- Ollama must be running for queries/embedding.
- If `DEEPSEEK_API_KEY` is missing, extraction falls back to Ollama — check
  `brain status` for the active `extract_model`.
- Rebuild from scratch: `brain reset --yes` then `brain index`.
