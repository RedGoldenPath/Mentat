# PLAN — Mentat (living checklist)

**Single source of truth for the current session.** Re-read at the start; update
at every step. Keep it LIVING: when a step is concluded, fold it to a single
line under "In place" (or delete it); when a task dies, delete it. Do not let
concluded steps or dead processes accumulate here — this file lists what is
being done now, so context can never get lost in a graveyard.

Status: dialectical method (Track D). Gates every step: `python verify.py --quick`
(36) · `python eval.py --gold` (13/13) · `python eval.py` (82/86). Quality-boundary
gate: `battery.py --group dialectic` A/B.

---

## Now — Track D · Dialectical method

Goal: the dialectical method engages automatically when a question turns on a
contradiction, and facts stay facts. No mode toggle. Framing: Hegel's immanent
movement / Aufhebung — NOT the thesis–antithesis–synthesis triad — with the
dialectics of the Stalin text in the vault as method (contradiction internal to
a thing). Sources: `Stalin, Dialectical and Historical Materialism`, `Kojeve,
Introduction to the Reading of Hegel`.

Decisions locked:
- Method chosen per question by `_reasoning_mode` (auto): `strict` /
  `interpretive` / `dialectical`. `reasoning_mode` is an optional override only.
- Sublation brief runs on the **helper** model, before the writer, sequentially.
- **No local revision pass** until the brief alone is measured.
- Bar: local-with-method sits in the same band as `deepseek-v4-pro` on movement +
  grounding (not better).
- Lexicon discipline is policed: class and the state are **sublated** (cancelled,
  preserved, raised), never "abolished/eliminated"; "negation" must name *what*.

In place (built, gated 36/36 · 13/13 · 82/86): mode selector + prompt split;
negation lane (`contradiction` planner field, `[antithesis]` marking,
`_ensure_negation`); sublation brief (`_sublation_brief`, helper-cached);
movement check + lexicon guard (`_movement_report`, `_lexicon_flags`,
`_dialectic_revise` online); thesis ledger; `battery.py` `dialectic` group (14 Qs)
+ rubric; `_answer_path` never "fast" for dialectical. Measured offline: ~3s
helper for the brief; 78–114s/answer, movement 5–6/7, no triad, one erasure flag
(offline, no repair).

Open:
- [x] **1 · Quality gate — PASSED (caveats).** Local+method movement **3.6/7** vs
  `deepseek-v4-pro` **2.8/7**; ungrounded **13 vs 11** (same band). Local cites
  **63 vs 128** (weaker grounding breadth). Verdict: the 27B + dialectical method
  is in the online model's band on movement and grounding; the gap is citation
  breadth. Triad-ban re-check: Q2 and Q9 now **triad 0** (were 1); Q12 not run.
- [ ] **2 · Movement rubric is lexical (new).** After the triad ban, movement
  scores *dropped* (Q2 4→2, Q9 5→3) even though the answers remained
  substantively dialectical — banning the labeled vocabulary removes the words
  the keyword rubric counts. Consider a movement check that reads structure, not
  just terms. Low priority; the thinking is there, the measurement is crude.
- [ ] **3 · Local revision (stays deferred).** Movement+grounding are in band, so
  no local repair pass unless the triad fix regresses grounding.

Findings this session:
- **Triad detector was blind to labels.** Answers wrote "thesis: … antithesis: …"
  (Q12, Q9) and the exact-phrase rubric missed it. Fixed: `_triad_used` in
  `brain_core` + `battery` now flags the phrase OR the two terms used as labels;
  the dialectic prompt now bans the words "thesis/antithesis/synthesis" outright.
- **"Online" was silently local.** `stream_dialectic.py --online` left
  `settings.json`'s `offline: true` in place, so the first online leg ran the
  local 27B (slow, and it kept 18 GB resident). Fixed: `--online` forces
  `offline=False`, model `deepseek-flash`, synth pinned.
- **Local preliminary (voice dialectic, pre-fix prompts):** movement_avg 3.6/7,
  triad 3, ungrounded 13, cites 63, avg 88s. Strong where the corpus states the
  tension (Quran usury 7/7, Khaldun 6/7, state sublation 6/7); weak where
  retrieval missed it (Leto II 1/7, Khaldun agency 1/7, debt/empire 2/7).
- **Online reference (deepseek-v4-pro):** Q1 Khaldun 6/7, 0 ungrounded, 78s —
  same band as local on that question. Run in progress.
- Local answers predate the triad/ban fixes; a rerun is needed to see triads drop.
- **RAM:** stopped the idle 27B (`ollama stop qwen3.8:27b`); free 46% → 88%.

---

## Next up — engine (open, not current)
- **A2 · Quiet plumbing.** Prompt-prefix cache; merge/cache helper calls. Gate:
  `gen_tokens` / `helper_sec` down, quality flat.
- **D1 · Split `brain_core.py`.** Modules: retrieval, Thufir, Lisan al-Gaib,
  Bene Gesserit, Shai-Hulud, telemetry.
- **Stage 3 · Living Brain.** Retrieval switches → weights (soft routing) +
  relaxation/early-exit; consolidate routing into Lisan al-Gaib.
- **C3 · Cache prewarm + speculative retrieval.** Hit-rate gated.
- **C4 · Knob auto-tuner** against held-out gold + Spice Agony.
- **Track B.** GraphRAG-expanded retrieval / sentence-window context; sparse
  indexer; retriever mixture; speculative prefetch; off-main region sampling.

## Deferred / not now
- App/UI: Chat↔Research modes + indicator bar; Screens split; type sweep;
  composer polish; voice picker. (User deprioritised app work.)
- Never built: tagged line protocol for model handoff; prompt-lookup speculative
  decoding (needs an in-process decode loop). The architect→typist JSON brief
  shipped as the sublation brief.
