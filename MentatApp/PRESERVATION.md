# Mentat — Preservation Contract

The definition of done for the rewrite. **The behaviors are the product.** Every
item below must survive the rewrite (ported or deliberately improved), or its
removal must be an explicit decision. The Python brain
(`brain_core.py`, `brain.py`, `server.py`, `brain_mcp.py`, `storage/`) is frozen.

## Reading surface (the soul)
- Fixed book measure: 40-char column, hard 55-char cap.
- `linesPerColumn = 30`; columns fill top-to-bottom (unbalanced), spill 1 → 2 → 3,
  then paginate. Resizing the window never changes the pagination.
- Click an answer → select it + centre it (`centerRequest`); it stays in view
  across page / reasoning animations.
- Arrow keys page the selected answer (L/R); ignored when a field editor (composer
  / settings input) has text, and when modifiers are held.
- Page transition: directional asymmetric slide + fade, `Anim.smooth`; opacity
  under reduce-motion.
- Bubble hugs its content; a short final page collapses instead of leaving a
  full-height empty box. Page control (`‹ n / m ›`) sits at the TOP of the body.
- Streaming: cheap plain-text preview while tokens arrive; full justified/paged
  typeset only on completion; grow spring scales with token delta and is
  suppressed mid-stream.
- Typography: monospaced, justified; `**bold**`, `*italic*`, `> quote`
  (indented italics), `-`/`*` bullets, `#` headers; inline `(Book · Chapter)`
  italicised; `^` / backtick markers stripped; trailing `References` trimmed.
- Thoughts + Citations dropdowns; `FlowRow` chips; "unverified" badge; meta line
  (model · kind · time · tokens · cost).

## Layout armature
- Always-on feathered grid (`GridLinesLayer`): column bands + margin frame, faded
  across a centred 40-box band so the page centre reads clean.
- Numeric inspector (`GridOverlay` + `GridControlsContent`): live steppers for
  cols/gutter/margin/baseline/header/rows, scope layer/window/both, lines,
  opacity, numbers. Dev-facing; the user-facing Layout mode supersedes it.

## Chrome / interaction
- `NavigationSplitView` sidebar (min 250 / ideal 320 / max 440); masonry tile ↔
  list toggle; Find filter; Pinned + Past sections; build stamp.
- Background: the **living sand** is the only canvas (Noir); every other look
  (`System`/`Paper`/`Mono`) owns its own solid surface. Colour comes from the look,
  never from a photo.
- Glass family: pressable, glass button style, materialise, edge-to-edge, soft
  scroll edges, fade glass, frosted backing.
- Light/Dark appearance (only affects `System`) + the **Looks** studio (`SurfaceLook`
  System/Paper/Mono/Noir); the **Sand** studio (living/frequency/grain/glass);
  drop-in menu transitions; command palette; settings sheet; `/debug` panel;
  copy / re-ask / stop actions.

## Preserved specs (must not be lost)
- The grid `@AppStorage` keys (`gridCols`, `gridGutter`, `gridMargin`,
  `gridBaseline`, `gridRows`, `headerHeight`, `gridScope`, `gridLines`,
  `gridLineOpacity`, `gridNumbers`) migrate into the LayoutGrid presets.
  (`storage/design_spec.json` is orphaned — nothing reads it; ignore.)
- `Quicksand-Light` wordmark (`Quicksand.ttf`, registered via CoreText).

## Checkpoint (every phase)
build → launch → streamed answer → click + arrow-page → baseline-aligned columns
→ Layout mode + presets + snap → grid feather + inspector → Looks (System/Paper/
Mono/Noir) → Sand studio → Light/Dark → `/debug`.

## Lean by construction
The app ships **no photo assets**; the sand is procedural. The bundle stays ~9 MB
and `verify.sh` fails if it exceeds 30 MB or if any `Resources/bg-*.jpg` returns.
The token graph (`TokenCatalog`) is the single vocabulary, including `sand.*`.
