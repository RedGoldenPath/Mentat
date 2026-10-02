import SwiftUI

/// Developer-scene sand controls. The everyday panel (SandPanel) keeps only the
/// plain-English knobs; everything technical lives here, plus the per-layer
/// isolate toggles used to lock in a look. Thin binding over `DesignTokens.sand`.
struct SandDebugPanel: View {
    @Environment(DesignStore.self) private var store: DesignStore?
    @Environment(\.palette) private var pal

    var body: some View {
        if let store {
            let live = Binding(
                get: { store.tokens.sand.enabled },
                set: { store.tokens.sand.enabled = $0 })
            VStack(alignment: .leading, spacing: 14) {
                header("Sand (pro)")
                group("Motion") {
                    slider("Swirl", \.swirl, 0...2, "%.2f")
                    slider("Swirl scale", \.swirlScale, 0.2...4, "%.2f")
                    slider("Drift", \.drift, -0.2...0.2, "%.3f")
                }
                group("Obstacles") {
                    slider("Cursor radius", \.obstacleRadius, 0...0.05, "%.3f")
                    slider("Rect pad", \.obstaclePad, 0...0.1, "%.3f")
                }
                group("Light shape") {
                    slider("Spread", \.shaftSpread, 5...80, "%.0f")
                    slider("Rays", \.shaftRays, 1...12, "%.0f")
                    slider("Beam drift", \.shaftDrift, 0...0.2, "%.3f")
                    slider("Background wash", \.shaftBg, 0...0.5, "%.3f")
                    slider("Source glow", \.shaftSourceGlow, 0...4, "%.2f")
                }
                group("Dust advanced") {
                    slider("Depth fog", \.dustFog, 0...5, "%.2f")
                    slider("Base (glow in dark)", \.dustBase, 0...1, "%.2f")
                    slider("Brightness", \.dustBrightness, 0...2, "%.2f")
                }
                group("Volumetric") {
                    slider("Steps", \.volSteps, 4...64, "%.0f")
                    slider("Density", \.volDensity, 0...6, "%.2f")
                    slider("Extinction", \.volExtinction, 0...4, "%.2f")
                    slider("Medium scale", \.volScale, 0.5...6, "%.1f")
                    slider("Medium drift", \.volDrift, 0...0.2, "%.3f")
                    slider("Jitter", \.volJitter, 0...1, "%.2f")
                    slider("TAA blend", \.taaAlpha, 0.02...1, "%.2f")
                }
                group("Bloom · cadence") {
                    slider("Bloom levels", \.bloomIterations, 0...6, "%.0f")
                    slider("Idle window", \.idleWindow, 0.5...6, "%.1f")
                    slider("Impulse scale", \.impulseScale, 0...2, "%.2f")
                }
                group("Isolate layers (5)") {
                    layer("Close-up", \.layerClose)
                    layer("Near", \.layerNear)
                    layer("Mid", \.layerMid)
                    layer("Far", \.layerFar)
                    layer("Haze", \.layerHaze)
                }
                Toggle("Living sand", isOn: live)
                    .toggleStyle(.switch).controlSize(.mini)
                    .font(.system(size: TypeScale.label))
                    .foregroundStyle(pal.text)
            }
            .padding(.horizontal, 14).padding(.vertical, 12)
            .surface(shape: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .stroke(pal.border.opacity(0.28), lineWidth: 1))
        }
    }

    private func header(_ t: String) -> some View {
        Text(t.uppercased())
            .font(.system(size: 10, weight: .semibold)).tracking(1.1)
            .foregroundStyle(pal.textDim)
    }

    @ViewBuilder
    private func group<C: View>(_ title: String, @ViewBuilder _ content: () -> C) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title.uppercased()).font(.system(size: 9, weight: .semibold))
                .tracking(0.6).foregroundStyle(pal.textDim)
            content()
        }
    }

    private func layer(_ label: String, _ kp: WritableKeyPath<DesignTokens.Sand, Bool>) -> some View {
        let b = Binding(
            get: { store?.tokens.sand[keyPath: kp] ?? true },
            set: { store?.tokens.sand[keyPath: kp] = $0 })
        return Toggle(label, isOn: b)
            .toggleStyle(.checkbox)
            .font(.system(size: TypeScale.label))
            .foregroundStyle(pal.text)
    }

    private func slider(_ label: String, _ kp: WritableKeyPath<DesignTokens.Sand, Double>,
                        _ range: ClosedRange<Double>, _ format: String) -> some View {
        let v = store?.tokens.sand[keyPath: kp] ?? range.lowerBound
        return HStack(spacing: 6) {
            Text(label).font(.system(size: TypeScale.label))
                .foregroundStyle(pal.text).frame(width: 108, alignment: .leading)
            Slider(value: Binding(
                get: { store?.tokens.sand[keyPath: kp] ?? range.lowerBound },
                set: { store?.tokens.sand[keyPath: kp] = $0 }), in: range)
            Text(String(format: format, v))
                .foregroundStyle(pal.textDim)
                .font(.system(size: TypeScale.caption, design: .monospaced))
                .frame(width: 40, alignment: .trailing)
        }
    }
}
