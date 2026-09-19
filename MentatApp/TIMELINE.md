# Mentat App — Build Timeline

The tracked plan for the app rewrite + design system. Statuses: done / in-progress / pending.

## Phases 0–9

- **0 — Baseline & preservation** · done. Dirt removed (`historyCard` restored, no `/tmp` write,
  reorder wiring deleted), grid feather kept, `PRESERVATION.md` is the parity contract.
- **1 — Toolchain & build** · done. `swift-tools-version 6.4`, `.macOS(.v27)`, Swift 6 language
  mode, robust `build.sh` (DEVELOPER_DIR-overridable), `swift-format`, `run.sh` = build + open,
  min-27 plist.
- **2 — Engine boundary** · done. `@Observable` `Engine` (own file), typed `MentatClient`,
  `EngineProcess` actor, fixture mode (`MENTAT_FIXTURE=1`).
- **3 — DesignSystem** · done. `DesignTokens` + `DesignStore`, `TypeScale`, `Glass`, `Controls`,
  `LayoutGrid`, `Masonry`, `Metrics`, `Motion`, `Typography`.
- **4 — ColorSystem** · done. `ColorScience` (OKLCH + gamut + WCAG), `Analyzer`, `Resolver`,
  `Scheme`, `Provider`. Palette **schemes** (primary, monochrome, analogous, secondary, tertiary,
  complementary, split, triadic, from-image) with **surface-hue rotation**; **ink modes**
  (background-adaptive default / theme); OKLCH-native palette tool + preview list.
- **5 — Reading surface** · done. Pure `PageEngine` (measure, columns, pages), baseline alignment,
  all reading quirks preserved; unit-tested.
- **6 — Layout instrument** · done. `LayoutGrid` armature + `SnapEngine` + composition guides
  (thirds / golden / centre); full-screen Layout mode (⌥⌘G); armature panel in Debug.
- **7 — Screens split** · pending. Move Chat / Sidebar / Composer / Reader / Menu / Debug out of
  the main file into `Screens/`. Architecture only, no visual change.
- **8 — Role adoption + UX + motion** · in-progress. Role adoption done (theme-derived Palette,
  rail, cards, plates, panels). UX basics (empty/offline/error, keyboard, focus, a11y) + motion
  polish pending.
- **9 — Data-driven + performance** · in-progress. Done: streaming row isolation, no render-time
  hashing, off-main palette analysis, colour caches, PERF HUD + signposts, SQLite mmap/cache/WAL,
  chunk-id cache, cache-hit visibility, warm-up. Pending: off-main region sampling, async gallery
  thumbnails, memory bounds, final measurement.

## Art Direction workstream (new)

Encode the reference language as data + rules, then apply:

- **Shape vocabulary** — capsules, circular icon buttons, super-rounded cards, thin-rule motif.
- **Scale hierarchy** — dramatic type jumps (large light hero → small dim micro), weight contrast.
- **One solid focal per screen** — e.g. the composer send; everything else translucent.
- **Composition** — unequal widths, repetition with variation, asymmetry, alignment to the
  armature (12-col + thirds/golden).
- **Colour restraint** — neutral UI driven by the theme; colour from the artwork; a single accent
  for active state.
- **Material depth** — system Liquid Glass only (no hand-rolled rims), stained-glass tint, with a
  **Tinted / Clear** setting; content stays non-glass.
- **Motion** — calm springs, morphing glass, reduce-motion aware.

## Liquid Glass

- System `glassEffect` only; hand-rolled `GlassSurface` / `FadeGlass` / `FrostedBacking` retired.
- **Tinted / Clear** setting (default Tinted), provided via environment.
- Planned: morphing menu (rail ↔ panel via `GlassEffectContainer` + `Namespace` + `glassEffectID`).

## Track B — brain (separate)

- **B1** · done: SQLite mmap/cache/WAL tuning, `chunk_id` cache, cache-hit token visibility,
  startup warm-up. Validated: `eval.py` 82/86, gold 13/13.
- **B2** · deferred: GraphRAG-expanded retrieval, neighbour/sentence-window context,
  position-aware assembly, continuous eval tuning.

## Verification

- 31 unit tests (pagination, colour science, resolver, schemes) — green.
- Clean build, 0 warnings. Both run modes (normal + fixture). Engine `/status` online.
- Screenshots verify Tinted/Clear and scheme recolouring.

## Progress log

### Track A — App UX (in progress)
- ✅ **Traffic lights** — hover-only, top-left (`DesignSystem/WindowChrome.swift`); hidden by
  default, fade on hover, reduce-motion instant, clicks pass through.
- ✅ **Telemetry seam** — `done` meta now carries `route_reason` + `cache_hit_tokens` /
  `cache_miss_tokens`; app `AnswerMeta` extended; meta line shows "cached N · route". Eval-gated.
- ✅ **Legibility fixes** — wordmark ink is always luminance-based (never dark-on-dark), wordmark
  picks the ink for the region it actually sits over, and the top control glyphs contrast their
  own disc fill (fixes the two buttons vanishing on dark art).
- ✅ **Liquid Glass** — system `glassEffect` only; deleted dead hand-rolled glass
  (`GlassSurface` / `FadeGlass` / `FrostedBacking` + unused `.glass` / `.fadeGlass` / `.frosted` /
  `.liquidClear` / `.edgeToEdge`). Dropped remaining availability gates.
- ✅ **Traffic lights** — for now the native close/min/zoom buttons are **hidden**
  (`HideTrafficLights`, `DesignSystem/WindowChrome.swift`); the hover-reveal was parked.
- ✅ **Offline banner** — a small capsule above the composer appears when the engine is
  unreachable, with a Retry button (no more silent offline).
- ✅ **Aesthetic** — conversation cards bumped to a super-rounded radius; orphaned
  `storage/design_spec.json` removed.
- ✅ **Clear glass carries colour** — removed the `glassStyle == .tinted` gate on all four glass
  wrappers (`LiquidSurface`, `BubbleSurface`, `GlassPanel`, `SidebarGlass`); both styles now tint
  when the theme is live, Clear at a lighter `ColorTheme.clearTint` (accent @0.34) and Tinted at
  `accentTint` (@0.55). This was why the earlier vibrancy work was invisible: the app was in
  Clear mode, where no tint was applied. Verified hue-follow: magenta rail over aurora, blue over
  reef, grey over neutral desert. One-time `colorVividBumpV1` migration lifts untouched
  chroma/tint to 1.4/1.3; `ColorControls.default` now 1.4/1.1/1.3.
- ✅ **Perf: off-main sampling** — `BackgroundAnalysis` memo caches are now lock-guarded and
  bounded (160); region reads + the 36-sample quiet-band scan + palette pixel sampling +
  the 132-file catalog all run off-main and publish back on the main actor (stale tasks
  cancelled). Region sampling is one batched `regionAverages` pass; results cross as
  `Sendable` RGB. Gallery tiles use a new `AsyncThumbnail` (ImageIO downsample, fades in)
  instead of decoding on the render thread. Catalogue reads image metadata via ImageIO, not
  `NSImage`. Top/title OKLCH ink is memoized (`topInk`/`adaptiveInk`) so view bodies do no
  colour science per frame. Only the pre-existing benign `sliderRow` warning remains.
- ✅ **Vibrancy pass** — Liquid Glass controls now tint with the *accent* (`ColorTheme.accentTint`)
  instead of the muted surface tone; caps raised (base `0.28`, surface `0.18`, accent `0.32`,
  role `0.26`), tint alpha `~0.72`, default chroma `1.15` / tint `1.1`. Neutral images still
  resolve to true grayscale per the `mono`/`followImage` rule. 31 tests green.
- ✅ **Screens split (more)** — extracted `Support/BackgroundAnalysis.swift`,
  `App/App.swift` (app entry + `PaletteHost`), and `DesignSystem/ThemeEnv.swift`
  (Palette / ChromePalette / AppInk / AppTheme + env keys). Monolith 2,403 → **1,916** (from 3,712).
- ✅ **Keyboard / a11y** — Esc dismisses the topmost layer (reader → palette → menu → debug) and
  closes the layout instrument / clears find; `ChipButton` gained an accessibility label; the
  starfield is hidden from a11y. ⌘N / ⇧⌘N / ⌥⌘D / ⌥⌘G already wired.
- ✅ **Source reader (the grounding loop)** — tapping a citation chip opens a full reader screen
  at the exact passage: `GET /passage` resolves `(book, loc)` back to the chunk (preferring the
  passages that grounded the last answer, ranked by quote overlap), returns the focal quote plus
  a 5k-char verbatim window. `SourceReader.swift` shows the quote as the one solid focal (serif)
  and the window scrollable via `BookText`, with the quote softly washed; back button, Esc, and
  scrim-tap return to the answer. `CitationChip` is now a button. Frozen schema untouched.
- ✅ **Columns → pop-ups** — the reading column engine (`PageEngine`/`PagedText`) is now a
  standalone `ColumnText` view with its own type scale (`TextStyle.attributed` grew a `size:`).
  The `Thoughts` disclosure flows in the answer's columns at caption scale; the palette panel's
  prose is typeset by the engine; the command palette runs a balanced two-column list. Also added
  **⌘K** to open the palette. Build clean, 31 tests.
- ✅ **Colourful first launch** — when no background is saved, prefer `bg-curated-aurora-1` over
  whatever `bg-` sorts first (which read as grey).
- ⏳ Pending: rest of the split (ChatView, RootView, MessageRow, palette/theme plumbing),
  Art Direction depth, retire dormant legacy HSB.

### Track B — backend (after Track A)
- ✅ **B1** (prior): SQLite mmap/cache/WAL, `chunk_id` cache, cache-hit visibility, warm-up.
- ✅ **B2.0/B2.1 (measure + caching)** — baseline `eval.py --bench`: probe median `1.25s`,
  RSS `1924MB` (was `0.18s` / `1249MB`). Hot path was `_derive_terms → _fix_vocab_spelling`,
  whose `difflib.get_close_matches` rescanned the whole vocabulary on every query angle;
  the librarian also rebuilt an 8k-entry chunk dict and re-scanned every chunk path per term,
  and re-embedded the same query as a "document" ~15×/probe. Fixes (all behavior-preserving):
  - `_fix_vocab_spelling` memoized (`_SPELL_CACHE`, dropped with the vocab/index).
  - `_librarian_search` uses cached `_chunks_by_id()` + new `_low_file_paths()`.
  - `nomic_embed` caches **both** query and document embeddings (`_EMBED_CACHE`, keyed by context).
  - `warm_models()` pre-builds the vocab + span index at boot (B2.5 prefetch).
  Result: probe median **0.79s (−37%)**, no bench regressions. Gates: **82/86** fast,
  **gold 13/13** stable over 3 runs. Stream schema and routes unchanged.
- ⏳ B2.2–B2.5 remaining: context compression, sparse indexer, retriever mixture/router,
  speculative prefetch, plus the RSS (`1924MB`) audit.
  - ✅ **B2.2 (partial)** — `_render_passage_block` now drops exact-duplicate passages
    (the same chunk arriving from several retrieval angles), saving prompt tokens without
    losing evidence. Eval 82/86 · gold 13/13.


