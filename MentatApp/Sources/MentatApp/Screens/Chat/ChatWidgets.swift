import SwiftUI

// MARK: - Small chat components

struct CitationChip: View {
    let citation: Citation
    /// Tap → open the passage in the source reader.
    var onOpen: (() -> Void)? = nil
    @Environment(\.palette) private var pal
    @State private var hover = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        let chip = HStack(spacing: 4) {
            Image(systemName: "text.quote").font(.caption2)
            Text("\(citation.book) · \(citation.loc)").font(.caption2).lineLimit(1)
        }
        .padding(.horizontal, 8).padding(.vertical, 3)
        .background(
            Engine.shared.accentColor(.center).opacity(pal.isDark ? 0.14 : 0.18),
            in: Capsule()
        )
        .foregroundStyle(pal.isDark ? pal.gold : pal.terracotta)
        .overlay(
            Capsule().strokeBorder(
                Engine.shared.accentColor(.center).opacity(hover && onOpen != nil ? 0.55 : 0),
                lineWidth: 1)
        )
        .scaleEffect(hover && onOpen != nil && !reduceMotion ? 1.04 : 1)
        .animation(reduceMotion ? nil : Anim.snappy, value: hover)

        if let onOpen {
            Button(action: onOpen) { chip }
                .buttonStyle(.plain)
                .onHover { hover = $0 }
                .help("Read the source")
                .accessibilityLabel("Open source: \(citation.book), \(citation.loc)")
        } else {
            chip
        }
    }
}

struct ActionButton: View {
    let system: String
    let help: String
    let action: () -> Void
    @Environment(\.palette) private var pal
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var hover = false
    @State private var taps = 0
    var body: some View {
        Button {
            taps += 1
            action()
        } label: {
            Image(systemName: system)
                .font(.caption2)
                .symbolEffect(.bounce, options: .speed(1.8), value: taps)
                .scaleEffect(hover && !reduceMotion ? 1.12 : 1)
        }
        .buttonStyle(.pressable)
        .foregroundStyle(hover ? pal.text : pal.textDim)
        .help(help)
        .accessibilityLabel(help)
        .onHover { hover = $0 }
        .motion(Anim.snappy, value: hover)
    }
}

/// Glass chip with a gentle Apple-style hover lift.
struct ChipButton: View {
    let system: String
    let help: String
    let color: Color
    let action: () -> Void
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var hover = false
    @State private var taps = 0

    var body: some View {
        Button {
            taps += 1
            action()
        } label: {
            Image(systemName: system)
                .font(.system(size: 13, weight: .medium))
                .frame(width: 30, height: 30)
                .symbolEffect(.bounce, options: .speed(1.8), value: taps)
        }
        .buttonStyle(.glass)  // Apple's native Liquid Glass button
        .foregroundStyle(color)
        .help(help)
        .accessibilityLabel(help)
        .onHover { hover = $0 }
        .scaleEffect(hover && !reduceMotion ? 1.07 : 1)
        .animation(reduceMotion ? nil : Anim.snappy, value: hover)
    }
}

struct LCG: RandomNumberGenerator {
    var state: UInt64
    mutating func next() -> UInt64 {
        state = state &* 6_364_136_223_846_793_005 &+ 1_442_695_040_888_963_407
        return state
    }
}
