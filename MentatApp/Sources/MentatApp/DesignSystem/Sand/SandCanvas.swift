import AppKit
import Metal
import MetalKit
import QuartzCore
import SandCore
import SwiftUI

/// The sand surface. Renders the **GPU fluid** (MetalKit) when available,
/// otherwise a lightweight Canvas approximation so dev builds and tests never
/// go blank. The fluid is always alive and swirls around the pointer.
///
/// Cadence: 120 fps while interacting, 60 fps at rest (always smooth), and
/// half-resolution while the local brain is generating (so inference keeps the
/// GPU). There is no hard 120↔30 flip.
struct SandCanvas: View {
    var style: SandStyle = .sand
    var store: SandMotionStore? = nil
    /// The local engine is generating — degrade so inference owns the GPU.
    var busy: Bool = false
    var motion: SandMotion = .rest

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.scenePhase) private var scenePhase
    @State private var lowPower = ProcessInfo.processInfo.isLowPowerModeEnabled

    var body: some View {
        let paused = reduceMotion || scenePhase != .active || lowPower
        let active = (store?.isActive ?? false) && !busy
        Group {
            if SandPipeline.metalAvailable {
                SandMetalView(style: style, store: store, busy: busy,
                              active: active, paused: paused)
            } else {
                SandFallbackLayer(style: style, store: store, staticMotion: motion,
                                  active: active, paused: paused)
            }
        }
        .ignoresSafeArea()
        .allowsHitTesting(false)
        .onReceive(NotificationCenter.default.publisher(
            for: .NSProcessInfoPowerStateDidChange)) { _ in
            lowPower = ProcessInfo.processInfo.isLowPowerModeEnabled
        }
    }
}

// MARK: - Metal backend

private struct SandMetalView: NSViewRepresentable {
    var style: SandStyle
    var store: SandMotionStore?
    var busy: Bool
    var active: Bool
    var paused: Bool

    func makeCoordinator() -> Coordinator { Coordinator() }

    /// Polled every frame by the pipeline, so UI-event motion is read at display
    /// rate rather than on SwiftUI updates.
    private func provider() -> @MainActor () -> SandInputs {
        let store = self.store
        let busy = self.busy
        return {
            var i = SandInputs()
            i.renderScale = busy ? 0.5 : 1.0
            if let s = store {
                i.pointer = s.pointer
                i.hasPointer = s.hasPointer
                i.obstacleRects = s.solids()
                // No pointer-driven parallax/lean — the light is not tied to the mouse.
                i.parallax = .zero
                i.pointerVelocity = s.pointerVelocity
                // The couplings used to be computed but never sent — now they
                // drive the renderer (forces, not walls; gust; breath).
                let m = s.motion()
                i.force = SIMD2(Float(m.shift.width), Float(m.shift.height)) * 0.006
                i.shear = Float(m.shear) * 0.4
                i.gust = Float(m.gust) * 0.5
                i.breath = Float(m.breath)
                i.pulse = Float(m.pulse)
            }
            return i
        }
    }

    func makeNSView(context: Context) -> MTKView {
        let view = MTKView()
        view.device = MTLCreateSystemDefaultDevice()
        view.colorPixelFormat = .bgra8Unorm
        view.framebufferOnly = true
        view.isPaused = false
        view.enableSetNeedsDisplay = false
        view.autoResizeDrawable = true
        view.preferredFramesPerSecond = 60
        view.clearColor = MTLClearColor(red: 0, green: 0, blue: 0, alpha: 1)
        if let device = view.device, let renderer = SandPipeline(device: device) {
            context.coordinator.renderer = renderer
            renderer.config = style.config
            renderer.inputsProvider = provider()
            view.delegate = renderer
        }
        return view
    }

    func updateNSView(_ view: MTKView, context: Context) {
        guard let renderer = context.coordinator.renderer else { return }
        renderer.config = style.config
        renderer.inputsProvider = provider()
        view.preferredFramesPerSecond = active ? 120 : 60   // 120 while interacting, 60 at rest
        view.isPaused = paused
    }

    final class Coordinator {
        var renderer: SandPipeline?
    }
}

// MARK: - Canvas fallback (no Metal toolchain / shader library)

/// A hand-drawn approximation of the live fluid: two travelling amber masses,
/// drifting grain, and the centre scrim. Not as rich as the Metal path, but
/// alive and honest.
private struct SandFallbackLayer: View {
    var style: SandStyle
    var store: SandMotionStore?
    var staticMotion: SandMotion
    var active: Bool
    var paused: Bool

    @State private var start = Date()

    private func cadence() -> Double { (active ? 1.0 / 120.0 : 1.0 / 60.0) }

    var body: some View {
        TimelineView(.animation(minimumInterval: cadence(), paused: paused)) { ctx in
            Canvas { g, size in
                let rect = CGRect(origin: .zero, size: size)
                let t = ctx.date.timeIntervalSince(start)
                g.fill(Path(rect), with: .color(.black))

                // A cone of light from a point above the top edge (rough).
                let col = style.shaftColor
                let drift = sin(t * style.shaftDrift * 6) * 0.01
                let src = CGPoint(x: size.width * (style.shaftX + drift),
                                  y: size.height * style.shaftY)
                let reach = max(size.width, size.height) * 0.35
                g.fill(Path(rect), with: .radialGradient(
                    Gradient(colors: [col.opacity(0.55 * style.shaftSourceGlow), col.opacity(0)]),
                    center: src, startRadius: 0, endRadius: reach))
                let half = style.shaftSpread * .pi / 180
                let len = max(size.width, size.height) * 2.2
                let dx = sin(half) * len
                var cone = Path()
                cone.move(to: src)
                cone.addLine(to: CGPoint(x: src.x - dx, y: src.y + cos(half) * len))
                cone.addLine(to: CGPoint(x: src.x + dx, y: src.y + cos(half) * len))
                cone.closeSubpath()
                g.fill(cone, with: .linearGradient(
                    Gradient(colors: [col.opacity(0.30 * style.shaftStrength), col.opacity(0)]),
                    startPoint: src, endPoint: CGPoint(x: src.x, y: src.y + len)))

                // Dust motes.
                let count = min(Int(max(0, style.dustCount)), 2000)
                for i in 0..<count {
                    let fi = Double(i)
                    let hx = abs((sin(fi * 12.9898) * 43758.5453).truncatingRemainder(dividingBy: 1))
                    let hy = abs((sin(fi * 78.233) * 12345.6789).truncatingRemainder(dividingBy: 1))
                    let y = (hy + t * 0.004 * (0.5 + hx)).truncatingRemainder(dividingBy: 1)
                    let rr = 0.5 + 1.6 * hy
                    g.fill(Path(ellipseIn: CGRect(x: hx * size.width, y: y * size.height,
                                                  width: rr, height: rr)),
                           with: .color(col.opacity(0.22 * style.dustBrightness)))
                }
            }
        }
    }
}

private extension Color {
    /// Blend toward `other` by `fraction` (0…1) in sRGB.
    func blended(with other: Color, fraction: Double) -> Color? {
        guard let a = NSColor(self).usingColorSpace(.deviceRGB),
              let b = NSColor(other).usingColorSpace(.deviceRGB)
        else { return nil }
        let f = CGFloat(min(1, max(0, fraction)))
        return Color(
            red: Double(a.redComponent + (b.redComponent - a.redComponent) * f),
            green: Double(a.greenComponent + (b.greenComponent - a.greenComponent) * f),
            blue: Double(a.blueComponent + (b.blueComponent - a.blueComponent) * f))
    }
}

/// Cached white-noise tile for the Canvas fallback's grain.
enum SandGrain {
    static let tile: CGImage? = {
        let side = 512
        guard
            let rep = NSBitmapImageRep(
                bitmapDataPlanes: nil, pixelsWide: side, pixelsHigh: side,
                bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0),
            let data = rep.bitmapData
        else { return nil }
        var rng = SystemRandomNumberGenerator()
        for i in stride(from: 0, to: side * side * 4, by: 4) {
            data[i] = 255; data[i + 1] = 255; data[i + 2] = 255
            data[i + 3] = UInt8(Double.random(in: 0...1, using: &rng) * 255)
        }
        return rep.cgImage
    }()
}
