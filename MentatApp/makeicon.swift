// Renders Mentat.app's icon (desert glass + eye sigil) into AppIcon.icns.
// Run: swift makeicon.swift
import AppKit

let outDir = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
    .appendingPathComponent("AppIcon.iconset")
try? FileManager.default.removeItem(at: outDir)
try! FileManager.default.createDirectory(at: outDir, withIntermediateDirectories: true)

let gold = NSColor(calibratedRed: 0.98, green: 0.82, blue: 0.52, alpha: 1)
let spiceGlow = NSColor(calibratedRed: 0.95, green: 0.62, blue: 0.30, alpha: 0.75)

func render(_ px: Int) -> Data {
    let rep = NSBitmapImageRep(
        bitmapDataPlanes: nil, pixelsWide: px, pixelsHigh: px,
        bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
        colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)

    let f = CGFloat(px)
    let inset = f * 0.055
    let rect = NSRect(x: inset, y: inset, width: f - 2 * inset, height: f - 2 * inset)
    let path = NSBezierPath(roundedRect: rect, xRadius: f * 0.225, yRadius: f * 0.225)

    NSGradient(colors: [
        NSColor(calibratedRed: 0.62, green: 0.33, blue: 0.16, alpha: 1),
        NSColor(calibratedRed: 0.24, green: 0.14, blue: 0.08, alpha: 1),
        NSColor(calibratedRed: 0.13, green: 0.08, blue: 0.05, alpha: 1),
    ])!.draw(in: path, angle: -68)

    // warm dune glow rising from below
    NSGraphicsContext.saveGraphicsState()
    path.addClip()
    let glowRect = NSRect(x: inset - f * 0.1, y: -f * 0.35, width: f * 1.2, height: f * 1.0)
    NSGradient(colors: [spiceGlow, spiceGlow.withAlphaComponent(0.0)])?
        .draw(in: glowRect, relativeCenterPosition: NSPoint(x: 0, y: 0))
    NSGraphicsContext.restoreGraphicsState()

    // glassy top highlight
    NSGraphicsContext.saveGraphicsState()
    path.addClip()
    NSGradient(colors: [NSColor.white.withAlphaComponent(0.22), NSColor.white.withAlphaComponent(0.0)])?
        .draw(in: NSRect(x: inset, y: f * 0.5, width: f, height: f * 0.5), angle: -90)
    NSGraphicsContext.restoreGraphicsState()

    // eye sigil
    if let sym = NSImage(systemSymbolName: "eye.fill", accessibilityDescription: nil) {
        let sizeCfg = NSImage.SymbolConfiguration(pointSize: f * 0.5, weight: .regular)
        let colorCfg = NSImage.SymbolConfiguration(paletteColors: [gold])
        if let s = sym.withSymbolConfiguration(sizeCfg.applying(colorCfg)) {
            let sz = s.size
            let scale = min(f * 0.60 / sz.width, f * 0.60 / sz.height)
            let w = sz.width * scale, h = sz.height * scale
            s.draw(in: NSRect(x: (f - w) / 2, y: (f - h) / 2, width: w, height: h),
                   from: .zero, operation: .sourceOver, fraction: 1)
        }
    }

    // fine rim
    NSColor.white.withAlphaComponent(0.14).setStroke()
    path.lineWidth = max(1, f * 0.006)
    path.stroke()

    NSGraphicsContext.restoreGraphicsState()
    return rep.representation(using: .png, properties: [:])!
}

let specs: [(Int, String)] = [
    (16, "icon_16x16.png"), (32, "icon_16x16@2x.png"),
    (32, "icon_32x32.png"), (64, "icon_32x32@2x.png"),
    (128, "icon_128x128.png"), (256, "icon_128x128@2x.png"),
    (256, "icon_256x256.png"), (512, "icon_256x256@2x.png"),
    (512, "icon_512x512.png"), (1024, "icon_512x512@2x.png"),
]
for (px, name) in specs {
    try! render(px).write(to: outDir.appendingPathComponent(name))
}

let proc = Process()
proc.executableURL = URL(fileURLWithPath: "/usr/bin/iconutil")
proc.arguments = ["-c", "icns", outDir.path, "-o", "AppIcon.icns"]
try! proc.run()
proc.waitUntilExit()
try? FileManager.default.removeItem(at: outDir)
print("wrote AppIcon.icns")
