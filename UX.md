# UX.md — Mentat interface source of truth

Companion to `TRUTH.md` (brain) and `ARCHITECTURE.md` (structure). This is the single
source of truth for the **interface**: its values, its element vocabulary, its
composition, its actions, and the decisions behind them. Keep it living — rewrite,
don't append.

> Metaphor: **the way Apple engineers a laptop's internals** — one enclosure, one logic
> board, one bus, unified memory, no redundant connectors, precision fit. Beautiful,
> simple, powerful.

---

## 0 · Principles

- **One enclosure.** All interface state lives in one observable store (`AppStore`),
  injected at the `App` scene (Apple's *single source of truth*).
- **One bus.** `Action → reduce → AppState`; effects are the only side exits. No view
  mutates shared state out-of-band.
- **Unified memory.** One **token graph**; every element resolves from it. No per-view
  literal copies.
- **No redundant connectors.** One colour system, one material system, one type system,
  one layout system, one state system.
- **Serviceable modules.** dsh-style slots + effect services; each part swappable and
  reversible.
- **Thermal discipline.** Typed native rendering; per-element observation; no per-token
  typesetting.
- **Precision fit.** Values snap to scales (8-pt space, radius/type/shadow ramps,
  baseline).
- **One authority.** Colour resolves from the look (`SurfaceLook` → `ColorTheme`); contrast
  is a guarantee by construction (WCAG-verified), never sampled from a photo. There is no
  wallpaper subsystem — the only background is the procedural sand.

## 1 · References (verified)

| System | What we take |
|---|---|
| **DeepSeek Harness / Cordis** (`deepseek-ai/deepseek-harness`) | Everything-is-a-plugin; services + typed events + reversible effects; **4 slot kinds** `single·list·keyed·chain`; Component Factories; store seats; declaration discipline. |
| **W3C Design Tokens** (`designtokens.org`) | Token graph: primitive→semantic→component; aliases `{group.token}`; composite types (shadow, gradient, typography, border, stroke, transition); `$type/$value/$description/$deprecated`; resolution order + cycle detection. |
| **SDUI** — Airbnb Ghost, Lyft Canvas, Spotify Encore, Yelp CHAOS, Twitter feed | Recursive `{type,key,props,children,actions,metadata}` element schema; component registry; recursive renderer; declarative actions; versioning; per-element error boundary; `semantics` for a11y. *Composition is data; vocabulary is code.* |
| **Apple** — HIG, SwiftUI Model data / Observation | Single source of truth via `@Observable` + `@Environment`; minimal updates; system materials; dynamic type; accessibility. |
| **Elm / TCA / Redux** | Unidirectional `State → View → Action → reduce → State`; effects as values. |
| **Generative UI** — Vercel AI SDK `streamUI`, Claude tool-use + JSON-Schema streaming, MCP Apps (SEP-1865), OpenAI Apps SDK, CopilotKit | The model emits UI from a catalog; two-phase skeleton→content; registry fallback; sandboxed HTML apps with typed JSON-RPC. |

## 2 · Token graph

Primitive → semantic → component; aliases resolve (`bubble.fill = {color.surface}`).

- **color** · `background, surface, surfaceTint, ink, inkDim, accent, secondary, tertiary, border, good, bad, onAccent`
- **type** · `hero, title, body, bodyMono, label, caption, micro, meta, emphasis` + `prose` composite
- **space** · `xxs,xs,s,m,l,xl,xxl,xxxl` (8-pt grid)
- **radius** · `s,m,l,xl,circle,continuous`
- **material** · `MaterialRole` = `material·tonal·outline·solid·glass`; default `.tonal`
- **shadow** · `flat,low,mid,high` (composite)
- **motion** · `smooth,snappy,bubble,stagger,ambient,parallax` + reduce-motion
- **sand** · `enabled, intensity, waveScale, warp, drift, grain, scrim, ambient, wander, grainFlow, colorShift, idleWindow, impulseScale`
- **layers** · `art<scrim<content<chrome<overlay<cursor`

Persisted as **W3C `.tokens.json`** with the native `DesignTokens` blob as the fast cache.
Migrations are additive and only ever raise legibility.

## 3 · Element catalog

Every visual element is one `ElementKind` with one **recipe** over tokens. Instances
carry props + at most a `StyleRef` override.

Shell: app-frame · rail · center-column · inspector · window-chrome
Background: sand (living) · grid-overlay · armature
Header: wordmark · tagline · disc (sidebar/inspector) · menu-circle
Menu: drip-down glass menu · vertical icon bar · panel
Transcript: **user-bubble · assistant-bubble · system-message** · role-header · header-rule ·
reasoning · citations-row · citation-chip · message-actions · edit-field · streaming-preview · meta-line
Composer: input · attach · send/stop · model-picker · attachment-chip · suggestion-list · offline-banner
Inspector: tab-strip · artifacts · citations · source · files · context · meter · stat-row
Sidebar: find-field · layout-toggle · section-header · conversation-card
Reader: reading-column · source-plate · pager
Settings: setting-row · option-slider · option-pills · pill-toggle · setting-pill
Developer: section-chip · design-panel · armature · perf-hud · engine-panel
Menu: sand-studio · looks-studio · settings · command-palette · icon-rail
Controls: chip · action-button · pressable · glass-control · slider/stepper/toggle/segmented
Generative: chart · table · kpi-card · diagram · mind-map · image · html-widget

### Bubble (decided)
Dedicated **Bubble** controls, separate from chrome: `role` (default `.tonal`), `opacity`
(user-dialable), `minOpacity` (legibility floor — clamp `max(min,opacity)`), **distinct
user (more opaque/tinted) vs assistant (more translucent)**. Adaptive ink preserved.

## 4 · Composition & slots

dsh slot kinds: `single` (one occupant) · `list` (ordered) · `keyed` (by key) · `chain`
(entries elect themselves). Features register occupants; the core is never edited.

Canonical shell: left **rail** (history) · centre capped **stream** (~720–768 px, single
column) · right collapsible **Inspector** (artifacts·citations·source·files·context).

## 5 · Actions & state

One `AppState`, one `Action`, one `reduce`; effects (transport · engine-process · stream ·
persist · generative) are values. The engine's **data** lives in effect services; the
**interface** state lives in the store.

> Naming: the Swift `Engine` class (app-internal facade) is renamed **`AppStore`**; the
> Python **brain** (`mentat2/`) is untouched and is never called "the Engine" here.

## 6 · Generative UI

- **Registry path (default):** the model emits a `SceneSpec { nodes:[ElementSpec],
  artifacts:[ArtifactSpec] }`; streamed via JSON-schema + partial-JSON; unknown kinds →
  fallback; per-element boundary. Renders in the transcript and the Artifacts tab.
- **HTML-app path:** MCP-Apps pattern — `ui://` `text/html;profile=mcp-app` in a locked-down
  sandboxed `WKWebView` (no network; host-brokered data; typed JSON-RPC; consent for
  UI-initiated tool calls).
- **First kinds:** charts · tables · KPI cards · diagrams · mind-maps · images.

## 7 · Decisions log

- 2026-09-25 · **UX.md created** as the interface source of truth, parallel to TRUTH/ARCHITECTURE.
- 2026-09-25 · **Living sand** — the surface never rests. An ambient clock travels two broad
  amber masses across the frame; the amber↔deep-orange transition follows the domain-warp
  field's velocity (organic, not a flat sine); fine grain is **advected along the warp field**
  so it streams like wind-blown sand. Bigger reactive impulses (send/panel/mode) surge on top.
  New `sand.*` tokens (`ambient · wander · grainFlow · colorShift`) round-trip through the token
  graph; a `sandV1` migration re-seeds existing installs. SandLab compiles the **shipping**
  shader (single source), so tuning is real. Refs: Inigo Quilez *domain warping*; Apple
  WWDC24 *Create custom visual effects with SwiftUI*; WWDC18 *Designing Fluid Interfaces*.
- 2026-09-25 · **De-wallpapered — one colour authority.** Removed the whole photo subsystem:
  bundled art, `BackgroundAnalysis`/`ImageAnalyzer`/`ColorResolver`/`ColorControls`/`PaletteScheme`,
  `artworkAccent`, the Background gallery and the OKLCH Palette panel. `SurfaceLook → ColorTheme`
  is now the single authority; `AppTheme` collapsed to light/dark (only matters for `.system`).
  `SourceReader` and the window appearance resolve from the look. The Palette panel became the
  **Sand studio**. Net: 126 MB → **9 MB**, and the sand is the only background. A `verify.sh`
  size gate blocks regressions.
- 2026-09-25 · **P7 done** — token graph engine (W3C-shaped: aliases, cycle detection,
  composite types) + native bridge. Colours resolve from the look (surface-first); the graph
  carries the primitives, semantic roles, and the `sand` group.
- 2026-09-25 · **P8 (bubbles) done** — bubbles are now a token-driven element with their own
  material role + opacity, distinct user/assistant, hard legibility floor. The hard-coded
  scrim is gone.
- 2026-09-25 · **P9 done** — slots now have dsh's four kinds and declaration discipline.
- 2026-09-25 · **P12 slice done** — the model can author UI from a client-owned element
  vocabulary (`scene`/`genui` blocks → KPI/chart/table/diagram); `html` blocks render in a
  locked-down sandboxed `WKWebView`. Unknown kinds degrade safely; per-element construction
  is declarative, never arbitrary code in the core.
- 2026-09-25 · **P10 started** — the interface now has one bus (`AppStore.send` → `UIReducer`
  → `Effect`) and one owner for the duplicated `sidebarVisible`/`appearance` state. `Engine`
  remains the data/effect service; folding it into `AppState` is the next strangler step.
- 2026-09-25 · **P11 started** — the Developer scene hosts a studio: edit a scene live and see
  the registry render it; export/import the token graph as W3C `.tokens.json`.
- 2026-09-25 · **Visibility pass** — the plumbing was real but unfelt. Added the Looks studio
  + presets with a visibly different default look, a distinct inspector icon, inline
  generation, and right-click bubble restyling. Lesson: ship visible payoffs first, then the
  architecture that makes them cheap.
- 2026-09-25 · Systematize the shipping app (not a prototype). Apple-native material/tonal;
  Liquid Glass demoted to one `MaterialRole`.
- 2026-09-25 · Unified visual architecture approved: tokens → element registry → slots →
  one store → authoring → generative UI. Full unidirectional rewrite (strangler) of the
  app's Swift `Engine` into `AppStore`; brain untouched.
- 2026-09-25 · W3C `.tokens.json` for interop; native blob as cache.
- 2026-09-25 · Bubbles get dedicated material + opacity controls; distinct user/assistant;
  hard legibility floor.
- 2026-09-25 · Widgets locked down: no network, host-brokered, typed JSON-RPC.

## 8 · Phase status

- [x] **Step 0** — `UX.md` created.
- [x] **Living sand + de-wallpaper** — the surface is a living subsystem (ambient travel +
  warp-driven amber↔ember + advected grain + stronger reactive impulses), fully token-driven
  and part of the token graph; the Sand studio is its one control surface. The entire photo
  subsystem is gone, leaving `SurfaceLook → ColorTheme` as the single colour authority and the
  sand as the only background. App **126 MB → 9 MB**; `verify.sh` gates tests **and** bundle
  size. Files: `DesignSystem/Sand/*`, `Screens/Menu/SandPanel.swift`, `SandLab/`.
- [x] **P7** — `TokenGraph` (alias resolution + cycle detection + W3C `.tokens.json`
  round-trip) + `TokenCatalog` native bridge + `DesignStore.export/importW3CTokens`
  + W3C export in the Design panel; 7 token tests.
- [~] **P8** — `Bubble` tokens (role + user/assistant opacity + floor) and `BubblePlate`
  drive user/assistant/system bubbles (was a hard-coded scrim); Bubble controls in the
  Design panel; 6 bubble tests. *Remaining: convert the rest of the element catalog to recipes.*
- [x] **P9** — `SlotRegistry` upgraded to dsh's four kinds (`single`/`list`/`keyed`/`chain`)
  + declaration discipline (declaring is authoritative) + reversible `dispose`; 6 slot tests.
- [~] **P12** — generative-UI slice: `SceneSpec`/`GenElement` schema + `SceneParser`, a
  kind→view registry (`KPI` · bar/line `chart` · `table` · `diagram`), wired into the
  Artifacts tab, plus a **locked-down `WKWebView`** for `html` blocks (ephemeral store,
  network blocked, typed message channel). Renders a model-authored `scene` block as real
  UI (screenshot-verified: KPI + bar chart + table). *Remaining: mind-map canvas, streaming
  two-phase render, widget→Action bridge.*
- [~] **P10** — unidirectional store founded: `UIReducer` (pure `State`/`Effect`/`reduce`) +
  `@Observable AppStore` (one enclosure, one bus); `UIAction` now flows through
  `AppStore.send` and the duplicated `@AppStorage("sidebarVisible")`/`("appearance")`
  connectors are gone from both views. 3 reducer tests. *Remaining: fold `Engine`'s data
  state into `AppState` (strangler continues), migrate the remaining @AppStorage keys.*
- [~] **P11** — authoring studio in the Developer scene: live scene-JSON editor with an
  instant `SceneRenderer` preview, plus W3C token export (copy `.tokens.json`) and import
  (from clipboard). *Remaining: recipe/component editors, scene inspector chrome.*
- [ ] **P8 (full)** — convert the remaining element families to recipes.
- [x] **Visibility pass** — made the system *felt* (the architecture was invisible):
  - **Inspector icon** → `wrench.and.screwdriver` (Resolve-style tools), distinctly different
    from the history `sidebar.left`; Developer scene glyph → `hammer`.
  - **Looks studio** in the everyday menu (`paintbrush.pointed`): **Atlas · Noir · Paper**
    presets with preview thumbnails + live material and bubble opacity/corner controls. New
    **Atlas** (frosted) default applied once via the `looksV2` migration so existing installs
    see it.
  - **Generated views render inline** in the transcript, not only the Inspector; `/scene` and
    `/chart` commands added to the registry.
  - **Right-click any bubble → restyle** the whole bubble family (material/opacity) — the
    first element-level editing path.
- [x] **Surface-first rebuild** — the fix for the whole class of legibility bugs was to
  stop putting photographs behind text. Colour now resolves from a small, closed set of
  **surface + ink roles** instead of sampling the art:
  - `SurfaceLook` (`system | paper | mono | noir`) → `ColorTheme.look(_:isDark:)` is the single
    colour authority. `DesignTokens.look` carries it; a `looksV3`/`looksV4` migration defaults
    everyone to **Noir** (the house default; pitch black). Looks are the *only* theme control
    (System / Paper / Mono / Noir — Noir is pitch black with a warm amber accent).
  - **Paper is a real theme again**: warm cream canvas, raised cards, ink text, terracotta
    accent — its charm is warmth + texture, not see-through-over-photo.
  - **No photograph behind reading text.** Content renders on `colorTheme.background`
    (solid). There is no wallpaper: the procedural sand is the only background.
  - **Messages**: plain assistant prose in the reading column (Claude/Obsidian) + a subtle
    raised surface for the reader's own turns.
  - **Purged** the now-dead subsystem: `BubblePlate`/`Legibility`/`BoxState`/`BackdropSample`,
    the art colour grid + rect sampler, `headerRule`, `bubbleStyleMenu`, `BgCell`, and their
    tests/goldens. Net: fewer systems, one visual language.
  - References: Material 3 "on-" colour roles; Apple HIG *Materials* + semantic colours;
    Radix Colors (guaranteed-contrast steps); Obsidian CSS-variable theming + translucent
    window; ChatGPT/Claude centered column + sticky composer; Bear/Craft/Apple Notes paper.
- [x] **Shell + polish pass** —
  - **Native `.inspector`** replaces the hand-rolled `AppFrame` (which is deleted);
    the divider, resize and show/hide come from the system (SwiftUI `.inspector`, macOS 14+).
  - **Top safe area**: a window `TopInsetReader` → `Engine.topInset` pushes the masthead +
    grid below the hidden titlebar, so the discs/logo no longer clip (Apple HIG *Layout —
    safe areas*; AppKit `NSView.safeAreaInsets`).
  - **No halo/glow**: the wordmark is plain **white**; the disc-glyph shadows and the unused
    `shadowColor` helper are removed.
  - **Backgrounds**: the photo set (and its hide/unhide manifest) was later removed entirely
    — see *Living sand + de-wallpaper* below.
- [x] **Noir sand surface** — the default canvas is a **Metal** fragment shader
  (`DesignSystem/Sand/SandShaders.metal`): near-black with one big, soft, **domain-warped
  amber dune** (Perlin flow field), fine grain over everything, a centre scrim for the
  reading column, and an in-shader **dither** that removes gradient banding. It **rests**,
  then moves only when the UI is touched — pointer parallax · panel glow-shift · streaming
  breath · a one-shot send **gust** — and settles. Motion is a **sum of decaying impulses**
  (framerate-free, interruptible) with an amplitude ladder: pointer/scroll barely register,
  panels/send/mode are bigger — **calm by default, nudged only when big things move**. Cadence
  adapts (60 fps active → slow at rest); Reduce Motion freezes it. `SandStyle`
  (look) + `SandMotion` (couplings) are data-driven; `DesignTokens.sand` overrides the preset.
  Needs the Metal Toolchain (`xcodebuild -downloadComponent MetalToolchain`); without it the
  app uses a Canvas fallback. Refs: "Grainy Gradients" (grain), The Coding Train (flow field),
  Apple WWDC18 *Designing Fluid Interfaces* (behaviours / resting states).
  - **`design-review` skill** (`.opencode/skills/design-review/SKILL.md`): reviews the
    **worst-case** state across the look × appearance × size × content matrix, citing Apple
    HIG / Material 3 / Radix / APCA / Obsidian-Claude conventions.
- [x] **Semantic text colours** — `TextInk` (one palette per look) paints the reading text
  like an editor's syntax theme: **headings** = accent, **quotes** = sand, **links** = blue
  (+ underline), **numbers** = gold, **citations** = dim italic, body otherwise. The
  **wordmark** is the constant brand **sand** in every look. Redundant cues (weight, italic,
  underline) are kept so colour is never the only signal (Apple HIG *Color*).
  Ref: VS Code / opencode token themes.
- [x] **Inspector folded into the chrome** — the header disc is gone; the hamburger rail now
  has an **Inspector** icon (highlighted while open), and the pane is rendered **in-content**
  (`HStack` trailing pane) instead of the native `.inspector`, which was resizing the window.
- [x] **Motion pass** — grounded in Apple's motion guidance:
  - **Apple spring presets** (`smooth`/`snappy`/`bouncy`/`interactiveSpring`) plus `gentle`
    and `pop`; a reduce-motion-aware `.motion(_:value:)` modifier replaces ad-hoc
    `reduceMotion ? nil : …`.
  - **Symbol effects carry state** (Apple SF Symbols): the `sparkles` glyph *pulses* while an
    answer streams (`symbolEffect(.pulse, isActive:)`), the send/stop glyph swaps via
    `contentTransition(.symbolEffect(.replace))` and bounces on send, icon-rail toggles bounce
    on activation, and every message action + chip bounces on tap.
  - **Streaming jank removed** — dropped the per-token `scrollTo`; `defaultScrollAnchor(.bottom)`
    now pins to the bottom, so tokens don't thrash the scroll view.
  - Removed `AnyView` from the glass panel path.
  - References: Apple HIG *Motion*, *Designing Fluid Interfaces* (WWDC18), SwiftUI
    `symbolEffect` / `contentTransition` / `defaultScrollAnchor`, and Material/Fluent motion
    (easing + shared-axis) as the contrast case for "animate the glyph, not the container".
