import AppKit

/// An image reduced to perceptual colour: dominant OKLCH clusters plus a global
/// hue / chroma / lightness, so a theme can be built from it. Pure (no state).
struct ImagePalette: Equatable, Sendable {
    struct Cluster: Equatable, Sendable {
        var color: ColorScience.OKLCH
        var weight: Double
    }

    var clusters: [Cluster]
    var baseHue: Double  // 0…360
    var meanChroma: Double
    var meanLightness: Double
    var isLight: Bool
    var isNeutral: Bool

    static let neutral = ImagePalette(
        clusters: [], baseHue: 0, meanChroma: 0,
        meanLightness: 0.5, isLight: false, isNeutral: true)
}

/// Samples an image and quantizes it into its main OKLCH colours.
enum ImageAnalyzer {
    static func analyze(_ image: NSImage, side: Int = 56) -> ImagePalette {
        guard let px = pixels(image, side: side) else { return .neutral }
        return quantize(px, side: side)
    }

    /// Quantize a raw RGBA buffer into an `ImagePalette`. Pure (no shared state),
    /// so it is safe to run off the main thread.
    static func quantize(_ px: [UInt8], side: Int = 56) -> ImagePalette {
        struct Bucket { var r = 0.0, g = 0.0, b = 0.0, n = 0.0 }
        let levels = 6
        var buckets: [Int: Bucket] = [:]
        var sampled = 0.0
        for i in stride(from: 0, to: px.count, by: 4) {
            if Double(px[i + 3]) / 255 < 0.5 { continue }
            let r = Double(px[i]) / 255
            let g = Double(px[i + 1]) / 255
            let b = Double(px[i + 2]) / 255
            let key =
                (min(levels - 1, Int(r * Double(levels))) * levels
                    + min(levels - 1, Int(g * Double(levels)))) * levels
                + min(levels - 1, Int(b * Double(levels)))
            var bk = buckets[key] ?? Bucket()
            bk.r += r
            bk.g += g
            bk.b += b
            bk.n += 1
            buckets[key] = bk
            sampled += 1
        }
        guard sampled > 0 else { return .neutral }

        var items: [(ColorScience.OKLCH, Double)] = buckets.values.map {
            (ColorScience.oklch(r: $0.r / $0.n, g: $0.g / $0.n, b: $0.b / $0.n), $0.n)
        }
        items.sort { $0.1 > $1.1 }

        // Merge nearby colours (in OKLab) into clusters.
        var merged: [(ColorScience.OKLCH, Double)] = []
        for (colour, n) in items {
            let lab = labComponents(colour)
            if let i = merged.firstIndex(where: { far(labComponents($0.0), lab) < 0.06 }) {
                let total = merged[i].1 + n
                merged[i].0 = ColorScience.mix(merged[i].0, colour, n / total)
                merged[i].1 = total
            } else {
                merged.append((colour, n))
            }
        }
        merged.sort { $0.1 > $1.1 }
        let top = Array(merged.prefix(7))
        let total = max(1, merged.reduce(0) { $0 + $1.1 })
        let clusters = top.map { ImagePalette.Cluster(color: $0.0, weight: $0.1 / total) }

        var lSum = 0.0
        var cSum = 0.0
        var wSum = 0.0
        var hueSin = 0.0
        var hueCos = 0.0
        for c in clusters {
            lSum += c.color.l * c.weight
            cSum += c.color.c * c.weight
            let w = c.weight * max(0.05, c.color.c)
            wSum += w
            hueSin += sin(c.color.h * .pi / 180) * w
            hueCos += cos(c.color.h * .pi / 180) * w
        }
        var hue = atan2(hueSin, hueCos) * 180 / .pi
        if hue < 0 { hue += 360 }
        let isNeutral = cSum < 0.04

        return ImagePalette(
            clusters: clusters,
            baseHue: isNeutral ? 0 : hue,
            meanChroma: cSum,
            meanLightness: lSum,
            isLight: lSum >= 0.6,
            isNeutral: isNeutral)
    }

    // MARK: helpers

    private static func labComponents(_ c: ColorScience.OKLCH) -> (Double, Double, Double) {
        let hr = c.h * .pi / 180
        return (c.l, c.c * cos(hr), c.c * sin(hr))
    }
    private static func far(_ a: (Double, Double, Double), _ b: (Double, Double, Double)) -> Double
    {
        let dl = a.0 - b.0
        let da = a.1 - b.1
        let db = a.2 - b.2
        return (dl * dl + da * da + db * db).squareRoot()
    }

    static func pixels(_ image: NSImage, side: Int) -> [UInt8]? {
        guard let cg = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
            return nil
        }
        var buf = [UInt8](repeating: 0, count: side * side * 4)
        let cs = CGColorSpaceCreateDeviceRGB()
        let info = CGImageAlphaInfo.premultipliedLast.rawValue
        buf.withUnsafeMutableBytes { raw in
            if let ctx = CGContext(
                data: raw.baseAddress, width: side, height: side,
                bitsPerComponent: 8, bytesPerRow: side * 4,
                space: cs, bitmapInfo: info)
            {
                ctx.interpolationQuality = .medium
                ctx.draw(cg, in: CGRect(x: 0, y: 0, width: side, height: side))
            }
        }
        return buf
    }
}
