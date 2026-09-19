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
    var body: some View {
        Button(action: action) {
            Image(systemName: system).font(.caption2)
        }
        .buttonStyle(.plain)
        .foregroundStyle(pal.textDim)
        .help(help)
        .accessibilityLabel(help)
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

    var body: some View {
        Button(action: action) {
            Image(systemName: system)
                .font(.system(size: 13, weight: .medium))
                .frame(width: 30, height: 30)
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

struct StarField: View {
    var body: some View {
        Canvas { ctx, size in
            var rng = LCG(state: 7)
            let glyphs = ["·", "*", "+", "°", "•"]
            let center = CGPoint(x: size.width * 0.5, y: size.height * 0.55)
            let maxR = max(1, hypot(size.width * 0.5, size.height * 0.55))
            for _ in 0..<260 {
                let x = Double.random(in: 0...1, using: &rng) * size.width
                let y = Double.random(in: 0...1, using: &rng) * size.height
                let d = hypot(Double(x - center.x), Double(y - center.y)) / maxR
                let edge = max(0.0, min(1.0, (d - 0.18) / 0.62))
                let alpha = edge * edge
                if alpha <= 0.03 { continue }
                let g = glyphs[Int(Double.random(in: 0...4.999, using: &rng))]
                let shade = Double.random(in: 0...1, using: &rng)
                let color = Color(
                    red: 0.85 + 0.15 * shade, green: 0.78 + 0.18 * shade, blue: 0.62 + 0.30 * shade
                )
                .opacity(alpha * 0.85)
                ctx.draw(
                    Text(g).font(.system(size: 6.5)).foregroundColor(color),
                    at: CGPoint(x: x, y: y))
            }
        }
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}

struct LCG: RandomNumberGenerator {
    var state: UInt64
    mutating func next() -> UInt64 {
        state = state &* 6_364_136_223_846_793_005 &+ 1_442_695_040_888_963_407
        return state
    }
}
