import Foundation

/// Bridges the native `DesignTokens` (the fast cache) to a W3C-shaped
/// `TokenGraph`, and back. One vocabulary, two representations.
enum TokenCatalog {

    // MARK: - Native → graph

    /// Build the canonical graph: primitive palette, then space / radius / size /
    /// duration / shadow / typography / material, then semantic `color.*` aliases.
    static func graph(from d: DesignTokens) -> TokenGraph {
        var tokens: [Token] = []

        func dim(_ path: String, _ v: Double) {
            tokens.append(Token(path: path, type: .dimension, value: .dimension(v)))
        }
        func dur(_ path: String, _ v: Double) {
            tokens.append(Token(path: path, type: .duration, value: .duration(v)))
        }

        // Primitive palette (desert night) — the defaults the look resolves from.
        let palette: [(String, String)] = [
            ("background", "#16110C"), ("surface", "#271B12"), ("surfaceTint", "#291C12"),
            ("ink", "#E7D3AB"), ("inkDim", "#C8A06A"), ("accent", "#EA9D5A"),
            ("secondary", "#C4703C"), ("tertiary", "#E6C079"), ("border", "#5A4028"),
            ("good", "#90C187"), ("bad", "#D47160"), ("onAccent", "#000000"),
        ]
        for (k, hex) in palette {
            tokens.append(Token(path: "palette.night.\(k)", type: .color, value: .color(hex)))
        }

        // Semantic colour roles alias the primitives.
        for (k, _) in palette {
            tokens.append(Token(path: "color.\(k)", type: .color, alias: "{palette.night.\(k)}"))
        }

        // Space (8-pt grid).
        let space: [(String, Double)] = [
            ("xxs", d.space.xxs), ("xs", d.space.xs), ("s", d.space.s), ("m", d.space.m),
            ("l", d.space.l), ("xl", d.space.xl), ("xxl", d.space.xxl), ("xxxl", d.space.xxxl),
        ]
        for (k, v) in space { dim("space.\(k)", v) }

        // Radius + control sizes (from Chrome).
        dim("radius.s", d.chrome.radiusS)
        dim("radius.m", d.chrome.radiusM)
        dim("radius.l", d.chrome.radiusL)
        dim("radius.xl", d.chrome.radiusXL)
        dim("radius.nestedInset", d.chrome.nestedInset)
        dim("size.circle", d.chrome.circle)
        dim("size.circleSmall", d.chrome.circleSmall)
        dim("size.capsuleHeight", d.chrome.capsuleHeight)
        dim("size.capsulePadH", d.chrome.capsulePadH)
        dim("size.focal", d.chrome.focal)

        // Duration (from Motion).
        dur("duration.smooth", d.motion.smoothDuration)
        dur("duration.snappy", d.motion.snappyDuration)
        dur("duration.bubble", d.motion.bubbleBounce)
        dur("duration.pageSlide", d.motion.pageSlide)

        // Shadow (composite, from Elevation).
        func shadow(_ path: String, _ s: DesignTokens.Elevation.Shadow) {
            tokens.append(Token(path: path, type: .shadow,
                                value: .shadow(ShadowValue(color: "#000000", offsetX: 0,
                                                           offsetY: s.y, blur: s.radius, spread: 0))))
        }
        shadow("shadow.flat", d.elevation.flat)
        shadow("shadow.low", d.elevation.low)
        shadow("shadow.mid", d.elevation.mid)
        shadow("shadow.high", d.elevation.high)

        // Typography (composite per role).
        let type: [(String, Double)] = [
            ("display", d.typography.display), ("title", d.typography.title),
            ("body", d.typography.body), ("bodyMono", d.typography.bodyMono),
            ("label", d.typography.label), ("caption", d.typography.caption),
            ("micro", d.typography.micro), ("meta", d.typography.meta),
            ("emphasis", d.typography.emphasis), ("prose", d.typography.fontSize),
        ]
        for (k, v) in type {
            tokens.append(Token(path: "typography.\(k)", type: .typography,
                                value: .typography(TypographyValue(
                                    fontFamily: k.contains("Mono") ? "monospace" : nil,
                                    fontSize: v, fontWeight: nil,
                                    lineHeight: d.typography.lineSpacing, letterSpacing: nil))))
        }

        // Material role.
        tokens.append(Token(path: "material.role", type: .fontFamily,
                            value: .fontFamily(d.material.role.rawValue)))

        // Sand system (Langevin dust + soft beams + solid obstacles). Numbers so
        // they round-trip cleanly.
        let sand: [(String, Double)] = [
            ("swirl", d.sand.swirl),
            ("swirlScale", d.sand.swirlScale),
            ("drift", d.sand.drift),
            ("drag", d.sand.drag),
            ("brownian", d.sand.brownian),
            ("parallaxDepth", d.sand.parallaxDepth),
            ("obstacleRadius", d.sand.obstacleRadius),
            ("obstaclePad", d.sand.obstaclePad),
            ("dustCount", d.sand.dustCount),
            ("dustSize", d.sand.dustSize),
            ("dustFog", d.sand.dustFog),
            ("dustBase", d.sand.dustBase),
            ("dustBrightness", d.sand.dustBrightness),
            ("shaftStrength", d.sand.shaftStrength),
            ("shaftX", d.sand.shaftX),
            ("shaftY", d.sand.shaftY),
            ("shaftSpread", d.sand.shaftSpread),
            ("shaftRays", d.sand.shaftRays),
            ("shaftFalloff", d.sand.shaftFalloff),
            ("shaftSourceGlow", d.sand.shaftSourceGlow),
            ("shaftDrift", d.sand.shaftDrift),
            ("shaftBg", d.sand.shaftBg),
            ("beamFlutter", d.sand.beamFlutter),
            ("beamFlutterSpeed", d.sand.beamFlutterSpeed),
            ("goboStrength", d.sand.goboStrength),
            ("goboScale", d.sand.goboScale),
            ("goboDrift", d.sand.goboDrift),
            ("gustAmount", d.sand.gustAmount),
            ("gustRate", d.sand.gustRate),
            ("lightSway", d.sand.lightSway),
            ("lightLean", d.sand.lightLean),
            ("volSteps", d.sand.volSteps),
            ("volDensity", d.sand.volDensity),
            ("volExtinction", d.sand.volExtinction),
            ("volScale", d.sand.volScale),
            ("volDrift", d.sand.volDrift),
            ("volJitter", d.sand.volJitter),
            ("taaAlpha", d.sand.taaAlpha),
            ("layerClose", d.sand.layerClose ? 1 : 0),
            ("layerNear", d.sand.layerNear ? 1 : 0),
            ("layerMid", d.sand.layerMid ? 1 : 0),
            ("layerFar", d.sand.layerFar ? 1 : 0),
            ("layerHaze", d.sand.layerHaze ? 1 : 0),
            ("bloomIntensity", d.sand.bloomIntensity),
            ("bloomThreshold", d.sand.bloomThreshold),
            ("bloomIterations", d.sand.bloomIterations),
            ("dither", d.sand.dither),
            ("exposure", d.sand.exposure),
            ("tonemap", d.sand.tonemap),
            ("idleWindow", d.sand.idleWindow),
            ("impulseScale", d.sand.impulseScale),
        ]
        for (k, v) in sand {
            tokens.append(Token(path: "sand.\(k)", type: .number, value: .number(v)))
        }

        return TokenGraph(tokens: tokens)
    }

    // MARK: - graph → native

    /// Apply the practical groups (space, radius, duration, shadow, typography,
    /// material, sand) back onto `DesignTokens`. Colour roles are resolved by the
    /// look at runtime (`ColorTheme.look`), so they are left to the look.
    static func apply(_ graph: TokenGraph, into d: inout DesignTokens) {
        func dim(_ p: String, _ fallback: Double) -> Double {
            (try? graph.point(p)).map(Double.init) ?? fallback
        }
        func dur(_ p: String, _ fallback: Double) -> Double {
            (try? graph.seconds(p)) ?? fallback
        }
        func size(_ p: String, _ fallback: Double) -> Double {
            (try? graph.point(p)).map(Double.init) ?? fallback
        }

        d.space.xxs = dim("space.xxs", d.space.xxs); d.space.xs = dim("space.xs", d.space.xs)
        d.space.s = dim("space.s", d.space.s); d.space.m = dim("space.m", d.space.m)
        d.space.l = dim("space.l", d.space.l); d.space.xl = dim("space.xl", d.space.xl)
        d.space.xxl = dim("space.xxl", d.space.xxl); d.space.xxxl = dim("space.xxxl", d.space.xxxl)

        d.chrome.radiusS = dim("radius.s", d.chrome.radiusS)
        d.chrome.radiusM = dim("radius.m", d.chrome.radiusM)
        d.chrome.radiusL = dim("radius.l", d.chrome.radiusL)
        d.chrome.radiusXL = dim("radius.xl", d.chrome.radiusXL)
        d.chrome.nestedInset = dim("radius.nestedInset", d.chrome.nestedInset)
        d.chrome.circle = size("size.circle", d.chrome.circle)
        d.chrome.circleSmall = size("size.circleSmall", d.chrome.circleSmall)
        d.chrome.capsuleHeight = size("size.capsuleHeight", d.chrome.capsuleHeight)
        d.chrome.capsulePadH = size("size.capsulePadH", d.chrome.capsulePadH)
        d.chrome.focal = size("size.focal", d.chrome.focal)

        d.motion.smoothDuration = dur("duration.smooth", d.motion.smoothDuration)
        d.motion.snappyDuration = dur("duration.snappy", d.motion.snappyDuration)
        d.motion.bubbleBounce = dur("duration.bubble", d.motion.bubbleBounce)
        d.motion.pageSlide = dur("duration.pageSlide", d.motion.pageSlide)

        if let s = try? graph.shadow("shadow.low") {
            d.elevation.low = .init(radius: s.blur, y: s.offsetY, opacity: d.elevation.low.opacity)
        }
        if let s = try? graph.shadow("shadow.mid") {
            d.elevation.mid = .init(radius: s.blur, y: s.offsetY, opacity: d.elevation.mid.opacity)
        }
        if let s = try? graph.shadow("shadow.high") {
            d.elevation.high = .init(radius: s.blur, y: s.offsetY, opacity: d.elevation.high.opacity)
        }

        func typo(_ p: String, _ fallback: Double) -> Double {
            guard case let .typography(t)? = try? graph.resolve("typography.\(p)") else { return fallback }
            return t.fontSize
        }
        d.typography.display = typo("display", d.typography.display)
        d.typography.title = typo("title", d.typography.title)
        d.typography.body = typo("body", d.typography.body)
        d.typography.bodyMono = typo("bodyMono", d.typography.bodyMono)
        d.typography.label = typo("label", d.typography.label)
        d.typography.caption = typo("caption", d.typography.caption)
        d.typography.micro = typo("micro", d.typography.micro)
        d.typography.meta = typo("meta", d.typography.meta)
        d.typography.emphasis = typo("emphasis", d.typography.emphasis)
        d.typography.fontSize = typo("prose", d.typography.fontSize)

        if case let .fontFamily(raw)? = try? graph.resolve("material.role"),
           let role = MaterialRole(rawValue: raw) {
            d.material.role = role
        }

        func num(_ p: String, _ fallback: Double) -> Double {
            switch try? graph.resolve("sand.\(p)") {
            case let .number(v)?, let .dimension(v)?: return v
            default: return fallback
            }
        }
        d.sand.swirl = num("swirl", d.sand.swirl)
        d.sand.swirlScale = num("swirlScale", d.sand.swirlScale)
        d.sand.drift = num("drift", d.sand.drift)
        d.sand.drag = num("drag", d.sand.drag)
        d.sand.brownian = num("brownian", d.sand.brownian)
        d.sand.parallaxDepth = num("parallaxDepth", d.sand.parallaxDepth)
        d.sand.obstacleRadius = num("obstacleRadius", d.sand.obstacleRadius)
        d.sand.obstaclePad = num("obstaclePad", d.sand.obstaclePad)
        d.sand.dustCount = num("dustCount", d.sand.dustCount)
        d.sand.dustSize = num("dustSize", d.sand.dustSize)
        d.sand.dustFog = num("dustFog", d.sand.dustFog)
        d.sand.dustBase = num("dustBase", d.sand.dustBase)
        d.sand.dustBrightness = num("dustBrightness", d.sand.dustBrightness)
        d.sand.shaftStrength = num("shaftStrength", d.sand.shaftStrength)
        d.sand.shaftX = num("shaftX", d.sand.shaftX)
        d.sand.shaftY = num("shaftY", d.sand.shaftY)
        d.sand.shaftSpread = num("shaftSpread", d.sand.shaftSpread)
        d.sand.shaftRays = num("shaftRays", d.sand.shaftRays)
        d.sand.shaftFalloff = num("shaftFalloff", d.sand.shaftFalloff)
        d.sand.shaftSourceGlow = num("shaftSourceGlow", d.sand.shaftSourceGlow)
        d.sand.shaftDrift = num("shaftDrift", d.sand.shaftDrift)
        d.sand.shaftBg = num("shaftBg", d.sand.shaftBg)
        d.sand.beamFlutter = num("beamFlutter", d.sand.beamFlutter)
        d.sand.beamFlutterSpeed = num("beamFlutterSpeed", d.sand.beamFlutterSpeed)
        d.sand.goboStrength = num("goboStrength", d.sand.goboStrength)
        d.sand.goboScale = num("goboScale", d.sand.goboScale)
        d.sand.goboDrift = num("goboDrift", d.sand.goboDrift)
        d.sand.gustAmount = num("gustAmount", d.sand.gustAmount)
        d.sand.gustRate = num("gustRate", d.sand.gustRate)
        d.sand.lightSway = num("lightSway", d.sand.lightSway)
        d.sand.lightLean = num("lightLean", d.sand.lightLean)
        d.sand.volSteps = num("volSteps", d.sand.volSteps)
        d.sand.volDensity = num("volDensity", d.sand.volDensity)
        d.sand.volExtinction = num("volExtinction", d.sand.volExtinction)
        d.sand.volScale = num("volScale", d.sand.volScale)
        d.sand.volDrift = num("volDrift", d.sand.volDrift)
        d.sand.volJitter = num("volJitter", d.sand.volJitter)
        d.sand.taaAlpha = num("taaAlpha", d.sand.taaAlpha)
        d.sand.layerClose = num("layerClose", d.sand.layerClose ? 1 : 0) > 0.5
        d.sand.layerNear = num("layerNear", d.sand.layerNear ? 1 : 0) > 0.5
        d.sand.layerMid = num("layerMid", d.sand.layerMid ? 1 : 0) > 0.5
        d.sand.layerFar = num("layerFar", d.sand.layerFar ? 1 : 0) > 0.5
        d.sand.layerHaze = num("layerHaze", d.sand.layerHaze ? 1 : 0) > 0.5
        d.sand.bloomIntensity = num("bloomIntensity", d.sand.bloomIntensity)
        d.sand.bloomThreshold = num("bloomThreshold", d.sand.bloomThreshold)
        d.sand.bloomIterations = num("bloomIterations", d.sand.bloomIterations)
        d.sand.dither = num("dither", d.sand.dither)
        d.sand.exposure = num("exposure", d.sand.exposure)
        d.sand.tonemap = num("tonemap", d.sand.tonemap)
        d.sand.idleWindow = num("idleWindow", d.sand.idleWindow)
        d.sand.impulseScale = num("impulseScale", d.sand.impulseScale)
    }
}
