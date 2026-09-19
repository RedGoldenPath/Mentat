import AppKit
import SwiftUI

/// Perceptual colour science: sRGB ↔ linear ↔ OKLab ↔ OKLCH, gamut mapping, and
/// WCAG contrast. Pure and dependency-free so the colour system is testable.
enum ColorScience {

    // MARK: - OKLCH

    /// A perceptual colour: lightness 0…1, chroma ≥ 0, hue 0…360.
    struct OKLCH: Equatable, Sendable {
        var l: Double
        var c: Double
        var h: Double

        var nsColor: NSColor { ColorScience.nsColor(self) }
        var color: Color { Color(nsColor: nsColor) }

        static func rgba(_ r: Double, _ g: Double, _ b: Double) -> OKLCH {
            ColorScience.oklch(r: r, g: g, b: b)
        }
    }

    // MARK: - sRGB transfer

    static func linearized(_ c: Double) -> Double {
        c <= 0.04045 ? c / 12.92 : pow((c + 0.055) / 1.055, 2.4)
    }
    static func gamma(_ c: Double) -> Double {
        c <= 0.0031308 ? 12.92 * c : 1.055 * pow(c, 1.0 / 2.4) - 0.055
    }

    // MARK: - conversions

    /// sRGB (0…1) → OKLCH.
    static func oklch(r: Double, g: Double, b: Double) -> OKLCH {
        let lr = linearized(r)
        let lg = linearized(g)
        let lb = linearized(b)
        let l = 0.4122214708 * lr + 0.5363325363 * lg + 0.0514459929 * lb
        let m = 0.2119034982 * lr + 0.6806995451 * lg + 0.1073969566 * lb
        let s = 0.0883024619 * lr + 0.2817188376 * lg + 0.6299787005 * lb
        let l_ = cbrt(l)
        let m_ = cbrt(m)
        let s_ = cbrt(s)
        let L = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
        let a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
        let bb = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
        let chroma = (a * a + bb * bb).squareRoot()
        var hue = atan2(bb, a) * 180 / .pi
        if hue < 0 { hue += 360 }
        return OKLCH(l: clamp01(L), c: max(0, chroma), h: hue)
    }

    static func oklch(_ ns: NSColor) -> OKLCH {
        let c = ns.usingColorSpace(.sRGB) ?? NSColor(white: 0.5, alpha: 1)
        return oklch(
            r: Double(c.redComponent), g: Double(c.greenComponent), b: Double(c.blueComponent))
    }

    /// OKLCH → linear sRGB (may fall outside [0,1]; use `nsColor` for gamut-mapped).
    static func linearSRGB(_ c: OKLCH) -> (r: Double, g: Double, b: Double) {
        let hr = c.h * .pi / 180
        let a = c.c * cos(hr)
        let b = c.c * sin(hr)
        let l_ = c.l + 0.3963377774 * a + 0.2158037573 * b
        let m_ = c.l - 0.1055613458 * a - 0.0638541728 * b
        let s_ = c.l - 0.0894841775 * a - 1.2914855480 * b
        let l = l_ * l_ * l_
        let m = m_ * m_ * m_
        let s = s_ * s_ * s_
        return (
            r: 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
            g: -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
            b: -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s
        )
    }

    static func inGamut(_ c: OKLCH, tolerance: Double = 0.0005) -> Bool {
        let rgb = linearSRGB(c)
        let lo = 0.0 - tolerance
        let hi = 1.0 + tolerance
        return rgb.r >= lo && rgb.r <= hi && rgb.g >= lo && rgb.g <= hi && rgb.b >= lo
            && rgb.b <= hi
    }

    /// Map into sRGB by reducing chroma while holding L and H (the perceptual,
    /// hue-preserving gamut map).
    static func gamutMapped(_ c: OKLCH) -> OKLCH {
        if inGamut(c) { return c }
        var lo = 0.0
        var hi = c.c
        for _ in 0..<24 {
            let mid = (lo + hi) / 2
            if inGamut(OKLCH(l: c.l, c: mid, h: c.h)) { lo = mid } else { hi = mid }
        }
        return OKLCH(l: c.l, c: lo, h: c.h)
    }

    static func nsColor(_ c: OKLCH, alpha: Double = 1) -> NSColor {
        let mapped = gamutMapped(c)
        let s = linearSRGB(mapped)
        return NSColor(
            srgbRed: clamp01(gamma(s.r)), green: clamp01(gamma(s.g)),
            blue: clamp01(gamma(s.b)), alpha: alpha)
    }

    static func color(_ c: OKLCH, alpha: Double = 1) -> Color {
        Color(nsColor: nsColor(c, alpha: alpha))
    }

    // MARK: - WCAG

    /// WCAG relative luminance of an sRGB colour.
    static func relativeLuminance(_ ns: NSColor) -> Double {
        let c = ns.usingColorSpace(.sRGB) ?? NSColor(white: 0.5, alpha: 1)
        let r = linearized(Double(c.redComponent))
        let g = linearized(Double(c.greenComponent))
        let b = linearized(Double(c.blueComponent))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    }

    /// WCAG contrast ratio (1…21).
    static func contrast(_ a: NSColor, _ b: NSColor) -> Double {
        let la = relativeLuminance(a)
        let lb = relativeLuminance(b)
        let hi = max(la, lb)
        let lo = min(la, lb)
        return (hi + 0.05) / (lo + 0.05)
    }

    static func contrast(_ a: OKLCH, _ b: OKLCH) -> Double {
        contrast(nsColor(a), nsColor(b))
    }

    enum Level: Double {
        case body = 4.5  // normal text
        case large = 3.0  // large text / UI components
        case decorative = 0  // no requirement
    }

    /// Push `fg` toward black or white until it clears `level` against `bg`.
    /// Hue/chroma are preserved; only lightness moves. Picks the *least* movement
    /// that clears the bar, so the colour still reads as itself.
    static func enforce(_ fg: OKLCH, on bg: OKLCH, level: Level = .body) -> OKLCH {
        guard level != .decorative else { return fg }
        if contrast(fg, bg) >= level.rawValue { return fg }

        var best: OKLCH?
        var bestRatio = Double.greatestFiniteMagnitude
        for direction in [1.0, -1.0] {
            var l = fg.l
            while true {
                l += direction * 0.02
                if l < 0 || l > 1 { break }
                let candidate = OKLCH(l: l, c: fg.c, h: fg.h)
                let ratio = contrast(candidate, bg)
                if ratio >= level.rawValue {
                    if ratio < bestRatio {
                        best = candidate
                        bestRatio = ratio
                    }
                    break
                }
            }
        }
        if let best { return best }

        // Fall back to pure black/white for guaranteed legibility.
        let white = OKLCH(l: 1, c: 0, h: fg.h)
        let black = OKLCH(l: 0, c: 0, h: fg.h)
        return contrast(white, bg) >= contrast(black, bg) ? white : black
    }

    // MARK: - helpers

    static func clamp01(_ v: Double) -> Double { min(1, max(0, v)) }

    /// Perceptual mix in OKLCH (linear in L and C, shortest hue path).
    static func mix(_ a: OKLCH, _ b: OKLCH, _ t: Double) -> OKLCH {
        let t = clamp01(t)
        var dh = b.h - a.h
        if dh > 180 { dh -= 360 }
        if dh < -180 { dh += 360 }
        var h = a.h + dh * t
        if h < 0 { h += 360 }
        return OKLCH(
            l: a.l + (b.l - a.l) * t,
            c: a.c + (b.c - a.c) * t,
            h: h.truncatingRemainder(dividingBy: 360))
    }

    /// Rotate hue by degrees.
    static func rotate(_ c: OKLCH, _ degrees: Double) -> OKLCH {
        var h = (c.h + degrees).truncatingRemainder(dividingBy: 360)
        if h < 0 { h += 360 }
        return OKLCH(l: c.l, c: c.c, h: h)
    }
}
