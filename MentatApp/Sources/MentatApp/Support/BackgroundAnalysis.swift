import SwiftUI
import AppKit
import CoreImage

/// Artwork sampling: region averages, quiet-band detection, thumbnails and the
/// catalog. All memo state is lock-guarded and the sampling runs off-main.

enum BackgroundAnalysis {
    /// All memo state is guarded by `lock`; `NSImage`/`CIImage` are immutable to
    /// read, but the dictionaries are not. Sampling runs off-main, so the caches
    /// must be thread-safe.
    private static let lock = NSLock()
    nonisolated(unsafe) private static var thumbCache: [String: NSImage] = [:]
    /// One shared context — creating a `CIContext` per sample was a per-glyph hitch.
    /// `CIContext` is thread-safe, so it is shared across the sampling tasks too.
    private static let ciContext = CIContext(options: [.cacheIntermediates: false])
    /// Cache of the `CIImage` for each thumbnail, so sampling never re-decodes.
    nonisolated(unsafe) private static var ciCache: [String: CIImage] = [:]
    private static let cacheLimit = 160

    private static func ci(for image: NSImage, key: String) -> CIImage? {
        if key.isEmpty {
            guard let tiff = image.tiffRepresentation else { return nil }
            return CIImage(data: tiff)
        }
        lock.lock()
        if let c = ciCache[key] { lock.unlock(); return c }
        lock.unlock()
        guard let tiff = image.tiffRepresentation, let ci = CIImage(data: tiff) else { return nil }
        lock.lock()
        if ciCache.count >= cacheLimit { ciCache.removeAll(keepingCapacity: true) }
        ciCache[key] = ci
        lock.unlock()
        return ci
    }

    static func catalog() -> [String] {
        let urls = Bundle.main.urls(forResourcesWithExtension: "jpg", subdirectory: nil) ?? []
        let names = Set(
            urls.map { $0.deletingPathExtension().lastPathComponent }
                .filter { $0.hasPrefix("bg-") })
        // Read dimensions from ImageIO metadata (thread-safe, no decode) rather
        // than instantiating NSImage per file.
        return names.filter { name in
            guard let url = Bundle.main.url(forResource: name, withExtension: "jpg"),
                let src = CGImageSourceCreateWithURL(url as CFURL, nil),
                let props = CGImageSourceCopyPropertiesAtIndex(src, 0, nil) as? [CFString: Any],
                let w = (props[kCGImagePropertyPixelWidth] as? NSNumber)?.doubleValue,
                let h = (props[kCGImagePropertyPixelHeight] as? NSNumber)?.doubleValue,
                w > 1, h > 1
            else { return false }
            let aspect = w / h
            return aspect <= 2.4 && aspect >= 0.4
        }.sorted()
    }

    /// Small cached thumbnail for the gallery — decoding 80+ full-res images at
    /// once was why later tiles failed to appear/respond.
    static func thumb(_ name: String, max dim: CGFloat = 240) -> NSImage? {
        // Key by requested size: the engine samples a 512px thumb while the
        // gallery wants 240px, and sharing one entry would hand the wrong
        // resolution to one of them.
        let cacheKey = "\(name)|\(Int(dim))"
        lock.lock()
        if let c = thumbCache[cacheKey] { lock.unlock(); return c }
        lock.unlock()
        guard let img = NSImage(named: name) else { return nil }
        let s = img.size
        guard s.width > 0, s.height > 0 else { return nil }
        let scale = min(1, dim / max(s.width, s.height))
        let t = NSImage(size: NSSize(width: s.width * scale, height: s.height * scale))
        t.lockFocus()
        img.draw(in: NSRect(origin: .zero, size: t.size))
        t.unlockFocus()
        lock.lock()
        if thumbCache.count >= cacheLimit { thumbCache.removeAll(keepingCapacity: true) }
        thumbCache[cacheKey] = t
        lock.unlock()
        return t
    }

    /// Thread-safe downsample via ImageIO (no full decode, no AppKit drawing), so
    /// the gallery can build tiles off the main thread. `dim` is a point size;
    /// the pixel cap oversamples for Retina.
    static func fastThumb(_ name: String, max dim: CGFloat = 240) -> NSImage? {
        let cacheKey = "io|\(name)|\(Int(dim))"
        lock.lock()
        if let c = thumbCache[cacheKey] { lock.unlock(); return c }
        lock.unlock()
        guard let url = Bundle.main.url(forResource: name, withExtension: "jpg") else {
            return nil
        }
        let opts: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceShouldCacheImmediately: true,
            kCGImageSourceThumbnailMaxPixelSize: dim * 2,
        ]
        guard let src = CGImageSourceCreateWithURL(url as CFURL, nil),
            let cg = CGImageSourceCreateThumbnailAtIndex(src, 0, opts as CFDictionary)
        else { return nil }
        let img = NSImage(cgImage: cg, size: NSSize(width: cg.width, height: cg.height))
        lock.lock()
        if thumbCache.count >= cacheLimit { thumbCache.removeAll(keepingCapacity: true) }
        thumbCache[cacheKey] = img
        lock.unlock()
        return img
    }

    /// A device-RGB triple — `Sendable`, so sampling results can cross back from
    /// a background task without shipping `NSColor`.
    struct RGB: Sendable, Equatable {
        var r: CGFloat
        var g: CGFloat
        var b: CGFloat
        var nsColor: NSColor { NSColor(srgbRed: r, green: g, blue: b, alpha: 1) }
        static let mid = RGB(r: 0.5, g: 0.5, b: 0.5)
    }

    /// Average several normalized (top-origin) rects in one pass. Safe to call
    /// off the main thread — the caches are locked and the context is shared.
    static func regionAverages(
        _ image: NSImage, key: String,
        rects: [(x0: CGFloat, x1: CGFloat, y0: CGFloat, y1: CGFloat)]
    ) -> [RGB] {
        guard let ci = ci(for: image, key: key) else {
            return Array(repeating: .mid, count: rects.count)
        }
        let e = ci.extent
        return rects.map { r in
            let top = 1 - r.y1
            let rect = CGRect(
                x: e.minX + e.width * r.x0, y: e.minY + e.height * top,
                width: e.width * max(0.05, r.x1 - r.x0),
                height: e.height * max(0.05, r.y1 - r.y0))
            let crop = ci.cropped(to: rect)
            guard
                let f = CIFilter(
                    name: "CIAreaAverage",
                    parameters: [kCIInputImageKey: crop,
                                 kCIInputExtentKey: CIVector(cgRect: crop.extent)]),
                let out = f.outputImage
            else { return .mid }
            var px = [UInt8](repeating: 0, count: 4)
            ciContext.render(
                out, toBitmap: &px, rowBytes: 4,
                bounds: CGRect(x: 0, y: 0, width: 1, height: 1),
                format: .RGBA8, colorSpace: CGColorSpaceCreateDeviceRGB())
            return RGB(r: CGFloat(px[0]) / 255, g: CGFloat(px[1]) / 255, b: CGFloat(px[2]) / 255)
        }
    }

    static func averageColor(_ image: NSImage) -> NSColor {
        guard let ci = ci(for: image, key: "") else { return .darkGray }
        let e = ci.extent
        let band = ci.cropped(to: CGRect(x: e.minX, y: e.minY + e.height * 0.20,
                                         width: e.width, height: e.height * 0.60))
        guard let f = CIFilter(name: "CIAreaAverage",
                               parameters: [kCIInputImageKey: band,
                                            kCIInputExtentKey: CIVector(cgRect: band.extent)]),
              let out = f.outputImage else { return .darkGray }
        var px = [UInt8](repeating: 0, count: 4)
        ciContext.render(out, toBitmap: &px, rowBytes: 4,
                           bounds: CGRect(x: 0, y: 0, width: 1, height: 1),
                           format: .RGBA8, colorSpace: CGColorSpaceCreateDeviceRGB())
        return NSColor(red: CGFloat(px[0]) / 255, green: CGFloat(px[1]) / 255,
                       blue: CGFloat(px[2]) / 255, alpha: 1)
    }

    static func luminance(_ color: NSColor) -> CGFloat {
        let c = color.usingColorSpace(.deviceRGB) ?? .darkGray
        return 0.2126 * c.redComponent + 0.7152 * c.greenComponent + 0.0722 * c.blueComponent
    }

    /// Luminance as the user actually sees it: the photo is colour-graded per
    /// theme (contrast/grayscale), so sampling the raw image mispicks text on
    /// graded areas (e.g. white wordmark over a mono-boosted bright patch).
    static func gradedLuminance(_ color: NSColor, theme: AppTheme) -> CGFloat {
        let l = luminance(color)
        switch theme {
        case .mono: return min(1, max(0, 0.5 + (l - 0.5) * 1.45 + 0.02))
        case .hue: return min(1, max(0, 0.5 + (l - 0.5) * 1.12))
        }
    }

    /// Average colour of a horizontal band of the photo — so text and bubbles
    /// can adapt to the colour actually behind them (left vs right, etc.).
    ///
    /// `y0`/`y1` are measured from the **top** of the image (0 = top, 1 =
    /// bottom), matching every other coordinate in the app. Core Image's origin
    /// is bottom-left, so we flip here once — otherwise `bgTopColor` and the
    /// per-glyph wordmark sampling read the vertically-mirrored part of the art.
    static func regionAverage(_ image: NSImage, x0: CGFloat, x1: CGFloat,
                              y0: CGFloat = 0.28, y1: CGFloat = 0.72,
                              key: String = "") -> NSColor {
        guard let ci = ci(for: image, key: key) else { return .darkGray }
        let e = ci.extent
        let top = 1 - y1
        let rect = CGRect(x: e.minX + e.width * x0,
                          y: e.minY + e.height * top,
                          width: e.width * max(0.05, x1 - x0),
                          height: e.height * max(0.05, y1 - y0))
        let crop = ci.cropped(to: rect)
        guard let f = CIFilter(name: "CIAreaAverage",
                               parameters: [kCIInputImageKey: crop,
                                            kCIInputExtentKey: CIVector(cgRect: crop.extent)]),
              let out = f.outputImage else { return .darkGray }
        var px = [UInt8](repeating: 0, count: 4)
        ciContext.render(out, toBitmap: &px, rowBytes: 4,
                           bounds: CGRect(x: 0, y: 0, width: 1, height: 1),
                           format: .RGBA8, colorSpace: CGColorSpaceCreateDeviceRGB())
        return NSColor(red: CGFloat(px[0]) / 255, green: CGFloat(px[1]) / 255,
                       blue: CGFloat(px[2]) / 255, alpha: 1)
    }

    static func regionLuminance(_ image: NSImage, x0: CGFloat, x1: CGFloat) -> CGFloat {
        luminance(regionAverage(image, x0: x0, x1: x1))
    }

    /// Normalized y (top-origin) of the calmest horizontal band: the one whose
    /// left / centre / right thirds vary least, nudged away from mid-grey (which
    /// reads as muddy behind text). Used to pan the photo so a quiet region sits
    /// behind the wordmark.
    static func quietBandY(_ image: NSImage, key: String, theme: AppTheme,
                           bands: Int = 12) -> CGFloat {
        var bestY: CGFloat = 0.4
        var bestScore = CGFloat.greatestFiniteMagnitude
        for i in 0..<max(1, bands) {
            let y0 = CGFloat(i) / CGFloat(bands)
            let y1 = CGFloat(i + 1) / CGFloat(bands)
            let l = regionAverage(image, x0: 0.03, x1: 0.34, y0: y0, y1: y1, key: key)
            let c = regionAverage(image, x0: 0.33, x1: 0.67, y0: y0, y1: y1, key: key)
            let r = regionAverage(image, x0: 0.66, x1: 0.97, y0: y0, y1: y1, key: key)
            let ls = [l, c, r].map { gradedLuminance($0, theme: theme) }
            let spread = (ls.max() ?? 0) - (ls.min() ?? 0)
            let mean = ls.reduce(0, +) / 3
            let midPenalty = 1 - min(1, abs(mean - 0.5) * 2)   // 0 at black/white, 1 at grey
            let score = spread + 0.35 * midPenalty
            if score < bestScore { bestScore = score; bestY = (y0 + y1) / 2 }
        }
        return bestY
    }

    /// The vertical pan applied to a `scaledToFill` photo so its quiet band sits
    /// behind the wordmark — shared by the background view and the region
    /// sampling, so adaptive text tracks the same pixels the eye sees.
    static func panY(frameH: CGFloat, dispH: CGFloat, quietY: CGFloat,
                     anchor: CGFloat = 0.40) -> CGFloat {
        let overflow = max(0, dispH - frameH)
        guard overflow > 0.5 else { return 0 }
        let desired = anchor * frameH - (frameH - dispH) / 2 - quietY * dispH
        return min(overflow / 2, max(-overflow / 2, desired))
    }

    /// `quietBandY` memoized per (image, theme) so a background switch only pays
    /// the 36-sample scan once. Locked, so it can be computed off-main.
    nonisolated(unsafe) private static var quietCache: [String: CGFloat] = [:]
    static func cachedQuietBandY(_ image: NSImage, key: String, theme: AppTheme) -> CGFloat {
        let ck = "\(key)|\(theme)"
        lock.lock()
        if let v = quietCache[ck] { lock.unlock(); return v }
        lock.unlock()
        let v = quietBandY(image, key: key, theme: theme)
        lock.lock()
        if quietCache.count >= 64 { quietCache.removeAll(keepingCapacity: true) }
        quietCache[ck] = v
        lock.unlock()
        return v
    }

    /// The three text regions plus the top-bar band, mapped from view space to
    /// the visible part of the aspect-filled, quiet-band-panned photo. Pure math,
    /// so the caller can build the rects on any thread and sample them off-main.
    static func regionRects(
        content: CGSize, image: CGSize, quietY: CGFloat
    ) -> [(x0: CGFloat, x1: CGFloat, y0: CGFloat, y1: CGFloat)] {
        let iw = image.width
        let ih = image.height
        let W = content.width
        let H = content.height
        func visible(_ x0: CGFloat, _ x1: CGFloat, _ y0: CGFloat, _ y1: CGFloat)
            -> (CGFloat, CGFloat, CGFloat, CGFloat)
        {
            guard iw > 1, ih > 1, W > 1, H > 1 else { return (x0, x1, y0, y1) }
            let scale = max(W / iw, H / ih)
            let dw = iw * scale
            let dh = ih * scale
            let ox = (dw - W) / 2
            let oy = (dh - H) / 2
            let pan = panY(frameH: H, dispH: dh, quietY: quietY)
            func cx(_ t: CGFloat) -> CGFloat { min(1, max(0, (t * W + ox) / dw)) }
            func cy(_ t: CGFloat) -> CGFloat { min(1, max(0, (t * H + oy + pan) / dh)) }
            return (cx(x0), cx(x1), cy(y0), cy(y1))
        }
        func band(_ x0: CGFloat, _ x1: CGFloat, _ y0: CGFloat, _ y1: CGFloat)
            -> (x0: CGFloat, x1: CGFloat, y0: CGFloat, y1: CGFloat)
        {
            let v = visible(x0, x1, y0, y1)
            return (v.0, max(v.0 + 0.03, v.1), v.2, max(v.2 + 0.03, v.3))
        }
        return [
            band(0.00, 0.40, 0.22, 0.78),
            band(0.32, 0.68, 0.22, 0.78),
            band(0.60, 1.00, 0.22, 0.78),
            band(0.24, 0.76, 0.00, 0.14),
        ]
    }

    /// Fine grid of brightness + variance, so a bubble can gauge exactly how
    /// "powerful"/busy the photo is behind it (bottom-up rows, like the bitmap).
    static func grid(_ image: NSImage, cols: Int = 6, rows: Int = 8,
                     contrastBoost: CGFloat = 1) -> [[BgCell]] {
        let cell = 22
        let w = cols * cell, h = rows * cell
        guard let rep = NSBitmapImageRep(
            bitmapDataPlanes: nil, pixelsWide: w, pixelsHigh: h,
            bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
            colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0) else { return [] }
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
        image.draw(in: NSRect(x: 0, y: 0, width: w, height: h),
                   from: .zero, operation: .copy, fraction: 1)
        NSGraphicsContext.restoreGraphicsState()
        guard let data = rep.bitmapData else { return [] }
        let bpr = rep.bytesPerRow
        var cells = [[BgCell]](repeating: [BgCell](repeating: BgCell(lum: 0.4, variance: 0), count: cols),
                               count: rows)
        for cy in 0..<rows {
            for cx in 0..<cols {
                var sum = 0.0, sum2 = 0.0, n = 0.0
                for y in (cy * cell)..<((cy + 1) * cell) {
                    for x in (cx * cell)..<((cx + 1) * cell) {
                        let p = data + y * bpr + x * 4
                        let l = 0.2126 * Double(p[0]) / 255 + 0.7152 * Double(p[1]) / 255
                            + 0.0722 * Double(p[2]) / 255
                        sum += l; sum2 += l * l; n += 1
                    }
                }
                let mean = sum / n
                let v = max(0, sum2 / n - mean * mean) * Double(contrastBoost)
                cells[cy][cx] = BgCell(lum: CGFloat(mean), variance: CGFloat(v))
            }
        }
        return cells
    }

    /// A *cohesive* tint: a neighbouring hue in the art's own temperature family,
    /// kept low-saturation and deep so a surface belongs to the photograph. Greys
    /// fall back to a neutral tone so no phantom hue appears.
    static func analogousTint(from color: NSColor, isLight: Bool) -> Color {
        guard ColorTheory.temperature(color) != .neutral else {
            return Color(white: isLight ? 0.34 : 0.12, opacity: isLight ? 0.78 : 0.70)
        }
        let (_, s, _) = ColorTheory.hsb(color)
        let hue = ColorTheory.adjacentHue(color)
        let sat = min(0.52, max(0.22, s * 0.95))
        return Color(hue: hue, saturation: sat,
                     brightness: isLight ? 0.50 : 0.20,
                     opacity: isLight ? 0.74 : 0.68)
    }

    /// A *contrasting* tint: the opposite temperature to the art, so accents and
    /// floating chrome pop against it without leaving the same value range.
    static func complementaryTint(from color: NSColor, isLight: Bool) -> Color {
        guard ColorTheory.temperature(color) != .neutral else {
            return Color(white: isLight ? 0.28 : 0.88, opacity: 0.26)
        }
        let (_, s, _) = ColorTheory.hsb(color)
        let hue = ColorTheory.contrastingHue(color)
        let sat = min(0.44, max(0.18, s * 0.75))
        return Color(hue: hue, saturation: sat, brightness: isLight ? 0.70 : 0.86,
                     opacity: isLight ? 0.30 : 0.24)
    }
}
