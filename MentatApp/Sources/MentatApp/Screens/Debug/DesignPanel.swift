import SwiftUI

/// The design tokens, editable — the same data the UI renders from. Type, motion,
/// metrics, and composition in one place, so Settings/Debug drive the app rather
/// than drifting from it.
struct DesignPanel: View {
    @Environment(DesignStore.self) private var store: DesignStore?

    var body: some View {
        if let store {
            content(store)
        } else {
            Text("no design store").font(.caption2).foregroundStyle(.secondary)
        }
    }

    @ViewBuilder
    private func content(_ store: DesignStore) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            group("Type") {
                slider("Size", bind(store, \.typography.fontSize), 9...18, "%.1f")
                slider("Line", bind(store, \.typography.lineSpacing), 0...12, "%.1f")
                stepper("Max chars", bind(store, \.typography.maxChars), 30...90)
                stepper("Columns", bind(store, \.typography.maxColumns), 1...4)
                stepper("Lines/col", bind(store, \.typography.linesPerColumn), 10...60)
            }
            group("Motion") {
                slider("Smooth", bind(store, \.motion.smoothDuration), 0.05...1.0, "%.2f")
                slider("Snappy", bind(store, \.motion.snappyDuration), 0.05...1.0, "%.2f")
                slider("Bubble", bind(store, \.motion.bubbleBounce), 0...0.5, "%.2f")
            }
            group("Composition") {
                stepperD("Header", bind(store, \.composition.headerHeight), 40...140, 2)
                stepperD("Composer", bind(store, \.composition.composerHeight), 40...160, 2)
                stepperD("Bubble r", bind(store, \.composition.bubbleCorner), 4...40, 2)
            }
            group("Chrome") {
                stepperD("Sidebar min", bind(store, \.metrics.sidebarMin), 180...320, 10)
                stepperD("Ideal", bind(store, \.metrics.sidebarIdeal), 220...420, 10)
                stepperD("Max", bind(store, \.metrics.sidebarMax), 300...600, 10)
                stepperD("Panel pad", bind(store, \.metrics.panelPadMin), 4...24, 2)
                stepperD("Panel radius", bind(store, \.metrics.panelRadiusPad), 0...20, 2)
            }
            HStack {
                Spacer()
                Button("Reset design") { store.reset() }
                    .controlSize(.mini)
            }
        }
        .font(.system(size: 11))
    }

    @ViewBuilder
    private func group<Content: View>(_ title: String, @ViewBuilder _ content: () -> Content)
        -> some View
    {
        VStack(alignment: .leading, spacing: 4) {
            Text(title.uppercased())
                .font(.system(size: 9, weight: .semibold)).tracking(0.6)
                .foregroundStyle(.secondary)
            content()
        }
    }

    private func slider(
        _ label: String, _ value: Binding<Double>,
        _ range: ClosedRange<Double>, _ format: String
    ) -> some View {
        HStack(spacing: 6) {
            Text(label).frame(width: 62, alignment: .leading)
            Slider(value: value, in: range)
            Text(String(format: format, value.wrappedValue))
                .foregroundStyle(.secondary).frame(width: 36, alignment: .trailing)
        }
        .font(.system(size: 10.5, design: .monospaced))
    }

    private func stepper(_ label: String, _ value: Binding<Int>, _ range: ClosedRange<Int>)
        -> some View
    {
        Stepper("\(label)  \(value.wrappedValue)", value: value, in: range)
            .font(.system(size: 10.5, design: .monospaced))
    }

    private func stepperD(
        _ label: String, _ value: Binding<Double>,
        _ range: ClosedRange<Double>, _ step: Double
    ) -> some View {
        Stepper("\(label)  \(Int(value.wrappedValue))", value: value, in: range, step: step)
            .font(.system(size: 10.5, design: .monospaced))
    }

    private func bind(_ s: DesignStore, _ kp: WritableKeyPath<DesignTokens, Double>) -> Binding<
        Double
    > {
        Binding(get: { s.tokens[keyPath: kp] }, set: { s.tokens[keyPath: kp] = $0 })
    }
    private func bind(_ s: DesignStore, _ kp: WritableKeyPath<DesignTokens, Int>) -> Binding<Int> {
        Binding(get: { s.tokens[keyPath: kp] }, set: { s.tokens[keyPath: kp] = $0 })
    }
}
