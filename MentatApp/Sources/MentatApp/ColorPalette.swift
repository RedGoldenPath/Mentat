import SwiftUI
import AppKit

/// A role in the artwork-derived palette. The roles are the classic colour
/// relations, so a UI element can ask for "the analogous tone" or "the
/// complementary accent" instead of a hard-coded colour.
enum PaletteRole: String, CaseIterable, Codable {
    case dominant           // the image's most common colour
    case secondary          // the next most common
    case analogous          // +30°  (same temperature family)
    case complementary      // +180° (opposite temperature)
    case triadic            // +120°
    case accent             // saturated contrasting tone for controls
    case surface            // deep, low-sat tone for large surfaces (rail)
    case ink                // text over the art (brightness first, hue whisper)
    case inkDim             // secondary text
}

/// How the derived palette is put together from the image's dominant hue. This
/// is the user-facing "palette style" — separate from which image is chosen.
enum PaletteStyle: String, CaseIterable, Identifiable {
    case complementary, analogous, triadic, split, main, secondary, tertiary, monochrome
    var id: String { rawValue }

    var label: String {
        switch self {
        case .complementary: return "Complementary"
        case .analogous:     return "Analogous"
        case .triadic:       return "Triadic"
        case .split:         return "Split"
        case .main:          return "Main"
        case .secondary:     return "Secondary"
        case .tertiary:      return "Tertiary"
        case .monochrome:    return "Monochrome"
        }
    }

    var accentOffset: Double {
        switch self {
        case .main:          return 0
        case .analogous:     return 0.083     // +30°
        case .secondary:     return 0.166     // +60°
        case .tertiary:      return 0.333     // +120°
        case .complementary: return 0.5       // +180°
        case .triadic:       return 0.333     // +120°
        case .split:         return 0.417     // +150° (split-complement)
        case .monochrome:    return 0.5
        }
    }
    var surfaceOffset: Double {
        switch self {
        case .main:          return 0
        case .analogous:     return 0.083
        case .secondary:     return 0.166
        case .tertiary:      return 0.333
        case .complementary: return 0.083
        case .triadic:       return 0.166
        case .split:         return 0.083
        case .monochrome:    return 0
        }
    }
    var monochrome: Bool { self == .monochrome }
}

/// Codable sRGB colour so a palette can be persisted next to its image.
struct RGBA: Codable, Equatable {
    var r: Double, g: Double, b: Double, a: Double

    init(_ ns: NSColor) {
        let c = ns.usingColorSpace(.sRGB) ?? NSColor(white: 0.5, alpha: 1)
        r = Double(c.redComponent); g = Double(c.greenComponent)
        b = Double(c.blueComponent); a = Double(c.alphaComponent)
    }
    init(r: Double, g: Double, b: Double, a: Double = 1) {
        self.r = r; self.g = g; self.b = b; self.a = a
    }
    var nsColor: NSColor { NSColor(srgbRed: r, green: g, blue: b, alpha: a) }
    var color: Color { Color(nsColor) }

    func rotatedHue(_ degrees: Double) -> RGBA {
        guard a > 0.001 else { return self }
        let ns = nsColor
        var h: CGFloat = 0, s: CGFloat = 0, br: CGFloat = 0, al: CGFloat = 0
        ns.getHue(&h, saturation: &s, brightness: &br, alpha: &al)
        guard s > 0.02 else { return self }
        let nh = CGFloat((Double(h) + degrees / 360).truncatingRemainder(dividingBy: 1))
        return RGBA(NSColor(hue: nh < 0 ? nh + 1 : nh, saturation: s, brightness: br, alpha: al))
    }
}

/// One quantized colour sampled from the image, with the share of pixels it
/// accounts for.
struct ColorCluster: Codable, Equatable {
    var color: RGBA
    var weight: Double          // 0…1 of the sampled pixels
}

/// The full analysis of one image: the main colour clusters (with percentages),
/// a hue histogram, and the weighted hue / saturation / brightness. Everything a
/// palette needs is derived from this.
struct ImageAnalysis: Codable, Equatable {
    var clusters: [ColorCluster]
    var hueHistogram: [Double]   // 12 bins of 30°, weighted by saturation
    var dominantHue: Double      // 0…1 (circular weighted mean of colorful pixels)
    var baseHue: Double          // 0…1 — the hue the palette is built from
    var saturation: Double       // weighted mean
    var brightness: Double       // weighted mean luminance
    var temperature: String      // "warm" | "cool" | "neutral"
    var isLight: Bool
    var isNeutral: Bool

    static let empty = ImageAnalysis(clusters: [], hueHistogram: Array(repeating: 0, count: 12),
                                     dominantHue: 0, baseHue: 0, saturation: 0, brightness: 0.5,
                                     temperature: "neutral", isLight: false, isNeutral: true)
}

/// Material-style semantic colour roles, generated as *tonal palettes* from the
/// image's hue (like Material You / MD3 dynamic colour). Secondary chrome reads
/// these instead of fixed theme colours, so the whole UI follows the image.
struct ColorTokens: Codable, Equatable {
    var primary: RGBA
    var onPrimary: RGBA
    var primaryContainer: RGBA
    var onPrimaryContainer: RGBA
    var secondary: RGBA
    var secondaryContainer: RGBA
    var onSecondaryContainer: RGBA
    var tertiary: RGBA
    var tertiaryContainer: RGBA
    var onTertiaryContainer: RGBA
    var surface: RGBA
    var surfaceVariant: RGBA
    var onSurface: RGBA
    var onSurfaceVariant: RGBA
    var outline: RGBA
    var isDark: Bool

    func rgba(_ role: TokenRole) -> RGBA {
        switch role {
        case .primary: return primary
        case .onPrimary: return onPrimary
        case .primaryContainer: return primaryContainer
        case .onPrimaryContainer: return onPrimaryContainer
        case .secondary: return secondary
        case .secondaryContainer: return secondaryContainer
        case .onSecondaryContainer: return onSecondaryContainer
        case .tertiary: return tertiary
        case .tertiaryContainer: return tertiaryContainer
        case .onTertiaryContainer: return onTertiaryContainer
        case .surface: return surface
        case .surfaceVariant: return surfaceVariant
        case .onSurface: return onSurface
        case .onSurfaceVariant: return onSurfaceVariant
        case .outline: return outline
        }
    }
    func color(_ role: TokenRole) -> Color { rgba(role).color }
}

enum TokenRole: String, CaseIterable {
    case primary, onPrimary, primaryContainer, onPrimaryContainer
    case secondary, secondaryContainer, onSecondaryContainer
    case tertiary, tertiaryContainer, onTertiaryContainer
    case surface, surfaceVariant, onSurface, onSurfaceVariant, outline
}

extension ColorTokens {
    /// One tone from a tonal palette: `tone` 0…100 (0 black, 100 white), coloured
    /// by `hue`/`chroma` and only saturated in the mid tones (an HCT-ish ramp).
    static func tone(_ hue: Double, _ chroma: Double, _ tone: Double, neutral: Bool) -> RGBA {
        if neutral || chroma <= 0.01 {
            return RGBA(NSColor(white: tone / 100, alpha: 1))
        }
        let l = tone / 100
        let s = min(0.97, chroma * (1 - abs(2 * l - 1)) + chroma * 0.34)
        let h = CGFloat(hue < 0 ? hue + 1 : hue)
        return RGBA(NSColor(hue: h, saturation: CGFloat(s), brightness: CGFloat(l), alpha: 1))
    }

    /// Build the Material-You-style role set for a source hue. `dark` picks the
    /// dark scheme; `monochrome` collapses everything to neutral greys.
    static func make(hue: Double, chroma: Double, dark: Bool, monochrome: Bool) -> ColorTokens {
        let neutral = monochrome
        let p = neutral ? 0 : max(0.45, min(0.92, chroma))
        let s = neutral ? 0 : max(0.36, p * 0.80)
        let t = neutral ? 0 : max(0.42, p * 0.92)
        let n = neutral ? 0 : max(0.18, p * 0.34)
        let nv = neutral ? 0 : max(0.24, p * 0.46)

        func c(_ dh: Double, _ ch: Double, _ light: Double, _ darkTone: Double) -> RGBA {
            tone(hue + dh, ch, dark ? darkTone : light, neutral: neutral)
        }
        return ColorTokens(
            primary:              c(0, p, 40, 80),
            onPrimary:            c(0, p, 100, 20),
            primaryContainer:     c(0, p, 90, 30),
            onPrimaryContainer:   c(0, p * 0.5, 12, 90),
            secondary:            c(0, s, 42, 80),
            secondaryContainer:   c(0, s, 90, 30),
            onSecondaryContainer: c(0, s * 0.5, 12, 90),
            tertiary:             c(0.166, t, 42, 80),
            tertiaryContainer:    c(0.166, t, 90, 30),
            onTertiaryContainer:  c(0.166, t * 0.5, 12, 90),
            surface:              c(0, n, 98, 10),
            surfaceVariant:       c(0, nv, 92, 24),
            onSurface:            c(0, n, 12, 94),
            onSurfaceVariant:     c(0, nv, 32, 82),
            outline:              c(0, nv, 52, 62),
            isDark: dark)
    }

    static let neutralLight = make(hue: 0, chroma: 0, dark: false, monochrome: true)
    static let neutralDark = make(hue: 0, chroma: 0, dark: true, monochrome: true)
}

/// A whole palette derived from one image's analysis, with a role for every
/// colour decision the UI needs.
struct BackgroundPalette: Codable, Equatable {
    var roles: [String: RGBA]
    var temperature: String
    var isLight: Bool
    var tokens: ColorTokens = .neutralLight
    /// The dark-scheme token set, for surfaces that are always dark (the rail).
    var tokensDark: ColorTokens = .neutralDark

    func color(_ role: PaletteRole) -> Color { (roles[role.rawValue] ?? RGBA(.gray)).color }
    func ns(_ role: PaletteRole) -> NSColor { (roles[role.rawValue] ?? RGBA(.gray)).nsColor }
    var dominant: Color { color(.dominant) }
    var analogous: Color { color(.analogous) }
    var secondary: Color { color(.secondary) }
    var complementary: Color { color(.complementary) }
    var triadic: Color { color(.triadic) }
    var accent: Color { color(.accent) }
    var surface: Color { color(.surface) }
    var ink: Color { color(.ink) }
    var inkDim: Color { color(.inkDim) }

    var isWarm: Bool { temperature == "warm" }
    var isNeutral: Bool { temperature == "neutral" }

    func rotated(by degrees: Double) -> BackgroundPalette {
        guard abs(degrees.truncatingRemainder(dividingBy: 360)) > 0.01 else { return self }
        var out = self
        out.roles = roles.mapValues { $0.rotatedHue(degrees) }
        return out
    }

    static let placeholder = BackgroundPalette(
        roles: [PaletteRole.ink.rawValue: RGBA(NSColor(white: 0.96, alpha: 1)),
                PaletteRole.inkDim.rawValue: RGBA(NSColor(white: 0.96, alpha: 0.78)),
                PaletteRole.accent.rawValue: RGBA(NSColor(white: 0.90, alpha: 1)),
                PaletteRole.surface.rawValue: RGBA(NSColor(white: 0.12, alpha: 0.70))],
        temperature: "neutral", isLight: false)
}

/// Samples an image, quantizes it into its main colours, and measures hue,
/// saturation and brightness (weighted by how much of the image each colour
/// occupies).
enum PaletteAnalyzer {
    /// Per-channel quantization levels for the histogram (6³ = 216 buckets).
    private static let levels = 6

    static func analyze(_ image: NSImage) -> ImageAnalysis {
        let side = 56
        guard let px = pixels(image, side: side) else { return .empty }

        struct Bucket { var r = 0.0, g = 0.0, b = 0.0, n = 0.0 }
        var buckets: [Int: Bucket] = [:]
        var sampled = 0.0

        for i in stride(from: 0, to: px.count, by: 4) {
            let a = Double(px[i + 3]) / 255
            if a < 0.5 { continue }
            let r = Double(px[i]) / 255, g = Double(px[i + 1]) / 255, b = Double(px[i + 2]) / 255
            let key = (min(levels - 1, Int(r * Double(levels))) * levels
                       + min(levels - 1, Int(g * Double(levels)))) * levels
                      + min(levels - 1, Int(b * Double(levels)))
            var bk = buckets[key] ?? Bucket()
            bk.r += r; bk.g += g; bk.b += b; bk.n += 1
            buckets[key] = bk
            sampled += 1
        }
        guard sampled > 0 else { return .empty }

        // Average each bucket, then greedily merge nearby colours into clusters.
        var items: [(NSColor, Double)] = buckets.values.map { bk in
            (NSColor(srgbRed: bk.r / bk.n, green: bk.g / bk.n, blue: bk.b / bk.n, alpha: 1), bk.n)
        }
        items.sort { $0.1 > $1.1 }

        var merged: [(color: NSColor, count: Double)] = []
        let mergeDist: CGFloat = 0.14
        for (c, n) in items {
            if let i = merged.firstIndex(where: { distance($0.color, c) < mergeDist }) {
                let total = merged[i].count + n
                let w = n / total
                merged[i].color = blend(merged[i].color, c, w)
                merged[i].count = total
            } else {
                merged.append((c, n))
            }
        }
        merged.sort { $0.count > $1.count }
        let top = Array(merged.prefix(7))
        let total = max(1, merged.reduce(0) { $0 + $1.count })

        let clusters = top.map { ColorCluster(color: RGBA($0.color), weight: $0.count / total) }

        // Weighted metrics over the clusters.
        var lum = 0.0, sat = 0.0, wsum = 0.0
        var hueSin = 0.0, hueCos = 0.0
        var hist = Array(repeating: 0.0, count: 12)
        for c in clusters {
            var h: CGFloat = 0, s: CGFloat = 0, br: CGFloat = 0, al: CGFloat = 0
            c.color.nsColor.getHue(&h, saturation: &s, brightness: &br, alpha: &al)
            lum += Double(ColorTheory.luminance(c.color.nsColor)) * c.weight
            sat += Double(s) * c.weight
            let w = c.weight * Double(max(0.05, s))       // greys barely skew hue
            wsum += w
            hueSin += sin(Double(h) * 2 * .pi) * w
            hueCos += cos(Double(h) * 2 * .pi) * w
            let b = min(11, max(0, Int(Double(h) * 12)))
            hist[b] += w
        }
        let hue = wsum > 0 ? atan2(hueSin, hueCos) / (2 * .pi) : 0
        let dominantHue = hue < 0 ? hue + 1 : hue
        if hist.max() ?? 0 > 0 { let m = hist.max()!; hist = hist.map { $0 / m } }

        let isNeutral = sat < 0.12

        // The palette is built from the *main* colour when one cluster clearly
        // dominates (so a sand photo gets a sand palette); otherwise it falls
        // back to the saturation-weighted hue of the whole image.
        var baseHue = dominantHue
        if let top = clusters.first, top.weight >= 0.34 {
            var th: CGFloat = 0, ts: CGFloat = 0, tb: CGFloat = 0, ta: CGFloat = 0
            top.color.nsColor.getHue(&th, saturation: &ts, brightness: &tb, alpha: &ta)
            if ts >= 0.12 { baseHue = Double(th) }
        }
        let temp: String = isNeutral
            ? "neutral"
            : (ColorTheory.temperature(NSColor(hue: CGFloat(baseHue), saturation: 0.6,
                                               brightness: 0.7, alpha: 1)) == .warm ? "warm" : "cool")

        return ImageAnalysis(clusters: clusters, hueHistogram: hist,
                             dominantHue: dominantHue, baseHue: baseHue,
                             saturation: sat, brightness: lum,
                             temperature: temp, isLight: lum >= 0.5, isNeutral: isNeutral)
    }

    private static func pixels(_ image: NSImage, side: Int) -> [UInt8]? {
        guard let cg = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else { return nil }
        var buf = [UInt8](repeating: 0, count: side * side * 4)
        let cs = CGColorSpaceCreateDeviceRGB()
        let info = CGImageAlphaInfo.premultipliedLast.rawValue
        buf.withUnsafeMutableBytes { raw in
            if let ctx = CGContext(data: raw.baseAddress, width: side, height: side,
                                   bitsPerComponent: 8, bytesPerRow: side * 4,
                                   space: cs, bitmapInfo: info) {
                ctx.interpolationQuality = .medium
                ctx.draw(cg, in: CGRect(x: 0, y: 0, width: side, height: side))
            }
        }
        return buf
    }

    static func distance(_ a: NSColor, _ b: NSColor) -> CGFloat {
        let x = a.usingColorSpace(.sRGB) ?? .gray, y = b.usingColorSpace(.sRGB) ?? .gray
        return sqrt(pow(x.redComponent - y.redComponent, 2)
                    + pow(x.greenComponent - y.greenComponent, 2)
                    + pow(x.blueComponent - y.blueComponent, 2))
    }
    private static func blend(_ a: NSColor, _ b: NSColor, _ t: CGFloat) -> NSColor {
        let x = a.usingColorSpace(.sRGB) ?? .gray, y = b.usingColorSpace(.sRGB) ?? .gray
        return NSColor(srgbRed: x.redComponent + (y.redComponent - x.redComponent) * t,
                       green: x.greenComponent + (y.greenComponent - x.greenComponent) * t,
                       blue: x.blueComponent + (y.blueComponent - x.blueComponent) * t, alpha: 1)
    }
}

/// Turns an `ImageAnalysis` into a UI palette for a given style. The sampled
/// clusters supply the *actual* main colours (dominant/secondary); hue + style
/// derive the relational tones; brightness sets the value range.
enum PaletteExtractor {
    static func palette(from a: ImageAnalysis, style: PaletteStyle,
                        dark: Bool = false, monochrome: Bool = false) -> BackgroundPalette {
        guard !a.clusters.isEmpty else { return .placeholder }
        let neutral = a.isNeutral || style.monochrome
        let h = a.baseHue
        let lum = a.brightness
        let satBase = neutral ? 0 : min(0.80, max(0.26, a.saturation * 1.15))

        func tone(_ dh: Double, sat: CGFloat, val: CGFloat, alpha: CGFloat = 1) -> RGBA {
            guard !neutral else { return RGBA(NSColor(white: val, alpha: alpha)) }
            let hue = CGFloat((h + dh).truncatingRemainder(dividingBy: 1))
            return RGBA(NSColor(hue: hue < 0 ? hue + 1 : hue,
                                saturation: sat, brightness: val, alpha: alpha))
        }
        /// Interpolate a value between its dark-art and bright-art endpoints.
        func v(_ bright: CGFloat, _ dark: CGFloat) -> CGFloat { dark + (bright - dark) * CGFloat(lum) }

        let inkVal: CGFloat = lum < 0.5 ? 1.0 : 0.03
        let inkHue = CGFloat((h + 0.5).truncatingRemainder(dividingBy: 1))
        let inkSat = neutral ? 0 : min(0.10, CGFloat(a.saturation) * 0.2)

        var roles: [String: RGBA] = [:]
        // The image's genuine main colours (this is what the percentages buy us).
        roles[PaletteRole.dominant.rawValue] = a.clusters.first?.color ?? tone(0, sat: satBase, val: v(0.62, 0.5))
        if let second = a.clusters.dropFirst().first {
            roles[PaletteRole.secondary.rawValue] = second.color
        } else {
            roles[PaletteRole.secondary.rawValue] = tone(0.166, sat: satBase * 0.9, val: v(0.58, 0.44))
        }
        // Relational tones from the hue.
        roles[PaletteRole.analogous.rawValue] = tone(0.083, sat: satBase * 0.9, val: v(0.54, 0.40))
        roles[PaletteRole.complementary.rawValue] = tone(0.5, sat: satBase * 0.85, val: v(0.64, 0.66))
        roles[PaletteRole.triadic.rawValue] = tone(0.333, sat: satBase * 0.85, val: v(0.60, 0.58))
        // Style decides where the accent and rail sit on the wheel. The rail /
        // large surfaces are darkened so the light rail ink stays legible, and
        // they shift with the style so switching palettes retints the chrome.
        roles[PaletteRole.accent.rawValue] = tone(style.accentOffset,
                                                  sat: min(0.94, max(0.62, satBase)), val: 0.88)
        roles[PaletteRole.surface.rawValue] = tone(style.surfaceOffset,
                                                   sat: min(0.58, max(0.30, satBase * 0.85)),
                                                   val: 0.20, alpha: 0.85)
        roles[PaletteRole.ink.rawValue] = RGBA(NSColor(hue: inkHue, saturation: inkSat,
                                                       brightness: inkVal, alpha: 1))
        roles[PaletteRole.inkDim.rawValue] = RGBA(NSColor(hue: inkHue, saturation: inkSat,
                                                          brightness: inkVal, alpha: 0.78))

        // Material-style tokens: tonal palettes from the image hue, then roles.
        // The primary hue honours the chosen scheme's accent offset. We build
        // both schemes so always-dark surfaces (the rail) can use the dark set.
        let tokenHue = (h + style.accentOffset).truncatingRemainder(dividingBy: 1)
        // Boost chroma so even muted photos yield a visible Material palette.
        let tokenChroma: CGFloat = (a.isNeutral || style.monochrome)
            ? 0 : max(0.80, min(1.0, CGFloat(a.saturation) * 3.0))
        let tokens = ColorTokens.make(hue: tokenHue, chroma: tokenChroma,
                                      dark: dark, monochrome: monochrome)
        let tokensDark = ColorTokens.make(hue: tokenHue, chroma: tokenChroma,
                                          dark: true, monochrome: monochrome)

        return BackgroundPalette(roles: roles, temperature: a.temperature,
                                 isLight: a.isLight, tokens: tokens, tokensDark: tokensDark)
    }
}

/// Persists the analysis of each background image, so palette styles can be
/// re-derived instantly.
enum PaletteStore {
    private static var url: URL {
        let fm = FileManager.default
        let dir = fm.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Mentat", isDirectory: true)
        try? fm.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir.appendingPathComponent("image-analysis.json")
    }

    static func load() -> [String: ImageAnalysis] {
        guard let data = try? Data(contentsOf: url),
              let map = try? JSONDecoder().decode([String: ImageAnalysis].self, from: data)
        else { return [:] }
        return map
    }
    static func save(_ map: [String: ImageAnalysis]) {
        guard let data = try? JSONEncoder().encode(map) else { return }
        try? data.write(to: url, options: .atomic)
    }
}
