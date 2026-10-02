# Sand light — motion, candle, legibility + quote regression

**Status:** planned (not started) · **Date:** 2026-09-26

Owner notes: fix the animation/feel and brightness of the sand light, fix the
dust piling at the frame edges, and fix the quote regression. Everything below
was verified by reading the code; line numbers are from this date.

## Findings (verified in code)

- **Dust piling at top/bottom.** `SandMotionStore.swift:169-186` emits
  **full-span collider bars** for global transitions:
  - `.scroll` → `SIMD4(0.0, down ? 0.0 : 0.92, 1.0, 0.08)` (full width, top or bottom)
  - `.modeChange` → `SIMD4(0.0, 0.0, 1.0, 0.11)` (full width)
  - `.resize` → `SIMD4(0.90, 0.0, 0.10, 1.0)` (full height)

  `resolveRect` in `SandShaders.metal` clamps the inward velocity to 0 and snaps
  dust to the bar's edge, so across a full-width/height bar dust can't go around
  → it stacks into a line at the top or bottom. Fed via
  `SandCanvas.provider()` → `store.solids()` → `SandInputs.obstacleRects`.

- **Beams are static.** `beamAt` (`SandShaders.metal:96-108`): the ray `warpN`
  has no `time`, the per-ray hashes `h1/h2/h3` are fixed per `idx`, breathing is
  only ±18% at `shaftSpeed = 0.35` (~18 s), `width` never moves, and `big` never
  sees time. Only the thin filaments move, and only via `drift` at 0.03/s.

- **Too bright / middle unreadable.** The app runs the **stale** preset
  `SandStyle.sand` (`SandStyle.swift:42-50`) and `DesignTokens.Sand`
  (`DesignTokens.swift:119-149`): `shaftStrength 1.8`, `dustBase 0.25`,
  `shaftFalloff 2.2`, `shaftSourceGlow 1.0`, `bloomIntensity 0.25`, and it
  lacks every newer param. So the app does **not** use the tuned `SandConfig`
  defaults the lab shows. The middle stays lit because low `shaftFalloff` plus
  the strong HG axis keeps the beam core bright down the length of the beam.

- **Quote regression.** Stored answers **do** use `> ` blockquote lines
  (verified in `storage/conversations/*/turns.json` and `storage/dia_answers/*.md`),
  and the finished path **does** pass ink (`ReadingColumn` → `Typography.build`;
  the `trimmed.hasPrefix(">")` branch is at `Typography.swift:173`). The defect:
  the paragraph style is applied over `NSRange(location: out.length - body.count,
  length: body.count)` (`Typography.swift:194-196`) — a **grapheme** count against
  a **UTF-16** attributed string — and `runs()` drops `*`/`^`/`` ` `` so
  `body.count` ≠ the appended length. That mis-targets the paragraph range, so the
  indent can land on the wrong paragraph. Colour is set on the runs, but for
  `.sand`/`.mono` the `quote` colour is close to body (`Surfaces.swift:153-170`
  + `TextInk.swift:38-58`), so it reads as "same colour". The **streaming
  preview** (`MentatApp.swift:315`, a plain `Text`) never styles quotes at all.

## Plan

### 1 · Edge pile (bug)
Replace the full-span barriers for global transitions with **velocity**: drop the
`solid` for `.scroll` / `.modeChange` / `.resize` (keep their `shift`/`gust`
impulses) so dust is swept and **keeps travelling through the wrap** instead of
stacking. Keep local solids that dust should genuinely flow around (`.panel`,
`.send`). Add a defensive guard in the collision pass to **ignore any rect
spanning ~the full axis** (`w ≥ 0.98 || h ≥ 0.98`), so a full-span barrier can
never trap dust again. Update `SandMotionStoreTests` accordingly.

### 2 · Beam motion + candle (one grounded model)
Formalise `beamAt` as `L = S · cone(θ) · A(θ,t) · p(cosθ;g) · T(d)` — the
participating-media single-scatter form, with the aperture/occlusion idea from
GPU Gems 3 ch.13 and the shipped parameter set from Unreal Volumetric Fog.

- **`A(θ,t)` aperture transmission**: discrete ray cells (existing hashed
  density/width) × a coherent **spatiotemporal turbulence** field: a slow *hold*
  octave (gentle drift/sway) blended with a faster *gust* octave gated by a
  **gust envelope** `gustEnvelope(t, rate)`. The same envelope helper is reused
  for the beams and the candle → one mechanism, DRY.
- **Gust cadence = "both" (user's choice)**: drive the envelope from
  low-frequency fbm so intervals are irregular (~15–30 s) — sometimes it holds,
  sometimes it gusts, like real wind.
- **Candle**: global `S *= candle(t)` envelope (holds steady, then flickers),
  using the shared envelope helper.
- **`T(d)`**: switch to physical **Beer–Lambert `exp(−σ·d)`** (`beamExtinction`),
  which also dims the middle.

### 3 · Legibility
Lower `shaftStrength`, `shaftBg`, `bloomIntensity`; raise extinction; reduce
`shaftPhaseG` so the fan is brightest at the top (as the user likes) and fades
before the reading band. Tune in the lab, then land the same values in the app
preset.

### 4 · Port to the app + migration `sandV17`
Update `SandStyle.sand`, `DesignTokens.Sand`, `TokenCatalog`, `SandPanel`, and
add migration **`sandV17`** (re-seed the sand group) with the dimmed defaults and
all new params (thin, haze, beam motion, foreground, sparkle, extinction).
Without this the app keeps the old bright preset.

### 5 · Quotes (bug)
- Add a test that runs the **stored** multi-line blockquote through
  `TextStyle.attributed(..., ink:)` and asserts: the quoted run has `ink.quote`
  colour **and** a nonzero `firstLineHeadIndent` on **its own paragraph**.
- Fix `build()` to set the paragraph style over the full paragraph using
  **UTF-16** lengths (and include the terminating newline) so the indent lands on
  the quote paragraph.
- Ensure the quote colour is clearly distinct from body for the active look
  (adjust `TextInk` / look values if the test shows near-equality).
- Make the **streaming preview** quote-aware so quotes don't reflow when the
  answer completes.

## Knobs (decision)
Keep the lab lean: expose ~6 meaningful sliders (sway, gust amount, gust rate,
candle depth, extinction, phase g). The rest live in the preset / migration.

## Open question
Need a screenshot or paste of the recent answer that showed quotes wrong, to
confirm it used `> ` lines. If the model inlined the quotes, the fix is in the
formatting (prompt/engine), not the renderer. Proceeding with the test-and-fix
above covers the `> ` case regardless.

## References
- GPU Gems 3 ch.13 — Kenny Mitchell, *Volumetric Light Scattering as a Post-Process*.
- PBRT 4e — *Volume Scattering* (`pbr-book.org/4ed/Volume_Scattering`).
- Scratchapixel — *Volume Rendering* (Beer–Lambert, in-scattering integral).
- Unreal Engine — *Volumetric Fog* (Scattering Distribution = HG g, Extinction, Volumetric Scattering Intensity, volumetric shadows, temporal reprojection).
- Ocean Optics Web Book / Blender *Volume Scatter* — Henyey–Greenstein phase function, `g` = mean cosine.
- Wikipedia — *Bokeh* (disc of confusion, rim).
