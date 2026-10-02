import AppKit
import SandCore
import SwiftUI

/// The resolved parameters of the dust system (see `SandCore/TRUTH.md`). The
/// colour comes from the preset; every numeric knob is overridable from tokens,
/// so the surface is data-driven and round-trips through the token graph.
struct SandStyle: Equatable {
    // palette
    var shaftColor: Color
    var sparkleColor: Color
    // motion — Langevin
    var swirl: Double
    var swirlScale: Double
    var drift: Double
    var drag: Double
    var brownian: Double
    var parallaxDepth: Double
    // obstacles
    var obstacleRadius: Double
    var obstaclePad: Double
    // dust
    var dustCount: Double
    var dustSize: Double
    var dustFog: Double
    var dustBase: Double
    var dustBrightness: Double
    // light — a cone of light from a point above the top edge (god-ray)
    var shaftStrength: Double
    var shaftX: Double
    var shaftY: Double
    var shaftSpread: Double
    var shaftRays: Double
    var shaftFalloff: Double
    var shaftSourceGlow: Double
    var shaftDrift: Double
    var shaftBg: Double
    var beamFlutter: Double
    var beamFlutterSpeed: Double
    var goboStrength: Double
    var goboScale: Double
    var goboDrift: Double
    var gustAmount: Double
    var gustRate: Double
    var lightSway: Double
    var lightLean: Double
    // volumetric light (march + temporal AA)
    var volSteps: Double
    var volDensity: Double
    var volExtinction: Double
    var volScale: Double
    var volDrift: Double
    var volJitter: Double
    var taaAlpha: Double
    // depth layers + per-layer debug enables
    var layerClose: Bool
    var layerNear: Bool
    var layerMid: Bool
    var layerFar: Bool
    var layerHaze: Bool
    // render
    var bloomIntensity: Double
    var bloomThreshold: Double
    var bloomIterations: Double
    var dither: Double
    var exposure: Double
    var tonemap: Double

    /// Dust floating in a dark room, lit by soft beams that flitter like light
    /// through a window; layered spice drifts closer to the camera.
    static let sand = SandStyle(
        shaftColor: Color(red: 1.0, green: 0.60, blue: 0.28),
        sparkleColor: Color(red: 1.0, green: 0.55, blue: 0.22),
        swirl: 0.2844362745098039, swirlScale: 1.2040543300653592, drift: 0.0, drag: 9.498008578431373, brownian: 0.008,
        parallaxDepth: 0.6,
        obstacleRadius: 0.008, obstaclePad: 0.015,
        dustCount: 12000.0, dustSize: 2.2, dustFog: 1.6, dustBase: 0.08, dustBrightness: 1.0,
        shaftStrength: 1.0865093954248366, shaftX: 0.5, shaftY: -0.07350847630718949, shaftSpread: 90.0,
        shaftRays: 7.0, shaftFalloff: 2.6743872549019607, shaftSourceGlow: 0.9056883169934641,
        shaftDrift: 0.03, shaftBg: 0.2,
        beamFlutter: 0.6, beamFlutterSpeed: 1.2,
        goboStrength: 0.0, goboScale: 3.0, goboDrift: 0.06,
        gustAmount: 0.5, gustRate: 0.07,
        lightSway: 0.4, lightLean: 0.0,
        volSteps: 24.0, volDensity: 1.4, volExtinction: 0.5, volScale: 2.2,
        volDrift: 0.05, volJitter: 1.0, taaAlpha: 0.18,
        layerClose: true, layerNear: true, layerMid: true, layerFar: true, layerHaze: true,
        bloomIntensity: 0.4209354575163399, bloomThreshold: 0.6, bloomIterations: 4.0,
        dither: 0.012, exposure: 0.17888327205882354, tonemap: 1.0)

    /// Apply the user-tunable token overrides (the palette stays from the preset).
    func merging(_ t: DesignTokens.Sand) -> SandStyle {
        var s = self
        s.swirl = t.swirl
        s.swirlScale = t.swirlScale
        s.drift = t.drift
        s.drag = t.drag
        s.brownian = t.brownian
        s.parallaxDepth = t.parallaxDepth
        s.obstacleRadius = t.obstacleRadius
        s.obstaclePad = t.obstaclePad
        s.dustCount = t.dustCount
        s.dustSize = t.dustSize
        s.dustFog = t.dustFog
        s.dustBase = t.dustBase
        s.dustBrightness = t.dustBrightness
        s.shaftStrength = t.shaftStrength
        s.shaftX = t.shaftX
        s.shaftY = t.shaftY
        s.shaftSpread = t.shaftSpread
        s.shaftRays = t.shaftRays
        s.shaftFalloff = t.shaftFalloff
        s.shaftSourceGlow = t.shaftSourceGlow
        s.shaftDrift = t.shaftDrift
        s.shaftBg = t.shaftBg
        s.beamFlutter = t.beamFlutter
        s.beamFlutterSpeed = t.beamFlutterSpeed
        s.goboStrength = t.goboStrength
        s.goboScale = t.goboScale
        s.goboDrift = t.goboDrift
        s.gustAmount = t.gustAmount
        s.gustRate = t.gustRate
        s.lightSway = t.lightSway
        s.lightLean = t.lightLean
        s.volSteps = t.volSteps
        s.volDensity = t.volDensity
        s.volExtinction = t.volExtinction
        s.volScale = t.volScale
        s.volDrift = t.volDrift
        s.volJitter = t.volJitter
        s.taaAlpha = t.taaAlpha
        s.layerClose = t.layerClose
        s.layerNear = t.layerNear
        s.layerMid = t.layerMid
        s.layerFar = t.layerFar
        s.layerHaze = t.layerHaze
        s.bloomIntensity = t.bloomIntensity
        s.bloomThreshold = t.bloomThreshold
        s.bloomIterations = t.bloomIterations
        s.dither = t.dither
        s.exposure = t.exposure
        s.tonemap = t.tonemap
        return s
    }
}

extension SandStyle {
    /// Resolve into the shared engine config consumed by `SandPipeline`.
    var config: SandConfig {
        SandConfig(
            shaftColor: shaftColor.simdRGB,
            sparkleColor: sparkleColor.simdRGB,
            swirl: swirl, swirlScale: swirlScale, drift: drift, drag: drag, brownian: brownian,
            parallaxDepth: parallaxDepth,
            obstacleRadius: obstacleRadius, obstaclePad: obstaclePad,
            dustCount: dustCount, dustSize: dustSize, dustFog: dustFog,
            dustBase: dustBase, dustBrightness: dustBrightness,
            shaftStrength: shaftStrength, shaftX: shaftX, shaftY: shaftY,
            shaftSpread: shaftSpread, shaftRays: shaftRays, shaftFalloff: shaftFalloff,
            shaftSourceGlow: shaftSourceGlow, shaftDrift: shaftDrift, shaftBg: shaftBg,
            beamFlutter: beamFlutter, beamFlutterSpeed: beamFlutterSpeed,
            goboStrength: goboStrength, goboScale: goboScale, goboDrift: goboDrift,
            gustAmount: gustAmount, gustRate: gustRate,
            lightSway: lightSway, lightLean: lightLean,
            volSteps: volSteps, volDensity: volDensity, volExtinction: volExtinction,
            volScale: volScale, volDrift: volDrift, volJitter: volJitter, taaAlpha: taaAlpha,
            layerClose: layerClose, layerNear: layerNear, layerMid: layerMid,
            layerFar: layerFar, layerHaze: layerHaze,
            bloomIntensity: bloomIntensity, bloomThreshold: bloomThreshold,
            bloomIterations: bloomIterations, dither: dither,
            exposure: exposure, tonemap: tonemap)
    }
}

extension Color {
    var simdRGB: SIMD3<Float> {
        let c = NSColor(self).usingColorSpace(.deviceRGB) ?? .black
        return SIMD3(Float(c.redComponent), Float(c.greenComponent), Float(c.blueComponent))
    }
}
