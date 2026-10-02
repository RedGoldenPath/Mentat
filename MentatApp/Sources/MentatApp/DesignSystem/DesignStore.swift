import Foundation
import Observation

/// Owns the live `DesignTokens`, persisted to UserDefaults and mirrored into
/// `DesignTokens.current` so the static design helpers see edits immediately.
@Observable final class DesignStore {
    private static let key = "designTokens"

    var tokens: DesignTokens {
        didSet {
            DesignTokens.current = tokens
            persist()
        }
    }

    init(defaults: UserDefaults = .standard) {
        var t: DesignTokens
        if let data = defaults.data(forKey: Self.key),
            let decoded = try? JSONDecoder().decode(DesignTokens.self, from: data)
        {
            t = decoded
        } else {
            t = DesignStore.seeded(from: defaults)
        }
        // One-time: two columns read better than three for dense prose (the saved
        // token may still hold the old default of 3). Users can change it later in
        // the Design panel; the flag stops re-applying.
        if !defaults.bool(forKey: "columnsMigrated2") {
            if t.typography.maxColumns == 3 { t.typography.maxColumns = 2 }
            defaults.set(true, forKey: "columnsMigrated2")
        }
        // Chat is a single continuous column now; force it for anyone carrying an
        // older saved value (2 or 3) so the answer body never splits into columns.
        if !defaults.bool(forKey: "columnsMigrated1") {
            if t.typography.maxColumns != 1 { t.typography.maxColumns = 1 }
            defaults.set(true, forKey: "columnsMigrated1")
        }
        // Legibility pass: the reader asked for larger, airier body text. Only
        // ever raises the values, so a deliberate larger setting is preserved.
        if !defaults.bool(forKey: "legibilityV1") {
            t.typography.fontSize = max(t.typography.fontSize, 14.5)
            t.typography.bodyMono = max(t.typography.bodyMono, 14.5)
            t.typography.body = max(t.typography.body, 13.5)
            t.typography.lineSpacing = max(t.typography.lineSpacing, 5.5)
            t.typography.paragraphSpacing = max(t.typography.paragraphSpacing, 11)
            t.typography.maxChars = max(t.typography.maxChars, 66)
            defaults.set(true, forKey: "legibilityV1")
        }
        // Looks v3: the colour system is surface-first now. Everyone defaults to
        // Sand (pitch black); users can pick another look in the design studio.
        if !defaults.bool(forKey: "looksV3") {
            t.look = .sand
            defaults.set(true, forKey: "looksV3")
        }
        // Looks v4: Sand is the house default.
        if !defaults.bool(forKey: "looksV4") {
            t.look = .sand
            defaults.set(true, forKey: "looksV4")
        }
        // Sand v4: one **wind field** (curl current + pointer vortex/push +
        // vorticity) advecting a **sand body** and airborne **grains**. Re-seed
        // the sand group so older values don't linger; later edits are kept.
        if !defaults.bool(forKey: "sandV11") {
            t.sand = DesignTokens.Sand()
            defaults.set(true, forKey: "sandV11")
        }
        // Sand v12: rebuilt as a **dust cloud in the wind** — two advected dust
        // layers, curl turbulence with drag, and the cursor as an obstacle the
        // dust flows around. Re-seed the sand group so old values don't linger.
        if !defaults.bool(forKey: "sandV12") {
            t.sand = DesignTokens.Sand()
            defaults.set(true, forKey: "sandV12")
        }
        // Sand v13: dust is a true **passive scalar** now — threshold lift from an
        // erodible supply field, vorticity confinement (no velocity self-advect),
        // obstacles as no-slip boundaries, saltating near-camera glints lit by a
        // drifting key light, and **no centre dim**. Re-seed the sand group.
        if !defaults.bool(forKey: "sandV13") {
            t.sand = DesignTokens.Sand()
            defaults.set(true, forKey: "sandV13")
        }
        // Sand v14: reworked to match the reference — ONE roaming warm bloom on a
        // black field (the bloom is the soft gradient; advected dust adds swirl),
        // non-pulsing lift (no hysteresis feedback), and advected film grain.
        // Also: glints sized in points so they're visible. Re-seed the sand group.
        if !defaults.bool(forKey: "sandV14") {
            t.sand = DesignTokens.Sand()
            defaults.set(true, forKey: "sandV14")
        }
        // Sand v15: rebuilt around **Langevin dust** floating in a dark room —
        // mostly-still motes with a weak swirl + Brownian shimmer, lit by **soft
        // light beams** (a top-left gobo), flowing around moving solids (cursor +
        // UI). The old wind/turbulence/bloom/grain-firehose vocabulary is gone.
        // Re-seed the sand group so older values don't linger.
        if !defaults.bool(forKey: "sandV15") {
            t.sand = DesignTokens.Sand()
            defaults.set(true, forKey: "sandV15")
        }
        // Sand v16: the light is now a **cone from a point above the top edge**
        // (with a soft source glow) rather than diagonal parallel bands, and the
        // film grain is gone. Re-seed so everyone lands on the new defaults.
        if !defaults.bool(forKey: "sandV16") {
            t.sand = DesignTokens.Sand()
            defaults.set(true, forKey: "sandV16")
        }
        // Sand v17: the light is alive — per-beam flutter, a moving gobo
        // (leaves/window), a calm↔flutter gust envelope, Beer–Lambert extinction,
        // spice-orange sparkles and one HDR tonemap; the dust is four parallax
        // depth layers (closer = faster) with per-layer debug toggles, light that
        // actually illuminates the spice, and global motion as forces (no
        // full-span walls that pooled dust into a line). Re-seed defaults.
        if !defaults.bool(forKey: "sandV17") {
            t.sand = DesignTokens.Sand()
            defaults.set(true, forKey: "sandV17")
        }
        // Sand v18: the beams are a real **volumetric light engine** — a screen-
        // space ray-march through the medium (an integral, so the shafts read as
        // light in air, not a painted cone), supersampled + temporally
        // accumulated (light-only) to remove the aliasing. Re-seed defaults.
        if !defaults.bool(forKey: "sandV18") {
            t.sand = DesignTokens.Sand()
            defaults.set(true, forKey: "sandV18")
        }
        // Sand v19: the light moves for real — the shafts are the shadow of
        // drifting leaves (two layers, near faster than far), the source sways,
        // and the light leans toward the pointer. The cursor now barely disturbs
        // the dust (a smaller clearing). Re-seed defaults.
        if !defaults.bool(forKey: "sandV19") {
            t.sand = DesignTokens.Sand()
            defaults.set(true, forKey: "sandV19")
        }
        // Sand v20: one beam, not a fan — a single shaft from the source (rays 1,
        // no striations, no leaf breakup), and NO cursor/mouse interaction (the
        // light is not tied to the pointer). Re-seed defaults.
        if !defaults.bool(forKey: "sandV20") {
            t.sand = DesignTokens.Sand()
            defaults.set(true, forKey: "sandV20")
        }
        // Sand v21: the light is a **directional window god-ray** — a lit band
        // angled from the upper-right with several soft parallel shafts and a
        // warm pool where it lands on the floor (matching the reference), instead
        // of a fan from a near point. Re-seed defaults.
        if !defaults.bool(forKey: "sandV21") {
            t.sand = DesignTokens.Sand()
            defaults.set(true, forKey: "sandV21")
        }
        // Sand v22: a real **beam system** — one source, a fan of DISTINCT beams
        // (a mix of big and small/sharper ones) on black, fluttering. The old
        // window-band + noise-mud is gone. Re-seed defaults.
        if !defaults.bool(forKey: "sandV22") {
            t.sand = DesignTokens.Sand()
            defaults.set(true, forKey: "sandV22")
        }
        // Sand v23: **lean** — the light is one cheap pass (no ray-march, no 2×
        // supersample, no temporal buffer), 60 fps cap, dust 12k. Re-seed defaults.
        if !defaults.bool(forKey: "sandV23") {
            t.sand = DesignTokens.Sand()
            defaults.set(true, forKey: "sandV23")
        }
        // Sand v24: beams are now **crepuscular rays** — a moving noise field
        // (big + small octaves, each advected) so beams are born and dissolve at
        // irregular, cloud-like intervals, not a rigid fan. "Beam churn" /
        // "Cloud scale" replace "Number of beams". 120 fps restored (adaptive).
        if !defaults.bool(forKey: "sandV24") {
            t.sand = DesignTokens.Sand()
            defaults.set(true, forKey: "sandV24")
        }
        // Sand v25: the special "hero" layer is gone — replaced by **five equal
        // depth layers** (Close-up · Near · Mid · Far · Haze), each toggleable;
        // the nearest is the close-up (bigger/blurrier/faster). Re-seed defaults.
        if !defaults.bool(forKey: "sandV25") {
            t.sand = DesignTokens.Sand()
            defaults.set(true, forKey: "sandV25")
        }
        // Sand v26: adopt the tuned SandLab look as the new baseline (snapshot
        // `SandLab/sandlab-baseline.json`). Re-seed so the app matches it.
        if !defaults.bool(forKey: "sandV26") {
            t.sand = DesignTokens.Sand()
            defaults.set(true, forKey: "sandV26")
        }
        tokens = t
        DesignTokens.current = tokens
        persist()
    }

    /// First run: carry over the legacy loose `@AppStorage` settings so nothing
    /// is lost when they move into tokens.
    private static func seeded(from d: UserDefaults) -> DesignTokens {
        var t = DesignTokens.default
        if d.object(forKey: "showGrid") != nil { t.inspector.showGrid = d.bool(forKey: "showGrid") }
        if d.object(forKey: "gridLines") != nil {
            t.inspector.showLines = d.bool(forKey: "gridLines")
        }
        if d.object(forKey: "gridLineOpacity") != nil {
            t.inspector.lineOpacity = d.double(forKey: "gridLineOpacity")
        }
        if d.object(forKey: "gridLineBand") != nil {
            t.inspector.lineBand = d.double(forKey: "gridLineBand")
        }
        if d.object(forKey: "gridLineFeather") != nil {
            t.inspector.lineFeather = d.double(forKey: "gridLineFeather")
        }
        if d.object(forKey: "gridNumbers") != nil {
            t.inspector.numbers = d.bool(forKey: "gridNumbers")
        }
        if d.object(forKey: "gridScope") != nil {
            t.inspector.scope = d.string(forKey: "gridScope") ?? "both"
        }
        if d.object(forKey: "headerHeight") != nil {
            t.inspector.headerHeight = d.double(forKey: "headerHeight")
        }
        return t
    }

    func reset() { tokens = .default }

    // MARK: - Token graph (the unified vocabulary)

    /// The live token graph, derived from the native cache. Every semantic and
    /// component value is reachable here by path.
    var graph: TokenGraph { TokenCatalog.graph(from: tokens) }

    /// Export the whole graph as a W3C `.tokens.json` document (interop with
    /// Style Dictionary / Figma / Tokens Studio).
    func exportW3CTokens() -> Data? { try? graph.encode() }

    /// Import a W3C `.tokens.json`; only the practical groups are applied
    /// (space, radius, duration, shadow, typography, material). Colour roles are
    /// artwork-derived at runtime and stay with the ColorSystem.
    func importW3CTokens(_ data: Data) throws {
        let graph = try TokenGraph.decode(data)
        var next = tokens
        TokenCatalog.apply(graph, into: &next)
        tokens = next
    }

    private func persist() {
        if let data = try? JSONEncoder().encode(tokens) {
            UserDefaults.standard.set(data, forKey: Self.key)
        }
    }
}
