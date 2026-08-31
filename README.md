# Second Brain

A GraphRAG "thinking partner" that indexes everything in your knowledge
folder and reasons across texts to make novel connections.

- **Content vault:** `~/Everything/second brain/` — drop any text file or
  folder in here (txt, md, pdf, epub, docx). Subfolders are scanned
  recursively.
- **Tooling + index:** `~/Everything/Scripts/secondbrain/`
- **Models:** extraction via DeepSeek API (indexing), queries via your local
  Ollama `qwen3.8:27b` + `nomic-embed-text` (free, offline).

## Setup (one time)

1. The DeepSeek key lives in `.env` (`DEEPSEEK_API_KEY=sk-...`). It was copied
   from your opencode login. Without it, indexing falls back to the local
   model (slow for large corpora).
2. Build the index for the whole vault (uses DeepSeek, ~30-60 min for the
   Dune series, ~$2):

   ```bash
   uv run --project ~/Everything/Scripts/secondbrain python brain.py index
   ```

   Partial builds: add `--only <relpath>` (e.g. `--only notes`).

   When run in a terminal, `brain index` shows a live per-file progress panel:
   each file listed separately with its own percentage and MB amount, plus an
   overall line (e.g. `✓ 100%` done files, `▸ 71%` the current one, `· 0%`
   waiting, and `overall 3/8 files · 24/62 MB (38%)`).

## Usage

| Action                           | Command                                                              |
| -------------------------------- | -------------------------------------------------------------------- |
| Index everything new/changed     | `brain index`                                                        |
| Check indexing status            | `brain index-status` (running? progress? pending?)                   |
| Ask a question                   | `brain ask "..."` (add `--no-lazy` to skip auto-indexing)            |
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

## Settings

Stored in `storage/settings.json`. Keys:

| Key             | Values                                                    | Effect                                  |
| --------------- | --------------------------------------------------------- | --------------------------------------- |
| `thinking`      | `false`, `true`, `low`, `medium`, `high`                  | Qwen reasoning depth (local answers)    |
| `history_turns` | integer (0 = off)                                         | how much prior conversation to feed back|
| `mode`          | `naive`, `local`, `global`, `hybrid`, `mix`               | default query mode                      |
| `model`         | `deepseek-chat` · `deepseek-think` · `qwen` · any name   | which model writes the answers          |
| `temperature`   | `0`-`2` or `none`                                         | answer creativity                       |
| `top_k`         | integer                                                   | how many graph nodes to pull            |
| `chunk_top_k`   | integer                                                   | how many text chunks to pull            |
| `lens`          | free text                                                 | framing injected into every answer      |

### Choosing the answer model

The brain writes its answers with one of three engines (the retrieval step
always stays on local Qwen for speed):

| Setting value      | Model           | When to use                                    |
| ------------------ | --------------- | ---------------------------------------------- |
| `deepseek-chat`    | deepseek-chat   | default — fast, good quality                   |
| `deepseek-think`   | deepseek-v4-pro   | deep reasoning, cross-text synthesis         |
| `qwen`             | qwen3.8:27b (local) | fully offline, free, no internet            |

```bash
brain settings set model deepseek-think     # deep reasoning
brain settings set model qwen               # go offline
brain settings set model deepseek-chat      # back to default
```

If DeepSeek is unreachable (no internet), the brain automatically falls back
to local Qwen so it always answers. In the console, `model <name>` switches
instantly. (In opencode, the `secondbrain` agent uses opencode's own model
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
~/Everything/second brain/lenses/historical-materialism.md   # write your lens here
brain lens historical-materialism                            # activate it
brain lens --clear                                           # turn it off
```

Example lens (`lenses/historical-materialism.md`): "Analyze every subject
through the lens of Stalin's historical materialism: identify who owns the
means of production, what form the systemic debt takes, which group is bound
to which creditor class, and how the seizure of production cancels that debt..."

## Memory (permanent knowledge)

`remember` appends a dated fact to `~/Everything/second brain/memory/<topic>.md`
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

The `secondbrain` agent connects via MCP. Restart opencode after config
changes, then switch to the `secondbrain` agent. Use `/settings` to view or
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
