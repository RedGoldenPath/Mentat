# TRUTH.md — SandCore (the dust system)

> Single source of truth for **everything sand**: the engine, the lab, the app's
> tokens/panel. The app-wide [`../TRUTH.md`](../TRUTH.md) points here for the surface.
> **Read this first; update it last.** If it is not here, it is not real.

Owner: Raphael · Machine: Apple M5 Max · Updated: 2026-09-26 (rebuilt as
**Langevin dust** floating in a dark room, lit by **soft light beams**).

---

## 0 · North star

**Dust floating in a dark room, lit by a fan of light beams from one source.** A
real **beam system**: from a single point, a **fan of distinct beams** — a mix of
big and small/sharper ones — with near-black gaps, wavering, flickering and
breathing (a gust envelope holds calm then flutters). A black field of motes in
**four parallax depth layers** (far haze · mid · near · hero foreground) — the
closer a mote, the faster it drifts across the screen. The beams are the **light
source for the dust** (Tyndall / single-scatter): a mote lights only inside a beam,
and when a beam flickers brighter the spice it touches brightens in sync. One HDR **exposure +
tonemap** before output, so additive light never clips to white. Sparkles are
**spice-orange**, not white. The cursor and moving UI are **solids** the dust flows
around; global moves are **forces**, never walls. No on-screen spotlight, no glow
mass, no frame, no film grain (a subtle static dither hides banding).

---

## 1 · The model (one system)

Everything is one of three things: the **motion**, the **light**, or the
**renderer**. No solver, no velocity field.

```
MOTION   Langevin force particles (Brownian motion), 20k motes:
            v += (swirl(uv,t) + drift + force)·dt   weak force + the UI push
            v *= exp(-drag·dt)                      drag → mostly stationary
            v += gaussian · brownian · √dt          per-mote shimmer (Box–Muller)
            pos = fract(pos + v·dt)                 endless (periodic)
            × speedScale(z)                         nearer motes move faster
         `force`/`shear`/`gust` come from UI events (sandMotion → SandInputs →
         the update uniform) — global moves are PUSHES, not walls. The cursor is
         a disk + a velocity splat the dust parts around. **Solids are only for
         real UI** (panel slab, send block, pointer) and are never full-span.
         Long life; respawns across the void.
         Refs: Langevin (1908); The Coding Train #24 (a flow field as a *force*,
         not a field to be advected along); ogl gpgpu-particles (integration).
     ▼
LIGHT    a cone of light from a point above the top edge (a god-ray) that is
         ALIVE — the modulation is all in the ANGLE (measured from the source),
         so rays waver but never detach from the origin:
            source   = (shaftX, shaftY), shaftY negative (above the top)
            cone     = smoothstep(spread, spread·0.12, |angle from straight down|)
            per-ray  = own flicker (fbm on time) + breathing + wavering width
            spacing  = time-drifting angular warp (irregular, never static)
            gobo     = slow leaves/window fbm multiplied over the aperture
            gust     = envelope: long calm holds, then a visible flutter
            atten    = exp(−extinction·dist)        (Beer–Lambert)
            glow     = exp(−dist²·7) · sourceGlow    (the soft core)
         The beam is the LIGHT SOURCE for the dust: a mote is lit only inside
         the cone → `brightness = base + beam + glow`, using the SAME field, so
         flicker travels through the dust and gobo shadows darken it.
     ▼
RENDER   faint cone wash + haze in the air + additive layered sprites (4 parallax
         depth bands, near = bokeh + faster) accumulated in HDR → multi-scale
         bloom → ONE exposure + ACES tonemap → a single static dither (not grain).
```

There is **no velocity texture and no solver**. The swirl is a weak force added to
each mote; Brownian noise + drag keep the dust from collapsing onto the swirl's
streamlines (that collapse is what made the old model look like veins).

---

## 2 · Architecture map

| Piece | File | Role |
|---|---|---|
| Shader | `Sources/SandCore/SandShaders.metal` | `dust_update` (Langevin + collision), `dust_vertex`/`dust_fragment`, `shaftAt`, bloom, `sand_display` |
| Pipeline | `Sources/SandCore/SandPipeline.swift` | pass order, RTs, uniforms, `MTKViewDelegate` |
| Vocabulary | `Sources/SandCore/SandConfig.swift` | `SandConfig` + `SandInputs` (one config) |
| Doc | `Sources/SandCore/TRUTH.md` | this file |

| App | File | Role |
|---|---|---|
| Canvas | `MentatApp/.../Sand/SandCanvas.swift` | wraps `SandPipeline`, cadence, fallback |
| Style→config | `MentatApp/.../Sand/SandStyle.swift` | tokens → `SandConfig` |
| Tokens | `DesignSystem/DesignTokens.swift`, `Tokens/TokenCatalog.swift` | `sand.*` round-trip |
| Panel | `Screens/Menu/SandPanel.swift` | user controls |
| Motion store | `Sand/SandMotionStore.swift` | UI events → moving solids + pointer |
| Lab | `SandLab/Sources/SandLab/SandLabApp.swift` | live sliders over the same `SandConfig` |

Build: `export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer`
· lab: `cd app/SandLab && ./build.sh && open SandLab.app`
· app: `cd app/MentatApp && ./build.sh` · gate: `./verify.sh`.

---

## 3 · Config vocabulary (plain names)

Generated from the **`SandConfig` fields** (one vocabulary); the lab and app
panels list them in the same groups.

**Motion (Langevin)** — Swirl · Swirl scale · Drift · Drag · Brownian · Parallax depth
**Obstacles (solids)** — Pointer radius · Rect pad
**Light cone** — Strength · Source X · Source Y · Spread · Rays · Extinction ·
Source glow · Drift · Background
**Beam life** — Flutter · Flutter speed · Gobo · Gobo scale · Gobo drift · Gust amount · Gust rate · Sway · Lean to cursor
**Volumetric light** — Steps · Density (σs) · Extinction (σt) · Medium scale · Medium drift · Jitter · TAA blend
**Haze (bottom)** — Strength · Y · Thickness · Scale · Drift · Pulse
**Dust** — Count · Size · Depth fog · Base · Brightness · Layers · Near scale/bright/blur
**Foreground (bokeh)** — Front z · Density · Scale · Brightness · Sparkle · Sparkle speed
**Layers (debug)** — Far haze · Mid dust · Near dust · Hero foreground (per-layer on/off)
**Look** — Bloom · Bloom threshold · Bloom levels · Dither · Exposure · Tonemap
**Motion cadence** (app only) — Idle window · Impulse scale

Presets (lab): **Still · Wander · Breezy · Elegant (=`.sand`)**.

---

## 4 · Decision log (appended, dated)

- **2026-10-01 · Baseline from SandLab snapshot (sandV26).** The reader's tuned
  SandLab values (snapshot `SandLab/sandlab-baseline.json`, from
  `~/Library/Application Support/SandLab/settings.json`) are now baked into the
  engine (`SandConfig` defaults), the app token defaults (`DesignTokens.Sand`) and
  the `SandStyle` preset, and migration `sandV26` re-seeds the app. Key values:
  swirl 0.284 / swirlScale 1.204 / drag 9.498 / brownian 0.008; shaftStrength
  1.087 / spread 90° / rays 7 / falloff 2.674 / sourceGlow 0.906 / shaftY −0.0735 /
  bg 0.20; exposure 0.179 / bloom 0.421; rays 7; five layers on. `SandConfig` is
  `Codable` so SandLab settings round-trip.
- **2026-10-01 · Hero layer removed → FIVE depth layers (sandV25).** The special
  "hero foreground" (frontZ/frontDensity/frontScale/frontBrightness/frontSpeed)
  was disruptive and is gone. The dust is now **five equal depth layers**
  (`dustLayers = 5`), each toggleable: **Close-up · Near · Mid · Far · Haze**
  (`layerClose/Near/Mid/Far/Haze`); the nearest (close-up) is bigger, blurrier,
  brighter and faster via the existing near scaling. Tunable in SandLab → *Debug
  — show/hide layers* and the app Developer scene.
- **2026-10-01 · SandLab persists its settings (baseline capture).** `SandConfig`
  is `Codable`; SandLab writes the live config to
  `~/Library/Application Support/SandLab/settings.json` on every change (and on
  launch), and loads it on open — so a tuned look can be read back and baked in
  as the new defaults.
- **2026-10-01 · Shared wind REVERTED — beams back to the crepuscular version.**
  The shared-wind experiment (vorticles, then directional) made the beams swirl /
  vanish, which wasn't what was wanted. Reverted `beamSoft` and `dust_update` to
  the **crepuscular (sandV24)** behaviour exactly: beams are the moving big/small
  noise field advected by their own time churn + the gust envelope; the dust is
  its original swirl + drift + events. `windAt`/`rotate2`/`gustEnv` helpers
  removed; the Wind knobs removed from SandLab (back to Sway / Flicker / Wind
  strength / Wind rhythm, where "wind" = the gust envelope that drives both the
  beams and the event pushes). Verified headlessly: identical to pre-wind.
- **2026-10-01 · ONE shared DIRECTIONAL wind (no swirl) drives dust + beams —
  REVERTED (see above).**
  The vorticle wind blew up near its cores (~7×) and, multiplied into the beams'
  advection (×6), threw the occluder sampling far off → **beams vanished**. Fix:
  `windAt` is now a **plain directional** wind (dominant direction with a slow
  turn, no rotational term). The **dust keeps its own swirl** *plus* this shared
  wind; the **beams advect with the same wind at a gentle gain** (~1.5–2). One
  **gust envelope** scales both, so a gust swirls the dust and bends the beams
  **in the same direction and rhythm** — one wind, both effects. "Wander" knob
  removed. Defaults: dir 135°, strength 0.12.
- **2026-10-01 · Shared wind (vorticles) — superseded above.** The dust had
  its own swirl and the beams their own advection — two unrelated winds. Now a
  single `windAt(pos, time)` (a few slow **vortices** + a gentle dominant
  direction — the *Ghost of Tsushima* "vorticle" wind, GDC 2021; divergence-free
  curl) is called by **both** `dust_update` (as the force) and `beamSoft` (as the
  advection of the occluder noise). One **`gustEnv`** scales it, so **a gust
  pushes the dust and bends the beams together** — one scene, one air. Pure
  function of `(pos, time)` → they stay in sync with **no shared GPU state**.
  Knobs: **Wind direction / strength / wander** (+ gust amount/rhythm). Cost:
  unchanged (a handful of hash evals; still one light pass). Reference:
  *Bridson et al. 2007, Curl-Noise for Procedural Fluid Flow*.
- **2026-10-01 · Hero dust: faster + sparser (in front of the camera).** The
  nearest motes now stream **much faster** — `frontSpeed` adds a strong, sustained
  velocity to the `z < frontZ` band and eases their drag, so they read as
  physically close to the lens — and they're far more **sparse**
  (`frontDensity` 0.08 → 0.02). Engine defaults (`SandConfig`); tunable in
  SandLab → *Layers — depth* (Foreground speed / amount).
- **2026-10-01 · Crepuscular rays from a noise field (sandV24).** The beams read
  like a rigid "laser fan". Replaced the fixed per-slot beam loop with a **moving
  noise field across the angle**, sampled on the unit circle (seamless, radial →
  anchored at the source): two octaves — a slow **BIG** field and a quicker
  **SMALL** one — each advected independently and **soft-thresholded**, so beams
  **bloom in and dissolve out at irregular, cloud-like intervals** (the real
  phenomenon is *crepuscular rays*; the technique is curl-noise/domain-warped
  advection). This is genuinely **constant birth/death but not on a fixed beat**
  and gives a **big + small mixture**. Knobs: **Beam churn** (`volDrift`),
  **Cloud scale** (`volScale`), **Big ↔ small mix** (`shaftVary`), **Beam
  wander** (`shaftWarp`). Still one pass, no march/supersample — measured **0.3
  ms/frame at 2560×1440**. **120 fps restored** (adaptive: 120 while interacting,
  60 at rest, paused when hidden).
- **2026-10-01 · Lean pass — removed the march/supersample/TAA (sandV23).**
  The light couldn't hold 120 fps: `sand_light` rendered at **2× supersample**
  and ran a **24-step march** whose `beamSoft` was **independent of the step**
  (recomputed identically 24×) over a loop of up to 12 beams × 2 fbm — ~100×
  more work than needed. Now the light is **one pass, evaluated once per pixel**
  (the march added nothing since it didn't vary with depth), **no supersample**,
  **no temporal buffer/blit**, **60 fps cap**, dust **20k → 12k**. Measured
  headlessly: the light pass is **1.34 ms/frame at 2560×1440** (was ~100× that).
  The beam look is unchanged. This is the shape a UI background should keep:
  cheap, one pass, measured.
- **2026-10-01 · Real beam system: one source, a fan of distinct beams (sandV22).**
  The window-band + fbm-density attempt looked like mud (a lit rectangle +
  noise, no real shafts). Replaced with a proper **beam system**: `beamSoft`
  is now a **hashed array of soft Gaussian rays** anchored at **one source**,
  each with its own width (big vs small/sharper via `shaftVary`), irregular
  spacing (`shaftWarp`), brightness and **flutter** (`beamFlutter`) — distinct
  shafts with near-black gaps, wavering and flickering. The fan is bounded by
  the cone (`shaftSpread`) and fades with distance (`shaftFalloff`), with a
  source glow. The march's fbm density (the "dirt") is gone — a clean depth
  fade only. Dust still lit by the same light. Tunable in SandLab under
  **Light — beams**. Verified headlessly: 5 distinct strong humps per row.
- **2026-10-01 · Directional window god-ray (sandV21).** Reader wanted *multiple*
  beams (a typo had read as "one beam") that look like **sun through a window**.
  Replaced the point-source fan with a **directional (near-parallel) light**: a
  lit band across the frame at `lightAngle` (default −52°, down-left from the
  upper-right), width `windowWidth`, with several soft shafts (`shaftRays`) that
  blur together with distance (`shaftPenumbra`), fading into the room
  (`shaftFalloff`), plus a warm **pool** where they land (`poolStrength`, bottom
  of the frame). `goboStrength` is the optional leaf dapple (low by default).
  No pointer coupling. Tunable in SandLab under **Light — window (god rays)**.
- **2026-10-01 · ONE beam, no mouse interaction (sandV20).** Reader feedback: the
  multi-shaft / leaf-dappled look was wrong (it should be **a single beam**) and
  the pointer coupling was unwanted. Defaults now: **rays 1, vary 0, gobo 0** →
  `beamSoft` returns one smooth cone from the source (no striations, no leaf
  breakup); `lightLean 0` and the pointer parallax is no longer fed to the shader
  (`SandCanvas`/SandLab send `parallax = 0`), so the light is **not** tied to the
  mouse. `lightSway 0.4` keeps the single beam gently moving; `spread 20°`. The
  leaves/gobo stay available as knobs (turned off by default).
- **2026-10-01 · The light moves — moving leaves + sway + lean (sandV19).**
  The shafts were a *static* angular pattern with a slowly drifting gobo (so it
  read as "fixed beams + one wandering dark blob"). Reworked `beamSoft` so the
  shafts are the **moving shadow of drifting leaves**: window slats (the shaft
  structure) plus two leaf layers — **near leaves faster than far** — scrolled by
  a **wind** envelope, so the light flutters then holds. Added **source sway**
  (`lightSway`) and **lean toward the pointer** (`lightLean`) so the whole cone
  tilts. `beamFlutter` now flickers individual shafts. The **dust samples the
  light texture** in the vertex stage (lit by the same moving light — Tyndall
  consistent). The **cursor clears much less dust** (`obstacleRadius` 0.015 →
  0.008). The everyday **Sand panel is plain English** (Dust · Light · Light
  movement · Picture); the technical knobs moved to the Developer scene. Verified
  headlessly (frame-to-frame change 0.155, peak 5.6) + 97/97 tests.
- **2026-10-01 · Volumetric light engine — real shafts, no aliasing (sandV18).**
  The analytic cone (`beamAt` painted in `sand_display`) read as a *drawn shape*
  and its `floor()`-cell ray profile + high-frequency filaments aliased (no AA
  existed). Replaced the display's light term with a **screen-space volumetric
  ray-march** (`sand_light`): step ~`volSteps` samples through a fog/dust medium,
  accumulate `L += T·σs·density·light·ds` with `T *= exp(−σt·density·ds)`
  (Beer–Lambert). Because it is an **integral**, the shaft is soft and reads as
  light in air; the illumination profile (`beamSoft`) uses a continuous periodic
  ray function (no `floor` seams) + gobo + gust. Antialiased two ways:
  **2× supersample** of the light pass, then **temporal accumulation** (`sand_light_taa`,
  Halton-jittered, history blend + 3×3 neighbourhood clamp) — **light-only**, so
  the dust stays crisp. New knobs `volSteps · volDensity · volExtinction ·
  volScale · volDrift · volJitter · taaAlpha`; `shaftFalloff` is the medium
  extinction σ. Runtime-only change (no re-embed); built in SandLab first. Verified:
  Metal + SandLab + app build; 97/97 tests.
- **2026-10-01 · Living light + parallax depth + forces-not-walls (sandV17).**
  Executed §11. The couplings the app had always *computed* (`SandMotion`:
  parallax/shift/shear/gust/breath) were finally **plumbed into the GPU**
  (`SandInputs` → `DustUpdateUniforms`/`DustRenderUniforms`/`DisplayUniforms`) —
  they were dead before, which is why the surface felt flat. Beams are now
  **alive**: each ray flickers on its own (`beamFlutter`), spacing drifts
  (time-varying angular warp), a slow **gobo** (`goboStrength/Scale/Drift`) sweeps
  the aperture, a **gust envelope** (`gustAmount/Rate`) holds then flutters, and
  distance is **Beer–Lambert extinction** (`shaftFalloff` repurposed as σ). The
  beam is the **light source for the dust** (same field → flicker syncs). Dust is
  **four parallax layers** (`dustLayers=4`; nearer = faster via `parallaxDepth`;
  pointer split in the vertex stage) with **per-layer debug toggles**
  (`layerFar/Mid/Near/Hero`, in the Developer scene). One **exposure + ACES
  tonemap** (`exposure`, `tonemap`) before output stops additive clipping to
  white; sparkles get their own **spice-orange** colour (`sparkleColor`); film
  grain → a subtle static **dither**. Global transitions (`.scroll`/`.modeChange`/
  `.resize`) are **forces, not full-span colliders** (the border-line bug); a
  guard drops any rect with `w ≥ 0.98 || h ≥ 0.98`. Verified: Metal + SandLab +
  app build; 96/96 tests.
- **2026-09-26 · Light = a cone from top-center, with a source glow; grain gone.**
  Per the user's second reference (`istockphoto-2197615580`): the parallel diagonal
  bands read wrong, so the light is now a **cone from a point above the top edge**
  (`shaftX/Y/Spread/Rays/Falloff`) with a **soft source glow** (the reference's
  blown-out core). The **film grain is removed** entirely (a single 1/255 dither
  remains only to hide banding). Migration `sandV16`.
- **2026-09-26 · Pointer = the cursor tip, and small.** The pointer collider was a
  0.05-radius disk that engulfed the whole cursor; it is now a **small area at the
  cursor tip** (`obstacleRadius` 0.05 → 0.015), and the app maps the hover position
  into the **canvas's own frame** (`sandFrame`) so it lands on the exact pixel under
  the tip (previously it used `contentSize`, which shifts with the inspector/insets).
- **2026-09-26 · Rebuilt as Langevin dust + soft beams.** The user's steering: dust
  should be *mostly stationary, floating in a room* (Last-of-Us opening), reacting to
  moving UI by flowing around it — and the earlier curl-noise/tracer build still read
  as veins. Replaced the whole engine with **Langevin force particles** (weak swirl +
  drag + Brownian; §1) and **procedural soft beams**, and made the pointer + UI
  **collision solids** rather than a push. Deleted the curl-noise flow, the Stam
  solver, all velocity/dye/pressure RTs, `SandWind.swift`, and the whole
  wind/turbulence/bloom/grains vocabulary. Tokens/panel migrated (`sandV15`). Lab
  presets still/wander/breezy.
- **2026-09-25 · Dust rework (curl-noise flow → tracers → off-screen light).**
  (Superseded by the Langevin rebuild above.)
- **2026-09-25 · Gravity + off-screen bottom light.** Dyed-fluid pull toward a warm
  bottom strip; uniform gravity is divergence-free so projection can't remove it
  (vertical curtains) → dye-weighted Boussinesq buoyancy. (Superseded.)
- **2026-09-25 · Unified architecture (canonical fluid + tracers).** Stam / GPU Gems
  ch.38 / Dobryakov solver; everything a source/field/renderer. (Historical.)
- **2026-09-25 · Reference rework (roaming bloom + film grain).** (Historical.)
- **2026-09-25 · Rebuilt (passive scalar + saltation).** (Historical.)
- **2026-09-25 · Implemented / Palette / Density / Grain / Hand / Window / Systematize.**
  (Historical.)

---

## 5 · Removed / rejected (do-not list)

- **Advecting dust along a velocity field** (curl-noise flow or solver) — passive
  tracers converge onto streamlines and read as **veins**. Dust gets a *force*, not a
  field; Brownian + drag keep it loose.
- **Light as an on-screen source / point light / spotlight** — forms a blob. The beams
  are a gobo (parallel bands + envelope); there is no source in frame.
- **Emissive dye mass** ("lava lamp") and the `emission` term.
- **Gravity as a uniform body force** — divergence-free → domain-wide curtains.
- **Bottom light strip / sponge `edgeFade`** — gone with the fluid.
- **Multi-stirrer / high-confinement looks** — removed. **Static screen-space
  grain** as a *look* — removed (a tiny `dither` ~0.012 remains only to hide
  banding; that is not a grain overlay). **A global ad-hoc contrast remap** and a
  **global centre dim** — removed. *(2026-10-01: a per-frame HDR **exposure +
  ACES tonemap** is NOT the banned contrast remap — it is a single display
  transform that stops additive clipping; and a **reading scrim** may return as a
  targeted layer, not a global centre dim. Both are display-stage, not look
  grade.)*
- **The whole old sand vocabulary** (`windStrength`, `turbulence*`, `bloomSize`,
  `grain*`, `haze`, `warmth`, `filmGrain`, `simResolution`, …) — replaced; migration
  `sandV15` re-seeds the group.

---

## 6 · Known artifacts → fixes (watch list)

- **Black canvas / nothing renders** → a compiled kernel is missing from the `.metal`,
  so `ready=false`. Every `comp("…")` name in `buildPipelines` must exist as a `kernel`
  in `SandShaders.metal`.
- **Dust invisible** → too dim/foggy: raise **Brightness**, raise **Base** (visibility
  outside the beams), lower **Depth fog**, raise **Count/Size**.
- **Dust looks like veins/streams** → the swirl force is too strong vs Brownian: lower
  **Swirl**, raise **Brownian**, raise **Drag**.
- **Dust too jittery** → lower **Brownian**, raise **Drag**.
- **Beams invisible** → raise **Strength**, raise **Source glow**, lower **Falloff**
  (the cone reaches further), raise **Background** (air wash).
- **A bright blob** → an on-screen point light; banned (a cone from above is fine,
  a floating orb is not).
- **Film grain** → removed; keep only a very low static `dither` (~0.012) to hide
  banding — never a screen-space noise overlay.
- **Dust not reacting to UI** → the solid's event has decayed (`tau`), or `Impulse
  scale` is 0.

---

## 7 · Open questions

1. **Reading scrim (deferred):** text legibility over the brightest sand frame is
   not solved by the tonemap alone. Reintroduce a *targeted* scrim behind reading
   areas (layer L5) when the reader asks — not a global centre dim (banned).
2. **Temporal ghosting / perf:** the light is now supersampled + temporally
   accumulated (`sand_light_taa`, light-only). Watch for trails on fast light
   changes and for fps cost of the 2× march; lower `volSteps`/supersample if the
   HUD dips.
3. **Near-mote streaks:** fast parallax on big hero sprites can strobe; cap the
   near velocity or add velocity-stretched sprites (motion blur) if needed.
4. **Solids:** UI events still emit approximated rects (`SandMotionStore.solids`);
   wire real panel frames when the shell exposes them.
5. **Count vs perf:** 20k is calm on an M5; the hero layer adds overdraw — watch
   the fps HUD before raising.

---

## 8 · References

- Langevin, *Sur la théorie du mouvement brownien* (1908) — the force model.
- The Coding Train #24, *Perlin Noise Flow Field* — a field used as a *force*.
- ogl (`oframe/ogl`), `gpgpu-particles.html` — GPU integration of many point particles.
- three.js, `webgl_points_sprites.html` — additive soft sprites, exponential depth fade.
- Hughes/van Dam, *Physically Based Rendering* — the Tyndall effect (light through dust).
- three-good-godrays (Ameobea) — soft-beam reference (studied; not ray-marched here).
- Kawase — dual-filter bloom. Karis — prefiltered bloom.

---

## 9 · Tuning defaults snapshot

Kept in `SandConfig` (single source; the panel reads it).

- Motion: swirl 0.25 · swirl scale 0.9 · drift 0.0 · drag 3.0 · brownian 0.015 ·
  parallax depth 0.6.
- Obstacles: pointer radius 0.008 (a small area at the cursor tip) · rect pad 0.015.
- Beams: one source at (0.50, −0.06) · fan width 42° · **rays 7** (mixed big/small) ·
  big↔small 0.5 · irregular spacing 0.6 · softness-with-distance 0.4 ·
  fade 0.8 · strength 1.6 · source glow 1.2 · colour (1.0, 0.60, 0.28).
- Beam life: flutter 0.55 · flutter speed 0.7 · **gobo 0 (off)** / scale 3.0 / drift 0.06 ·
  gust amount 0.5 / rate 0.07 · sway 0.4 · **lean to cursor 0 (no mouse)**.
- Volumetric light: steps 24 · density (σs) 1.5 · extinction (σt) 1.2 ·
  medium scale 2.2 · medium drift 0.04 · jitter 1.0 · TAA blend 0.18 · light
  supersample 2× (light-only temporal AA).
- Dust: count 20000 · size 2.2 · depth fog 1.6 · base 0.10 · brightness 1.0 ·
  layers 4 · near 1.6 / 1.15 / 0.25.
- Foreground (hero): front z 0.18 · density 0.06 · scale 4.2 · brightness 1.25 ·
  sparkle 1.2 · sparkle speed 3.0 · sparkle colour (1.0, 0.55, 0.22).
- Look: bloom 0.20 · threshold 0.5 · levels 4 · dither 0.012 · exposure 1.15 ·
  tonemap 1 (ACES).
- Layers (debug): all four on by default.

---

## 10 · Change protocol

1. **Read this first.** Then `SandConfig` + the shader stage comments.
2. Make the change in `SandCore` (or app wiring).
3. **Rewrite** the "current state" sections; **append** a dated line to §4; move
   anything rejected into §5; update §7.
4. Build lab + app; run `verify.sh` (tests + ≤30 MB).
5. Keep §3 and the panels in step with `SandConfig`.

---

## 11 · Layer model, invariants & executed changes (2026-10-01)

> **DONE** (decision log §4). Owner-reported defects: the cursor disk missed the pointer tip (worse
> with the right Inspector open); sparkles were too bright/white and hurt legibility; the beams
> didn't flitter like light through a window/tree; dust pooled into a line at the borders / on
> resize. All fixed by **layering + invariants** (below). This section is kept as the rationale;
> the shipped values are §9. The reading-scrim decision is **deferred** (§7).

### 11.0 · What shipped
- **Plumbing (was missing):** `SandMotion` → `SandInputs` → `DustUpdateUniforms`/`DustRenderUniforms`/
  `DisplayUniforms`; the couplings were computed app-side and never reached the GPU before.
- **Beams:** per-ray flutter, time-drifting spacing, gobo, gust envelope, Beer–Lambert extinction;
  the beam is the dust's light source.
- **Dust:** four parallax layers (near = faster), pointer-parallax split, per-layer debug toggles.
- **Render:** one exposure + ACES tonemap; spice-orange sparkle colour; film grain → subtle dither.
- **Motion:** global transitions are forces, not full-span colliders (+ a full-axis guard).

### 11.1 · Layer model + invariants (the frame for every fix)

Compositing layers (back→front), like a VFX comp — currently one undifferentiated `sand_display`:

| Layer | Content | Rule |
|---|---|---|
| L0 Atmosphere | cone wash + haze | low / screen |
| L1 Gobo | moving "leaves/window" modulating the beam | multiply (**missing**) |
| L2 Mid dust | additive depth-faded sprites | additive, HDR |
| L3 Foreground bokeh | sparse large motes | additive, very low |
| L4 Interaction | cursor disk + UI solids | collision |
| L5 Reading scrim | luminance guard behind text | damp (**removed in sandV13**) |
| L6 UI ink | text/chrome | surface-first |

Invariants: (1) the interaction space **is** the rendered canvas space; (2) global transitions are
**forces**, colliders only for real UI, never spanning the domain or a full axis; (3) accumulate in
linear HDR and **tonemap once** before 8-bit — never let additive clamp to white; (4) text separation
comes from a **surface/scrim**, never a glow; (5) motion uses an envelope with rest windows, gated by
Reduce Motion.

### 11.2 · Pointer on the tip (Invariant 1)

**Cause:** the sand renders `.ignoresSafeArea()` (`SandCanvas.swift:38`) into the full window (incl.
the hidden-titlebar band), but the hover is mapped through `sandFrame`, measured on the *safe-area*
detail ZStack (`MentatApp.swift:1638-1651`) — origins differ by `topInset` (and x when the sidebar
changes). A fallback to `engine.contentSize` (`:1649`) re-introduces the bug because `contentSize`
tracks **ChatView** and shifts when the Inspector opens; the animated narrowing then fires a storm of
`.resize` impulses (`:1665-1670` → `SandMotionStore.swift:181-186`), which is the "misbehaving" disk.

**Fix:** the canvas exposes its **own** frame and that is the only mapping source; delete the
`contentSize` fallback; stop emitting `.resize` from animated layout (resize is a window event); pass
the already-computed `pointerVelocity` (`SandMotionStore.swift:60,90`) to the GPU.

### 11.3 · Sparkles, colour, legibility (Invariants 3 + 4)

**Cause:** (a) no scrim — removed in `sandV13` (`DesignStore.swift:77`, §5), so sand sits behind text
at full strength; (b) additive `one/one` into `rgba16f` (`SandPipeline.swift:141-143`) + gamma'd bloom
add (`linearToGamma3`, metal L437) + `bgra8` clamp (metal L442) → a sparkle (×7, metal L287) blows to
white; (c) sparkle has no colour of its own — it inherits the pale `shaftColorNear` `(1,.82,.62)`;
(d) `sparkle`/`sparkleSpeed`/`shaftColorNear`/`haze*` are engine-only (not in tokens/panel).

**Fix:** ACES/Reinhard **tonemap once** in `sand_display`, accumulate in HDR; give sparkles a **spice
orange** colour uniform from the `spice` token (`ThemeEnv.swift:24` `(0.78,0.42,0.14)`); raise
`bloomThreshold`, lower `bloomIntensity`; **reintroduce a reading scrim as layer L5** (damp only behind
reading/pane areas, keep full shimmer in margins). Verify text over the busiest frame meets APCA Lc ≥ 60
/ WCAG 4.5:1. **Open decision:** targeted reading scrim (recommended) vs a global dim.

### 11.4 · Beams flitter (Invariant 5)

**Cause:** `beamAt` (metal L85-122) has a static per-ray width (`h3`), a single sin "breathing", and a
warp evaluated on angle only (L97, no time); there is no gust or occluder. `SandMotionStore` computes a
gust/breath envelope but **never sends it to the GPU** (`SandCanvas.swift:60-73` drops it).

**Fix:** add a slow **moving gobo/occluder mask** (fBm "leaves/window") multiplied into the cone; drive
it with a **gust envelope with rest windows** (hold → flitter → hold), shared by beams + source glow,
wired from `SandMotion`; make per-ray width/warp time-varying; gate amplitude by Reduce Motion. The
gobo is already doctrine (§0/§1 "gobo (parallel bands + envelope)").

### 11.5 · Dust must not pool into lines (Invariant 2)

**Cause:** global transitions emit **full-span collider bars** — `.scroll` full-width top/bottom,
`.modeChange` full-width top, `.resize` full-height right (`SandMotionStore.swift:169-186`). The
resolver projects to the nearest face and zeroes the inward velocity (`SandShaders.metal:186-198`); a
wall spanning the domain has no way around it and the periodic wrap captures the seam → a parked line.
The dispersing force fields (`shift/shear/gust`) are computed but never consumed.

**Fix:** remove the full-span solids for `.scroll`/`.modeChange`/`.resize`; apply them as **velocity
impulses** in `dust_update`. Keep colliders only for real UI (panel slab, send block, cursor disk),
minimum-thickness, never full-axis/seam; add a guard dropping any rect with `w ≥ 0.98 || h ≥ 0.98`;
update `SandMotionStoreTests`.

### 11.6 · Plumbing & doctrine

- **Subsetting gap:** `SandConfig` has ~40 knobs, tokens/panel expose ~23; the fixes need
  `sparkle`, `sparkleSpeed`, sparkle colour, beam-motion, scrim, tonemap, `haze*`. Add them through
  `SandConfig → SandStyle → DesignTokens.Sand → TokenCatalog → SandPanel`, plus migration **`sandV17`**
  (re-seed the sand group; pattern of `sandV13-V16` in `DesignStore.swift`).
- **Doctrine:** move "centre dim" out of §5 (we add a *reading scrim*, distinct from a global centre
  dim); add the gobo + gust envelope to §0/§1/§3; refresh §7; the app-wide `TRUTH.md` sand paragraph is
  stale.
- **Verify (matrix, worst-case first):** build lab+app; screenshots over **System (light/dark) · Paper ·
  Mono** × **empty / streaming / long answer / citations open / Inspector open** × accent off/on; APCA
  check; Reduce Motion calm; no border line after scroll/Inspector/resize; disk on the tip across
  windows and with the sidebar collapsed; `./verify.sh`.

**References:** Apple HIG *Pointing devices / Pointer interactions*; Apple HIG *Materials*;
APCA / WCAG 2.2 1.4.3; GPU Gems 3 ch.13 (Mitchell, light shafts via occluders); Unreal *Volumetric Fog*
(light shafts, extinction); Karis 2013 prefiltered bloom; Narkowicz ACES-filmic fit; Langevin (1908).

**Deferred:** the reading scrim (targeted vs global dim) — the reader will decide
later; see §7. Excluded from this pass on purpose.
