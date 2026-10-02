import SwiftUI

/// The single source of truth for the app's design: type, motion, metrics, and
/// screen composition. Everything the UI draws from is here, so Settings/Debug
/// edit the same data the app renders — instead of numbers scattered in views.
///
/// Layout lives in `LayoutGridStore`; colour lives in `SurfaceLook` → `ColorTheme`.
struct DesignTokens: Codable, Equatable, Sendable {
    var typography = Typography()
    var motion = Motion()
    var metrics = Metrics()
    var composition = Composition()
    var chrome = Chrome()
    var inspector = Inspector()
    var space = Space()
    var material = Material()
    var elevation = Elevation()
    var bubble = Bubble()
    var sand = Sand()
    /// The surface-first look (System / Paper / Mono / Sand). Drives the whole
    /// colour system — see `SurfaceLook` / `ColorTheme.look`.
    var look = SurfaceLook.sand

    static let `default` = DesignTokens()

    /// The control language: circles, capsules, super-rounded cards, and the one
    /// focal per screen. Every piece of chrome draws its shape from here, so the
    /// vocabulary is data (editable in Design) rather than per-view literals.
    struct Chrome: Codable, Equatable, Sendable {
        var circle: Double = 38          // icon-button diameter
        var circleSmall: Double = 30
        var capsuleHeight: Double = 36
        var capsulePadH: Double = 16
        var radiusS: Double = 12         // chips / small cards
        var radiusM: Double = 18         // cards
        var radiusL: Double = 26         // panels
        var radiusXL: Double = 34        // hero plates
        var nestedInset: Double = 6      // concentric-corner rule
        var focal: Double = 28           // the one solid focal per screen
        var glassRim: Double = 0.30      // specular edge opacity
        var pressedScale: Double = 0.955
    }

    /// Grid-display settings (the always-on feather + the numeric inspector),
    /// so they live in the same data as everything else rather than as loose
    /// `@AppStorage` keys.
    struct Inspector: Codable, Equatable, Sendable {
        var showGrid: Bool = false
        var showLines: Bool = true
        var lineOpacity: Double = 0.18
        var lineBand: Double = 40
        var lineFeather: Double = 1
        var numbers: Bool = true
        var scope: String = "both"
        var headerHeight: Double = 68
    }

    /// The spatial rhythm — an 8-pt grid, so paddings/gaps stop being literals.
    struct Space: Codable, Equatable, Sendable {
        var xxs: Double = 4
        var xs: Double = 8
        var s: Double = 12
        var m: Double = 16
        var l: Double = 24
        var xl: Double = 32
        var xxl: Double = 48
        var xxxl: Double = 64

        init() {}
        init(from decoder: Decoder) throws {
            self.init()
            let c = try decoder.container(keyedBy: AnyKey.self)
            xxs = c.tolerant("xxs", xxs); xs = c.tolerant("xs", xs); s = c.tolerant("s", s)
            m = c.tolerant("m", m); l = c.tolerant("l", l); xl = c.tolerant("xl", xl)
            xxl = c.tolerant("xxl", xxl); xxxl = c.tolerant("xxxl", xxxl)
        }
    }

    /// The app's default surface material. `glass` is now *one* option, not the rule.
    struct Material: Codable, Equatable, Sendable {
        var role: MaterialRole = .tonal
        init() {}
        init(from decoder: Decoder) throws {
            self.init()
            let c = try decoder.container(keyedBy: AnyKey.self)
            role = c.tolerant("role", role)
        }
    }

    /// The elevation ramp: one shadow per level, so depth is a token rather than
    /// a per-view `.shadow(...)` literal.
    struct Elevation: Codable, Equatable, Sendable {
        struct Shadow: Codable, Equatable, Sendable {
            var radius: Double = 0
            var y: Double = 0
            var opacity: Double = 0
            init(radius: Double = 0, y: Double = 0, opacity: Double = 0) {
                self.radius = radius; self.y = y; self.opacity = opacity
            }
        }
        var flat = Shadow()
        var low = Shadow(radius: 8, y: 2, opacity: 0.18)
        var mid = Shadow(radius: 18, y: 6, opacity: 0.26)
        var high = Shadow(radius: 30, y: 12, opacity: 0.34)

        init() {}
        init(from decoder: Decoder) throws {
            self.init()
            let c = try decoder.container(keyedBy: AnyKey.self)
            flat = c.tolerant("flat", flat); low = c.tolerant("low", low)
            mid = c.tolerant("mid", mid); high = c.tolerant("high", high)
        }
    }

    /// The dust system (see `SandCore/TRUTH.md`): **Langevin dust** drifting in
    /// an endless dark void, lit by **soft light beams**, flowing around moving
    /// solids (the cursor + UI). `enabled` gates it; every knob overrides the
    /// defaults (all data-driven, tolerant-decoded).
    struct Sand: Codable, Equatable, Sendable {
        var enabled: Bool = true
        // motion — Langevin force particles
        var swirl: Double = 0.2844362745098039           // weak swirl force
        var swirlScale: Double = 1.2040543300653592       // swirl frequency (lower is bigger)
        var drift: Double = 0.0            // constant lateral air current
        var drag: Double = 9.498008578431373             // velocity damping (higher is stiller)
        var brownian: Double = 0.008       // random shimmer
        var parallaxDepth: Double = 0.6    // closer motes travel faster (multiplane)
        // obstacles — moving solids (cursor disk + UI rects)
        var obstacleRadius: Double = 0.008
        var obstaclePad: Double = 0.015
        // dust
        var dustCount: Double = 12000.0
        var dustSize: Double = 2.2
        var dustFog: Double = 1.6          // depth fade
        var dustBase: Double = 0.08        // visibility outside the beams
        var dustBrightness: Double = 1.0
        // light — a cone of light from a point above the top edge (god-ray)
        var shaftStrength: Double = 1.0865093954248366
        var shaftX: Double = 0.5
        var shaftY: Double = -0.07350847630718949
        var shaftSpread: Double = 90.0
        var shaftRays: Double = 7.0
        var shaftFalloff: Double = 2.6743872549019607
        var shaftSourceGlow: Double = 0.9056883169934641
        var shaftDrift: Double = 0.03
        var shaftBg: Double = 0.2
        // beam life — flutter · gobo · gust
        var beamFlutter: Double = 0.6
        var beamFlutterSpeed: Double = 1.2
        var goboStrength: Double = 0.0
        var goboScale: Double = 3.0
        var goboDrift: Double = 0.06
        var gustAmount: Double = 0.5
        var gustRate: Double = 0.07
        var lightSway: Double = 0.4
        var lightLean: Double = 0.0
        // volumetric light (ray-march + temporal AA)
        var volSteps: Double = 24.0
        var volDensity: Double = 1.4
        var volExtinction: Double = 0.5
        var volScale: Double = 2.2
        var volDrift: Double = 0.05
        var volJitter: Double = 1.0
        var taaAlpha: Double = 0.18
        // depth layers (per-layer debug enables)
        var layerClose: Bool = true
        var layerNear: Bool = true
        var layerMid: Bool = true
        var layerFar: Bool = true
        var layerHaze: Bool = true
        // render
        var bloomIntensity: Double = 0.4209354575163399
        var bloomThreshold: Double = 0.6
        var bloomIterations: Double = 4.0
        var dither: Double = 0.012

        var exposure: Double = 0.17888327205882354
        var tonemap: Double = 1.0
        // motion cadence
        var idleWindow: Double = 2.5
        var impulseScale: Double = 1.15
        init() {}
        init(from decoder: Decoder) throws {
            self.init()
            let c = try decoder.container(keyedBy: AnyKey.self)
            enabled = c.tolerant("enabled", enabled)
            swirl = c.tolerant("swirl", swirl)
            swirlScale = c.tolerant("swirlScale", swirlScale)
            drift = c.tolerant("drift", drift)
            drag = c.tolerant("drag", drag)
            brownian = c.tolerant("brownian", brownian)
            parallaxDepth = c.tolerant("parallaxDepth", parallaxDepth)
            obstacleRadius = c.tolerant("obstacleRadius", obstacleRadius)
            obstaclePad = c.tolerant("obstaclePad", obstaclePad)
            dustCount = c.tolerant("dustCount", dustCount)
            dustSize = c.tolerant("dustSize", dustSize)
            dustFog = c.tolerant("dustFog", dustFog)
            dustBase = c.tolerant("dustBase", dustBase)
            dustBrightness = c.tolerant("dustBrightness", dustBrightness)
            shaftStrength = c.tolerant("shaftStrength", shaftStrength)
            shaftX = c.tolerant("shaftX", shaftX)
            shaftY = c.tolerant("shaftY", shaftY)
            shaftSpread = c.tolerant("shaftSpread", shaftSpread)
            shaftRays = c.tolerant("shaftRays", shaftRays)
            shaftFalloff = c.tolerant("shaftFalloff", shaftFalloff)
            shaftSourceGlow = c.tolerant("shaftSourceGlow", shaftSourceGlow)
            shaftDrift = c.tolerant("shaftDrift", shaftDrift)
            shaftBg = c.tolerant("shaftBg", shaftBg)
            beamFlutter = c.tolerant("beamFlutter", beamFlutter)
            beamFlutterSpeed = c.tolerant("beamFlutterSpeed", beamFlutterSpeed)
            goboStrength = c.tolerant("goboStrength", goboStrength)
            goboScale = c.tolerant("goboScale", goboScale)
            goboDrift = c.tolerant("goboDrift", goboDrift)
            gustAmount = c.tolerant("gustAmount", gustAmount)
            gustRate = c.tolerant("gustRate", gustRate)
            lightSway = c.tolerant("lightSway", lightSway)
            lightLean = c.tolerant("lightLean", lightLean)
            volSteps = c.tolerant("volSteps", volSteps)
            volDensity = c.tolerant("volDensity", volDensity)
            volExtinction = c.tolerant("volExtinction", volExtinction)
            volScale = c.tolerant("volScale", volScale)
            volDrift = c.tolerant("volDrift", volDrift)
            volJitter = c.tolerant("volJitter", volJitter)
            taaAlpha = c.tolerant("taaAlpha", taaAlpha)
            layerClose = c.tolerant("layerClose", layerClose)
            layerNear = c.tolerant("layerNear", layerNear)
            layerMid = c.tolerant("layerMid", layerMid)
            layerFar = c.tolerant("layerFar", layerFar)
            layerHaze = c.tolerant("layerHaze", layerHaze)
            bloomIntensity = c.tolerant("bloomIntensity", bloomIntensity)
            bloomThreshold = c.tolerant("bloomThreshold", bloomThreshold)
            bloomIterations = c.tolerant("bloomIterations", bloomIterations)
            dither = c.tolerant("dither", dither)
            exposure = c.tolerant("exposure", exposure)
            tonemap = c.tolerant("tonemap", tonemap)
            idleWindow = c.tolerant("idleWindow", idleWindow)
            impulseScale = c.tolerant("impulseScale", impulseScale)
        }
    }

    /// The chat-bubble plate: its own material role and per-role opacity, with a
    /// legibility floor. Distinct user vs assistant, per the chat convention.
    struct Bubble: Codable, Equatable, Sendable {
        var role: MaterialRole = .tonal
        var userOpacity: Double = 0.90
        var assistantOpacity: Double = 0.72
        var minOpacity: Double = 0.45

        init() {}
        init(from decoder: Decoder) throws {
            self.init()
            let c = try decoder.container(keyedBy: AnyKey.self)
            role = c.tolerant("role", role)
            userOpacity = c.tolerant("userOpacity", userOpacity)
            assistantOpacity = c.tolerant("assistantOpacity", assistantOpacity)
            minOpacity = c.tolerant("minOpacity", minOpacity)
        }
    }

    struct Typography: Codable, Equatable, Sendable {
        var fontSize: Double = 14.5
        var measureChars: Int = 40
        var maxChars: Int = 66
        var maxColumns: Int = 1
        var linesPerColumn: Int = 30
        var lineSpacing: Double = 5.5
        var paragraphSpacing: Double = 11
        // Semantic size scale (used via `TypeScale`).
        var display: Double = 30
        var title: Double = 16
        var micro: Double = 9
        var meta: Double = 9.5
        var caption: Double = 10
        var label: Double = 11
        var body: Double = 13.5
        var bodyMono: Double = 14.5
        var emphasis: Double = 14
    }

    struct Motion: Codable, Equatable, Sendable {
        var smoothDuration: Double = 0.3
        var snappyDuration: Double = 0.3
        var snappyBounce: Double = 0.0
        var bubbleBounce: Double = 0.12
        var pageSlide: Double = 16
    }

    struct Metrics: Codable, Equatable, Sendable {
        var panelPadMin: Double = 10
        var panelRadiusPad: Double = 6
        var sidebarMin: Double = 250
        var sidebarIdeal: Double = 320
        var sidebarMax: Double = 440
    }

    struct Composition: Codable, Equatable, Sendable {
        var headerHeight: Double = 68
        var composerHeight: Double = 64
        var bubbleCorner: Double = 20
        var bubblePaddingH: Double = 18
        var bubblePaddingTop: Double = 13
        var bubblePaddingBottom: Double = 15
        var roleHeaderTop: Double = 40
    }
}

extension DesignTokens {
    /// Transitional single source read by the static design helpers (`Anim`,
    /// `PanelGrid`, `TextStyle`). Kept in sync by `DesignStore`.
    nonisolated(unsafe) static var current = DesignTokens()
}

// MARK: - Tolerant decoding

/// A string-addressed coding key so every token group can be decoded field by
/// field. A saved blob that predates a field (or a field added later) then keeps
/// its default instead of failing the whole decode and wiping the user's tokens.
private struct AnyKey: CodingKey {
    var stringValue: String
    var intValue: Int?
    init(_ s: String) {
        stringValue = s
        intValue = nil
    }
    init?(stringValue: String) {
        self.stringValue = stringValue
        intValue = nil
    }
    init?(intValue: Int) {
        self.intValue = intValue
        stringValue = String(intValue)
    }
}

extension KeyedDecodingContainer where Key == AnyKey {
    /// The stored value, or the default when the key is absent or malformed.
    func tolerant<T: Decodable>(_ key: String, _ fallback: T) -> T {
        (try? decode(T.self, forKey: AnyKey(key))) ?? fallback
    }
}

extension DesignTokens {
    init(from decoder: Decoder) throws {
        self = DesignTokens()
        let c = try decoder.container(keyedBy: AnyKey.self)
        typography = c.tolerant("typography", typography)
        motion = c.tolerant("motion", motion)
        metrics = c.tolerant("metrics", metrics)
        composition = c.tolerant("composition", composition)
        chrome = c.tolerant("chrome", chrome)
        inspector = c.tolerant("inspector", inspector)
        space = c.tolerant("space", space)
        material = c.tolerant("material", material)
        elevation = c.tolerant("elevation", elevation)
        bubble = c.tolerant("bubble", bubble)
        sand = c.tolerant("sand", sand)
        look = c.tolerant("look", look)
    }
}

extension DesignTokens.Chrome {
    init(from decoder: Decoder) throws {
        self = DesignTokens.Chrome()
        let c = try decoder.container(keyedBy: AnyKey.self)
        circle = c.tolerant("circle", circle)
        circleSmall = c.tolerant("circleSmall", circleSmall)
        capsuleHeight = c.tolerant("capsuleHeight", capsuleHeight)
        capsulePadH = c.tolerant("capsulePadH", capsulePadH)
        radiusS = c.tolerant("radiusS", radiusS)
        radiusM = c.tolerant("radiusM", radiusM)
        radiusL = c.tolerant("radiusL", radiusL)
        radiusXL = c.tolerant("radiusXL", radiusXL)
        nestedInset = c.tolerant("nestedInset", nestedInset)
        focal = c.tolerant("focal", focal)
        glassRim = c.tolerant("glassRim", glassRim)
        pressedScale = c.tolerant("pressedScale", pressedScale)
    }
}

extension DesignTokens.Typography {
    init(from decoder: Decoder) throws {
        self = DesignTokens.Typography()
        let c = try decoder.container(keyedBy: AnyKey.self)
        fontSize = c.tolerant("fontSize", fontSize)
        measureChars = c.tolerant("measureChars", measureChars)
        maxChars = c.tolerant("maxChars", maxChars)
        maxColumns = c.tolerant("maxColumns", maxColumns)
        linesPerColumn = c.tolerant("linesPerColumn", linesPerColumn)
        lineSpacing = c.tolerant("lineSpacing", lineSpacing)
        paragraphSpacing = c.tolerant("paragraphSpacing", paragraphSpacing)
        display = c.tolerant("display", display)
        title = c.tolerant("title", title)
        micro = c.tolerant("micro", micro)
        meta = c.tolerant("meta", meta)
        caption = c.tolerant("caption", caption)
        label = c.tolerant("label", label)
        body = c.tolerant("body", body)
        bodyMono = c.tolerant("bodyMono", bodyMono)
        emphasis = c.tolerant("emphasis", emphasis)
    }
}

extension DesignTokens.Motion {
    init(from decoder: Decoder) throws {
        self = DesignTokens.Motion()
        let c = try decoder.container(keyedBy: AnyKey.self)
        smoothDuration = c.tolerant("smoothDuration", smoothDuration)
        snappyDuration = c.tolerant("snappyDuration", snappyDuration)
        snappyBounce = c.tolerant("snappyBounce", snappyBounce)
        bubbleBounce = c.tolerant("bubbleBounce", bubbleBounce)
        pageSlide = c.tolerant("pageSlide", pageSlide)
    }
}

extension DesignTokens.Metrics {
    init(from decoder: Decoder) throws {
        self = DesignTokens.Metrics()
        let c = try decoder.container(keyedBy: AnyKey.self)
        panelPadMin = c.tolerant("panelPadMin", panelPadMin)
        panelRadiusPad = c.tolerant("panelRadiusPad", panelRadiusPad)
        sidebarMin = c.tolerant("sidebarMin", sidebarMin)
        sidebarIdeal = c.tolerant("sidebarIdeal", sidebarIdeal)
        sidebarMax = c.tolerant("sidebarMax", sidebarMax)
    }
}

extension DesignTokens.Composition {
    init(from decoder: Decoder) throws {
        self = DesignTokens.Composition()
        let c = try decoder.container(keyedBy: AnyKey.self)
        headerHeight = c.tolerant("headerHeight", headerHeight)
        composerHeight = c.tolerant("composerHeight", composerHeight)
        bubbleCorner = c.tolerant("bubbleCorner", bubbleCorner)
        bubblePaddingH = c.tolerant("bubblePaddingH", bubblePaddingH)
        bubblePaddingTop = c.tolerant("bubblePaddingTop", bubblePaddingTop)
        bubblePaddingBottom = c.tolerant("bubblePaddingBottom", bubblePaddingBottom)
        roleHeaderTop = c.tolerant("roleHeaderTop", roleHeaderTop)
    }
}

extension DesignTokens.Inspector {
    init(from decoder: Decoder) throws {
        self = DesignTokens.Inspector()
        let c = try decoder.container(keyedBy: AnyKey.self)
        showGrid = c.tolerant("showGrid", showGrid)
        showLines = c.tolerant("showLines", showLines)
        lineOpacity = c.tolerant("lineOpacity", lineOpacity)
        lineBand = c.tolerant("lineBand", lineBand)
        lineFeather = c.tolerant("lineFeather", lineFeather)
        numbers = c.tolerant("numbers", numbers)
        scope = c.tolerant("scope", scope)
        headerHeight = c.tolerant("headerHeight", headerHeight)
    }
}

private struct DesignTokensKey: EnvironmentKey {
    static let defaultValue = DesignTokens.default
}

extension EnvironmentValues {
    var design: DesignTokens {
        get { self[DesignTokensKey.self] }
        set { self[DesignTokensKey.self] = newValue }
    }
}
