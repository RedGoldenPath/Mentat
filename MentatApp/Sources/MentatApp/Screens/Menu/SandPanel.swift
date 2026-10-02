import SwiftUI

/// The Sand studio: a short, plain set of the knobs you actually use, with the
/// rest behind **Advanced**. Writes straight to `DesignTokens.sand` — the single
/// source — so the surface updates live and values round-trip the token graph.
struct SandPanel: View {
    @Environment(DesignStore.self) private var store: DesignStore?
    @Environment(\.palette) private var pal
    @Environment(\.glassStyle) private var glassStyle
    @State private var showAdvanced = false

    var body: some View {
        if let store {
            content(store)
        } else {
            Text("no design store").font(.caption2).foregroundStyle(.secondary)
        }
    }

    @ViewBuilder
    private func content(_ store: DesignStore) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            Toggle(isOn: Binding(
                get: { store.tokens.sand.enabled },
                set: { on in
                    store.tokens.sand.enabled = on
                    if on { store.tokens.look = .sand }
                })
            ) {
                VStack(alignment: .leading, spacing: 1) {
                    Text("Living sand").font(.system(size: 11, weight: .semibold))
                    Text("Dust lit by beams from one source")
                        .font(.system(size: 9)).foregroundStyle(pal.textDim)
                }
            }
            .toggleStyle(.switch)
            .controlSize(.small)

            group("Light") {
                slider("Brightness", \.shaftStrength, 0...4, "%.2f")
                slider("Fan width", \.shaftSpread, 5...90, "%.0f")
                slider("Cloud scale", \.volScale, 0.5...8, "%.1f")
                slider("Beam churn", \.volDrift, 0...0.2, "%.3f")
                slider("Distance fade", \.shaftFalloff, 0...4, "%.2f")
                slider("Glow at source", \.shaftSourceGlow, 0...4, "%.2f")
            }
            group("Movement") {
                slider("Sway", \.lightSway, 0...1, "%.2f")
                slider("Flicker", \.beamFlutter, 0...1, "%.2f")
                slider("Flicker speed", \.beamFlutterSpeed, 0...3, "%.2f")
                slider("Wind strength", \.gustAmount, 0...1.2, "%.2f")
                slider("Wind rhythm", \.gustRate, 0...0.4, "%.3f")
            }
            group("Dust") {
                slider("Amount", \.dustCount, 0...60000, "%.0f")
                slider("Size", \.dustSize, 0.5...6, "%.1f")
                slider("Glow in the dark", \.dustBase, 0...1, "%.2f")
            }
            group("Picture") {
                slider("Exposure", \.exposure, 0...3, "%.2f")
                slider("Glow", \.bloomIntensity, 0...2, "%.2f")
            }

            DisclosureGroup(isExpanded: $showAdvanced) {
                VStack(alignment: .leading, spacing: 14) {
                    group("Light — position") {
                        slider("Source →", \.shaftX, -0.5...1.5, "%.2f")
                        slider("Source ↓", \.shaftY, -0.6...0.5, "%.2f")
                    }
                    group("Dust — detail") {
                        slider("How still", \.drag, 0...12, "%.2f")
                        slider("Shimmer", \.brownian, 0...0.15, "%.3f")
                        slider("Depth motion", \.parallaxDepth, 0...1, "%.2f")
                        slider("Brightness", \.dustBrightness, 0...2, "%.2f")
                    }
                    group("Picture — detail") {
                        slider("What glows", \.bloomThreshold, 0...1, "%.2f")
                        slider("Highlight softness", \.tonemap, 0...1, "%.2f")
                        slider("Texture", \.dither, 0...0.1, "%.3f")
                    }
                    group("Glass") {
                        GlassSegmentedControl(
                            options: [GlassStyle.tinted, .clear],
                            label: { $0 == .tinted ? "Tinted" : "Clear" },
                            selection: Binding(
                                get: { glassStyle }, set: { Engine.shared.setGlassStyle($0) }))
                    }
                }
                .padding(.top, 6)
            } label: {
                Text("ADVANCED").font(.system(size: 10, weight: .semibold)).tracking(0.8)
                    .foregroundStyle(pal.textDim)
            }

            Button("Reset sand") {
                var s = DesignTokens.Sand()
                s.enabled = store.tokens.sand.enabled
                store.tokens.sand = s
            }
            .buttonStyle(.plain)
            .font(.system(size: 10.5, weight: .semibold))
            .foregroundStyle(pal.spice)
        }
        .font(.system(size: 11))
    }

    @ViewBuilder
    private func group<Content: View>(_ title: String, @ViewBuilder _ content: () -> Content)
        -> some View
    {
        VStack(alignment: .leading, spacing: 7) {
            Text(title.uppercased())
                .font(.system(size: 9, weight: .semibold)).tracking(0.6)
                .foregroundStyle(pal.textDim)
            content()
        }
    }

    private func slider(_ label: String, _ kp: WritableKeyPath<DesignTokens.Sand, Double>,
                        _ range: ClosedRange<Double>, _ format: String) -> some View {
        let v = store?.tokens.sand[keyPath: kp] ?? range.lowerBound
        return HStack(spacing: 6) {
            Text(label).frame(width: 96, alignment: .leading)
            Slider(value: Binding(
                get: { store?.tokens.sand[keyPath: kp] ?? range.lowerBound },
                set: { store?.tokens.sand[keyPath: kp] = $0 }), in: range)
            Text(String(format: format, v))
                .foregroundStyle(pal.textDim).frame(width: 40, alignment: .trailing)
        }
        .font(.system(size: 10.5, design: .monospaced))
    }
}
