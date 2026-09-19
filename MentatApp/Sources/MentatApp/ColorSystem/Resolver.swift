import SwiftUI

/// OKLCH-native palette controls — what the palette tool exposes: a scheme
/// (how the roles relate to the image hue), a hue shift, chroma/contrast/tint
/// strengths, and whether to follow the image or force a hue.
struct ColorControls: Equatable, Codable, Sendable {
    var scheme: PaletteScheme = .primary
    var hueShift: Double = 0  // degrees
    var chroma: Double = 1.4  // 0…2 multiplier
    var contrast: Double = 1.1  // 0.6…1.8 lightness separation
    var tintStrength: Double = 1.3  // 0…2 stain on surfaces/accents
    var followImage: Bool = true  // when off, hue/chroma apply even on greyscale images
    var light: Bool = false
    var monochrome: Bool = false
    static let `default` = ColorControls()
}

/// A fully resolved, contrast-enforced theme derived from an image.
struct ColorTheme: Equatable, Sendable {
    var isLight: Bool
    var baseHue: Double
    var ink: Color
    var inkDim: Color
    var accent: Color
    var onAccent: Color
    /// Additional hued roles so multi-hue schemes show up across the chrome.
    var secondary: Color
    var tertiary: Color
    var surface: Color
    /// The tint to pass to a Liquid Glass material ("stained glass"): a low-alpha
    /// tone from the image hue that colours the material rather than sitting on
    /// top of it.
    var surfaceTint: Color
    /// Vivid tint for Liquid Glass *controls* (accent-derived) — gives the
    /// material real colour, where `surfaceTint` deliberately stays muted.
    var accentTint: Color { accent.opacity(0.55) }
    /// Lighter tint for the *Clear* Liquid Glass variant — colour still reads,
    /// but more translucency is preserved.
    var clearTint: Color { accent.opacity(0.34) }
    var background: Color
    var border: Color
    var good: Color
    var bad: Color

    static let placeholder = ColorTheme(
        isLight: false, baseHue: 0,
        ink: .white, inkDim: Color(white: 0.72),
        accent: Color(white: 0.90), onAccent: .black,
        secondary: Color(white: 0.80), tertiary: Color(white: 0.70),
        surface: Color(white: 0.18), surfaceTint: Color.white.opacity(0.40),
        background: Color(white: 0.12), border: Color(white: 0.30),
        good: Color(white: 0.70), bad: Color(white: 0.60))
}

/// Builds a theme from an image palette + controls, enforcing WCAG contrast on
/// every text/UI pairing. Hue follows the image; surfaces carry a whisper of it.
enum ColorResolver {
    static func theme(for p: ImagePalette, controls: ColorControls) -> ColorTheme {
        let mono = controls.monochrome || (p.isNeutral && controls.followImage)
        let imageHue = mono ? 0 : normalized(p.baseHue + controls.hueShift)
        let strength = min(2.0, max(0, controls.tintStrength))
        let baseChroma =
            mono ? 0 : min(0.28, max(0.06, p.meanChroma * 1.05)) * max(0, controls.chroma) * strength
        let light = controls.light
        let sep = min(1.8, max(0.6, controls.contrast))

        // The scheme drives the *dominant* hue: primary/monochrome stay on the
        // image hue; complementary/triadic/split rotate the whole palette.
        var accentHue = normalized(imageHue + controls.scheme.accentOffset)
        var secondaryHue = normalized(imageHue + controls.scheme.secondaryOffset)
        var tertiaryHue = normalized(imageHue + controls.scheme.tertiaryOffset)
        if controls.scheme == .fromImage {
            let colorful = p.clusters.filter { $0.color.c > 0.04 }
                .sorted { $0.weight > $1.weight }
            if let a = colorful.first { accentHue = a.color.h }
            if colorful.count >= 2 { secondaryHue = colorful[1].color.h }
            if colorful.count >= 3 { tertiaryHue = colorful[2].color.h }
        }
        let surfaceHue = accentHue  // surfaces + accent share the scheme hue

        func tone(_ h: Double, _ chroma: Double, _ lightness: Double) -> ColorScience.OKLCH {
            ColorScience.OKLCH(l: clamp(lightness), c: max(0, chroma), h: normalized(h))
        }
        // A visible stained-glass tint on surfaces (medium intensity).
        let surfaceChroma = mono ? 0 : min(0.18, baseChroma * 0.85)

        // Lightness separation grows with the contrast control.
        let bgL = light ? 0.96 : max(0.08, 0.18 - (sep - 1) * 0.06)
        let surfL = light ? 0.90 : min(0.34, 0.24 + (sep - 1) * 0.05)
        let inkL = light ? max(0.10, 0.18 - (sep - 1) * 0.05) : min(0.99, 0.94 + (sep - 1) * 0.03)
        let inkDimL = light ? 0.44 : 0.72

        let background = tone(surfaceHue, surfaceChroma * 0.6, bgL)
        let surface = tone(surfaceHue, surfaceChroma, surfL)

        var ink = tone(surfaceHue, mono ? 0 : min(0.03, baseChroma * 0.3), inkL)
        ink = ColorScience.enforce(ink, on: surface, level: .body)
        var inkDim = tone(surfaceHue, mono ? 0 : min(0.03, baseChroma * 0.3), inkDimL)
        inkDim = ColorScience.enforce(inkDim, on: surface, level: .body)

        let accentChroma = mono ? 0 : min(0.32, max(0.14, baseChroma * 2.2))
        let accentL = light ? 0.50 : 0.74
        let accent = ColorScience.enforce(
            tone(accentHue, accentChroma, accentL),
            on: background, level: .large)
        let onAccent = ColorScience.enforce(
            ColorScience.OKLCH(l: light ? 1.0 : 0.12, c: 0, h: surfaceHue), on: accent, level: .body
        )

        // Secondary/tertiary: separate hues, or (for primary/monochrome) the same
        // hue separated by lightness — tonal variants of one colour.
        let roleChroma = mono ? 0 : min(0.26, max(0.10, baseChroma * 1.7))
        let secondary = ColorScience.enforce(
            tone(secondaryHue, roleChroma, light ? 0.46 : 0.68), on: background, level: .large)
        let tertiary = ColorScience.enforce(
            tone(tertiaryHue, roleChroma, light ? 0.42 : 0.62), on: background, level: .large)

        let border = tone(surfaceHue, mono ? 0 : surfaceChroma * 0.8, light ? 0.72 : 0.40)
        let good = ColorScience.enforce(
            tone(145, mono ? 0 : 0.11, light ? 0.40 : 0.72), on: background, level: .large)
        let bad = ColorScience.enforce(
            tone(28, mono ? 0 : 0.13, light ? 0.45 : 0.70), on: background, level: .large)

        // Stained glass: a low-alpha tone that colours the material itself.
        let tint = tone(surfaceHue, surfaceChroma, light ? 0.82 : 0.34)
        let tintAlpha = min(1.0, (light ? 0.74 : 0.72) * strength)
        let surfaceTint = Color(nsColor: ColorScience.nsColor(tint, alpha: tintAlpha))

        return ColorTheme(
            isLight: light, baseHue: surfaceHue,
            ink: Color(nsColor: ColorScience.nsColor(ink)),
            inkDim: Color(nsColor: ColorScience.nsColor(inkDim)),
            accent: Color(nsColor: ColorScience.nsColor(accent)),
            onAccent: Color(nsColor: ColorScience.nsColor(onAccent)),
            secondary: Color(nsColor: ColorScience.nsColor(secondary)),
            tertiary: Color(nsColor: ColorScience.nsColor(tertiary)),
            surface: Color(nsColor: ColorScience.nsColor(surface)),
            surfaceTint: surfaceTint,
            background: Color(nsColor: ColorScience.nsColor(background)),
            border: Color(nsColor: ColorScience.nsColor(border)),
            good: Color(nsColor: ColorScience.nsColor(good)),
            bad: Color(nsColor: ColorScience.nsColor(bad)))
    }

    private static func normalized(_ h: Double) -> Double {
        var x = h.truncatingRemainder(dividingBy: 360)
        if x < 0 { x += 360 }
        return x
    }
    private static func clamp(_ v: Double) -> Double { min(1, max(0, v)) }
}
