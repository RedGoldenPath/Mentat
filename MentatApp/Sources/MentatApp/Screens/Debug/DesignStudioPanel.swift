import SwiftUI

/// The design control surface, in the everyday menu: pick a whole look, then a
/// couple of surface knobs. Everything writes to the token store, so the change
/// is instant and applies across the entire app.
struct DesignStudioPanel: View {
    @Environment(DesignStore.self) private var store: DesignStore?
    @Environment(\.palette) private var pal

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
            VStack(alignment: .leading, spacing: 8) {
                groupLabel("Look")
                HStack(spacing: 8) {
                    ForEach(DesignPreset.all) { preset in
                        presetCard(preset, store: store)
                    }
                }
            }

            VStack(alignment: .leading, spacing: 7) {
                groupLabel("Cards")
                slider("Corner", binding(store, \.composition.bubbleCorner), 6...28)
            }
        }
        .font(.system(size: 11))
    }

    private func presetCard(_ preset: DesignPreset, store: DesignStore) -> some View {
        let active = DesignPreset.matching(store.tokens) == preset.id
        return Button {
            withAnimation(Anim.smooth) {
                var d = store.tokens
                preset.apply(to: &d)
                store.tokens = d
                // keep the window's light/dark consistent with the look
                switch preset.look {
                case .paper: UserDefaults.standard.set("light", forKey: "appearance")
                case .mono, .sand: UserDefaults.standard.set("dark", forKey: "appearance")
                case .system: break
                }
            }
        } label: {
            VStack(alignment: .leading, spacing: 6) {
                presetSwatch(preset.look)
                Text(preset.name)
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(pal.text)
                Text(preset.blurb)
                    .font(.system(size: 9))
                    .foregroundStyle(pal.textDim)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(8)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .fill(pal.text.opacity(active ? 0.10 : 0.03))
            )
            .overlay(
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .stroke(active ? pal.spice : pal.border.opacity(0.4),
                            lineWidth: active ? 1.5 : 1)
            )
        }
        .buttonStyle(.plain)
        .help("Apply the \(preset.name) look")
    }

    /// A tiny preview of the look: canvas, a raised card, and an ink rule.
    private func presetSwatch(_ look: SurfaceLook) -> some View {
        let t = ColorTheme.look(look, isDark: look != .system && look != .paper)
        return ZStack {
            RoundedRectangle(cornerRadius: 7, style: .continuous)
                .fill(t.background)
                .frame(height: 30)
            RoundedRectangle(cornerRadius: 5, style: .continuous)
                .fill(t.surface)
                .frame(width: 40, height: 18)
                .overlay(
                    RoundedRectangle(cornerRadius: 5, style: .continuous)
                        .stroke(t.border.opacity(0.7), lineWidth: 0.75))
            Capsule()
                .fill(t.ink)
                .frame(width: 24, height: 3)
                .offset(y: -1)
        }
        .overlay(
            RoundedRectangle(cornerRadius: 7, style: .continuous)
                .stroke(.black.opacity(0.12), lineWidth: 0.5))
    }

    private func groupLabel(_ s: String) -> some View {
        Text(s.uppercased())
            .font(.system(size: 9, weight: .semibold)).tracking(0.6)
            .foregroundStyle(pal.textDim)
    }

    private func slider(_ label: String, _ value: Binding<Double>, _ range: ClosedRange<Double>)
        -> some View
    {
        HStack(spacing: 6) {
            Text(label).frame(width: 52, alignment: .leading)
            Slider(value: value, in: range)
            Text(String(format: "%.0f", value.wrappedValue))
                .foregroundStyle(pal.textDim).frame(width: 28, alignment: .trailing)
        }
        .font(.system(size: 10.5, design: .monospaced))
    }

    private func binding(_ s: DesignStore, _ kp: WritableKeyPath<DesignTokens, Double>) -> Binding<
        Double
    > {
        Binding(get: { s.tokens[keyPath: kp] }, set: { s.tokens[keyPath: kp] = $0 })
    }
}
