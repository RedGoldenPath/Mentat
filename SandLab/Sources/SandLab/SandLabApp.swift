import AppKit
import Combine
import MetalKit
import SandCore
import SwiftUI

@main
struct SandLabApp: App {
    var body: some Scene {
        WindowGroup("Sand Lab") {
            LabView()
        }
        .windowStyle(.hiddenTitleBar)
        .defaultSize(width: 1480, height: 920)
    }
}

final class RendererBox: ObservableObject {
    weak var pipeline: SandPipeline?
}

struct LabView: View {
    @StateObject private var box = RendererBox()
    @State private var cfg = SandLabSettings.load() ?? SandConfig()
    @State private var fps = 0.0
    @State private var testRectOn = true
    @State private var testRectX = 0.5
    @State private var showAdvanced = false
    private let fpsTimer = Timer.publish(every: 0.5, on: .main, in: .common).autoconnect()

    private var obstacles: [SIMD4<Float>] {
        testRectOn ? [SIMD4(Float(testRectX) - 0.05, 0.30, 0.10, 0.40)] : []
    }

    var body: some View {
        HStack(spacing: 0) {
            ZStack {
                MetalSandView(config: cfg, obstacles: obstacles, box: box)
                VStack {
                    Spacer()
                    HStack {
                        Text(String(format: "%.0f fps", fps))
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundStyle(.white.opacity(0.5))
                        Spacer()
                    }
                }
                .padding(16)
            }
            .frame(minWidth: 860)

            controls.frame(width: 360).background(.ultraThinMaterial)
        }
        .frame(minWidth: 1240, minHeight: 740)
        .preferredColorScheme(.dark)
        .onReceive(fpsTimer) { _ in
            fps = box.pipeline?.fps ?? 0
            box.pipeline?.inputs.gust *= 0.5   // let a test gust decay
        }
        .onChange(of: cfg) { _, c in SandLabSettings.save(c) }
        .onAppear { SandLabSettings.save(cfg) }   // write current values so they exist to read
    }

    private var controls: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                Text("Sand Lab").font(.title2).bold()
                Text("Dust and light, live. Every knob is the real engine.")
                    .font(.caption).foregroundStyle(.secondary)

                group("Presets") {
                    HStack(spacing: 6) {
                        presetButton("Still") { cfg = .still }
                        presetButton("Wander") { cfg = .wander }
                        presetButton("Breezy") { cfg = .breezy }
                        presetButton("Elegant") { cfg = .sand }
                    }
                }

                // ── CORE ──────────────────────────────────────────────────
                group("Light") {
                    s("Brightness", $cfg.shaftStrength, 0...4, "How bright the beams are.")
                    s("Fan width", $cfg.shaftSpread, 5...90, "%.0f", "How wide the spread of beams is.")
                    s("Cloud scale", $cfg.volScale, 0.5...8, "%.1f", "How many beams — small value = big beams, high = many small.")
                    s("Beam churn", $cfg.volDrift, 0...0.2, "%.3f", "How quickly beams are born and dissolve.")
                    s("Big ↔ small mix", $cfg.shaftVary, 0...1, "%.2f", "0 = all small and sharp, 1 = all big and soft.")
                    s("Distance fade", $cfg.shaftFalloff, 0...4, "How fast the beams fade out.")
                    s("Glow at the source", $cfg.shaftSourceGlow, 0...4, "Bright core where the beams come from.")
                }
                group("Movement") {
                    s("Sway (source)", $cfg.lightSway, 0...1, "How much the light source itself sways.")
                    s("Flicker", $cfg.beamFlutter, 0...1, "How much individual beams flicker.")
                    s("Flicker speed", $cfg.beamFlutterSpeed, 0...3, "How fast the flicker is.")
                    s("Wind strength", $cfg.gustAmount, 0...1.2, "How strong the gusts are.")
                    s("Wind rhythm", $cfg.gustRate, 0...0.4, "Gust timing — low = long calm stretches.")
                }
                group("Dust") {
                    s("Amount", $cfg.dustCount, 0...60000, "%.0f", "How many motes.")
                    s("Size", $cfg.dustSize, 0.5...6, "Mote size.")
                    s("Glow in the dark", $cfg.dustBase, 0...1, "How visible motes are outside the light.")
                }
                group("Picture") {
                    s("Exposure", $cfg.exposure, 0...3, "Overall brightness before the filmic curve.")
                    s("Glow amount", $cfg.bloomIntensity, 0...2, "How much the bright areas bloom.")
                }

                // ── ADVANCED (collapsed by default) ───────────────────────
                DisclosureGroup(isExpanded: $showAdvanced) {
                    VStack(alignment: .leading, spacing: 12) {
                        group("Light — position") {
                            s("Source →", $cfg.shaftX, -0.5...1.5, "Where the light comes from, sideways.")
                            s("Source ↓", $cfg.shaftY, -0.6...0.5, "Where the light comes from, vertically.")
                        }
                        group("Light — detail") {
                            s("Beam wander", $cfg.shaftWarp, 0...2, "How much the beam field drifts sideways.")
                            s("Softness with distance", $cfg.shaftPenumbra, 0...1.5, "How much beams blur as they travel.")
                            s("Beam gain", $cfg.volDensity, 0...6, "Overall strength of the light in the air.")
                            s("Air wash", $cfg.shaftBg, 0...0.5, "A faint wash of light in the air.")
                        }
                        group("Dust — motion detail") {
                            s("Swirl", $cfg.swirl, 0...2, "How much the dust curls around.")
                            s("Swirl size", $cfg.swirlScale, 0.2...4, "Size of the curls — lower is bigger.")
                            s("Sideways drift", $cfg.drift, -0.2...0.2, "A steady sideways air current.")
                            s("How still", $cfg.drag, 0...12, "Higher = the dust settles more.")
                            s("Shimmer", $cfg.brownian, 0...0.15, "Fine random jitter of the motes.")
                            s("Depth motion", $cfg.parallaxDepth, 0...1, "Nearer motes travel faster (depth feel).")
                            s("Brightness", $cfg.dustBrightness, 0...2, "Overall mote brightness.")
                            s("Distance fade", $cfg.dustFog, 0...5, "How fast far motes fade out.")
                        }
                        group("Layers — depth") {
                            s("Number of layers", $cfg.dustLayers, 1...6, "%.0f", "How many depth bands.")
                            s("Near size", $cfg.dustNearScale, 1...6, "Near-mote size.")
                            s("Near brightness", $cfg.dustNearBrightness, 0.5...4, "Near-mote brightness.")
                            s("Near blur", $cfg.dustNearBlur, 0...1, "Near-mote bokeh.")
                            s("Sparkle", $cfg.sparkle, 0...5, "Glint as motes cross the light.")
                            s("Sparkle speed", $cfg.sparkleSpeed, 0...10, "Glint rate.")
                        }
                        group("Haze") {
                            s("Strength", $cfg.hazeStrength, 0...2, "How much the haze catches the light.")
                            s("Height", $cfg.hazeY, 0.4...1.2, "How high the haze band sits.")
                            s("Thickness", $cfg.hazeThickness, 0.03...0.4, "Band thickness.")
                            s("Size", $cfg.hazeScale, 0.5...8, "Haze clump size.")
                            s("Drift", $cfg.hazeDrift, 0...0.2, "Haze drift.")
                            s("Roll speed", $cfg.hazePulse, 0...0.5, "Haze roll/flicker.")
                        }
                        group("Picture — extra") {
                            s("What glows", $cfg.bloomThreshold, 0...1, "How bright a pixel must be to glow.")
                            s("Highlight softness", $cfg.tonemap, 0...1, "0 = hard clip, 1 = soft filmic rolloff.")
                            s("Glow spread", $cfg.bloomIterations, 0...6, "%.0f", "How far the glow spreads.")
                            s("Texture", $cfg.dither, 0...0.1, "Subtle texture that hides banding.")
                            s("Beam breathing", $cfg.shaftSpeed, 0...2, "How fast the beams breathe.")
                        }
                        group("Interaction") {
                            s("Cursor clearing", $cfg.obstacleRadius, 0...0.05, "How much dust the cursor clears.")
                            s("UI clearance", $cfg.obstaclePad, 0...0.1, "Padding around UI obstacles.")
                        }
                    }
                    .padding(.top, 6)
                } label: {
                    Text("ADVANCED").font(.system(size: 10, weight: .semibold)).tracking(0.8)
                        .foregroundStyle(.secondary)
                }

                // ── DEBUG ─────────────────────────────────────────────────
                group("Debug — show/hide layers") {
                    t("Close-up", $cfg.layerClose, "The nearest, biggest, fastest motes — right in front of the lens.")
                    t("Near", $cfg.layerNear, "Close motes.")
                    t("Mid", $cfg.layerMid, "The main body of dust.")
                    t("Far", $cfg.layerFar, "Distant motes.")
                    t("Haze", $cfg.layerHaze, "The farthest, smallest plate.")
                }
                group("Debug — test wind") {
                    Button("Gust") { box.pipeline?.inputs.gust = 1.6 }
                        .buttonStyle(.bordered).controlSize(.small).font(.system(size: 11))
                    Text("Puffs the light — watch the beams flutter.")
                        .font(.system(size: 9)).foregroundStyle(.tertiary)
                }
                group("Debug — test solid") {
                    t("Show test rect", $testRectOn, "A movable solid the dust flows around.")
                    s("Test rect x", $testRectX, 0...1, "Move the test solid.")
                }
                Button("Reset all") { cfg = SandConfig() }.buttonStyle(.plain)
                    .font(.system(size: 11, weight: .semibold)).foregroundStyle(.orange)
            }
            .padding(18)
        }
    }

    @ViewBuilder
    private func group<C: View>(_ title: String, @ViewBuilder _ content: () -> C) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title.uppercased()).font(.system(size: 9, weight: .semibold))
                .tracking(0.6).foregroundStyle(.secondary).padding(.top, 6)
            content()
        }
    }

    private func presetButton(_ title: String, _ action: @escaping () -> Void) -> some View {
        Button(title, action: action)
            .buttonStyle(.bordered).controlSize(.small).font(.system(size: 11))
    }

    private func t(_ label: String, _ value: Binding<Bool>, _ help: String) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            Toggle(label, isOn: value).toggleStyle(.switch).controlSize(.mini).font(.callout)
            Text(help).font(.system(size: 9)).foregroundStyle(.tertiary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private func s(_ label: String, _ value: Binding<Double>, _ range: ClosedRange<Double>,
                   _ help: String) -> some View {
        s(label, value, range, "%.3f", help)
    }
    private func s(_ label: String, _ value: Binding<Double>, _ range: ClosedRange<Double>,
                   _ format: String, _ help: String = "") -> some View {
        VStack(alignment: .leading, spacing: 1) {
            HStack {
                Text(label).font(.callout)
                Spacer()
                Text(String(format: format, value.wrappedValue))
                    .font(.system(.caption, design: .monospaced)).foregroundStyle(.secondary)
            }
            Slider(value: value, in: range).controlSize(.small)
            if !help.isEmpty {
                Text(help).font(.system(size: 9)).foregroundStyle(.tertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}

// MARK: - Presets

extension SandConfig {
    static let still = SandConfig(swirl: 0.10, brownian: 0.008, shaftStrength: 1.3)
    static let wander = SandConfig(swirl: 0.25, brownian: 0.015, shaftStrength: 1.2)
    static let breezy = SandConfig(swirl: 0.70, brownian: 0.030, shaftStrength: 1.1, shaftDrift: 0.06)
}

// MARK: - Metal view

struct MetalSandView: NSViewRepresentable {
    var config: SandConfig
    var obstacles: [SIMD4<Float>]
    let box: RendererBox

    func makeCoordinator() -> Coord { Coord() }
    final class Coord { var pipeline: SandPipeline? }

    func makeNSView(context: Context) -> TrackingMTKView {
        let v = TrackingMTKView()
        v.device = MTLCreateSystemDefaultDevice()
        v.colorPixelFormat = .bgra8Unorm
        v.framebufferOnly = true
        v.isPaused = false
        v.enableSetNeedsDisplay = false
        v.preferredFramesPerSecond = 120
        v.clearColor = MTLClearColor(red: 0, green: 0, blue: 0, alpha: 1)
        if let d = v.device, let p = SandPipeline(device: d) {
            context.coordinator.pipeline = p
            v.pipeline = p
            v.delegate = p
            p.config = config
            p.inputs.obstacleRects = obstacles
            box.pipeline = p
        }
        return v
    }

    func updateNSView(_ v: TrackingMTKView, context: Context) {
        guard let p = context.coordinator.pipeline else { return }
        p.config = config
        p.inputs.obstacleRects = obstacles
    }
}

final class TrackingMTKView: MTKView {
    weak var pipeline: SandPipeline?
    private var last = CGPoint.zero

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        trackingAreas.forEach { removeTrackingArea($0) }
        addTrackingArea(NSTrackingArea(
            rect: .zero,
            options: [.mouseMoved, .mouseEnteredAndExited, .activeInKeyWindow, .inVisibleRect],
            owner: self, userInfo: nil))
    }

    override func mouseMoved(with event: NSEvent) {
        let pt = convert(event.locationInWindow, from: nil)
        let uv = CGPoint(x: pt.x / max(1, bounds.width), y: 1 - pt.y / max(1, bounds.height))
        last = uv
        pipeline?.inputs.hasPointer = true
        pipeline?.inputs.pointer = SIMD2(Float(uv.x), Float(uv.y))
    }

    override func mouseExited(with event: NSEvent) {
        pipeline?.inputs.hasPointer = false
    }
}

// MARK: - Persist the tuned settings (so a look can be captured as a baseline)

enum SandLabSettings {
    static var url: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? URL(fileURLWithPath: NSTemporaryDirectory())
        let dir = base.appendingPathComponent("SandLab", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir.appendingPathComponent("settings.json")
    }

    static func save(_ c: SandConfig) {
        let enc = JSONEncoder(); enc.outputFormatting = [.prettyPrinted, .sortedKeys]
        guard let data = try? enc.encode(c) else { return }
        try? data.write(to: url)
    }

    static func load() -> SandConfig? {
        guard let data = try? Data(contentsOf: url) else { return nil }
        return try? JSONDecoder().decode(SandConfig.self, from: data)
    }
}
