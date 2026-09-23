import SwiftUI

/// The shared chrome vocabulary, read live from `DesignTokens.chrome` so every
/// circle, capsule and card draws from the same data.
enum ChromeShape {
    static var c: DesignTokens.Chrome { DesignTokens.current.chrome }
    static var circle: CGFloat { CGFloat(c.circle) }
    static var circleSmall: CGFloat { CGFloat(c.circleSmall) }
    static var capsuleHeight: CGFloat { CGFloat(c.capsuleHeight) }
    static var capsulePadH: CGFloat { CGFloat(c.capsulePadH) }
    static var radiusS: CGFloat { CGFloat(c.radiusS) }
    static var radiusM: CGFloat { CGFloat(c.radiusM) }
    static var radiusL: CGFloat { CGFloat(c.radiusL) }
    static var radiusXL: CGFloat { CGFloat(c.radiusXL) }
    static var pressedScale: CGFloat { CGFloat(c.pressedScale) }
}

/// One circular Liquid-Glass icon button — the single implementation behind the
/// top discs, the menu rail and any glyph control, so they can't drift apart.
struct CircleIconButton: View {
    let system: String
    var help: String = ""
    var diameter: CGFloat? = nil
    var active: Bool = false
    var tint: Color? = nil
    var action: () -> Void

    @Environment(\.palette) private var pal
    @Environment(\.colorTheme) private var colorTheme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var hover = false

    private var d: CGFloat { diameter ?? ChromeShape.circleSmall }
    private var accent: Color {
        tint ?? (colorTheme != .placeholder ? colorTheme.accent : Engine.shared.accentColor(.center))
    }

    var body: some View {
        Button(action: action) {
            Image(systemName: system)
                .font(.system(size: d * 0.42, weight: .semibold))
                .frame(width: d, height: d)
                .contentShape(Circle())
        }
        .glassControl(.small, shape: .circle, prominent: active, tint: active ? accent : nil)
        .foregroundStyle(active ? (colorTheme != .placeholder ? colorTheme.onAccent : pal.text) : pal.text)
        .scaleEffect(hover && !reduceMotion ? 1.06 : 1)
        .animation(reduceMotion ? nil : Anim.snappy, value: hover)
        .onHover { hover = $0 }
        .help(help)
        .accessibilityLabel(help)
    }
}

/// A glass capsule track with a sliding tinted-glass thumb — the "VIDEO / PHOTO"
/// control from the references, generic over its options so every picker can use
/// it instead of the system segmented style. The thumb is real Liquid Glass
/// (`Glass.tint`) inside a `GlassEffectContainer` and morphs via `glassEffectID`,
/// so it inherits the platform's active/inactive rendering rather than painting
/// a fake tint on top.
struct GlassSegmentedControl<T: Hashable>: View {
    let options: [T]
    let label: (T) -> String
    @Binding var selection: T

    @Environment(\.palette) private var pal
    @Environment(\.colorTheme) private var colorTheme
    @Environment(\.glassStyle) private var glassStyle
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Namespace private var ns

    private var accent: Color {
        colorTheme != .placeholder ? colorTheme.accent : Engine.shared.accentColor(.center)
    }
    private var thumbTint: Color {
        colorTheme != .placeholder
            ? (glassStyle == .clear ? colorTheme.clearTint : colorTheme.accentTint)
            : accent.opacity(0.55)
    }

    var body: some View {
        if reduceTransparency {
            opaque
        } else {
            glassy
        }
    }

    private var glassy: some View {
        GlassEffectContainer(spacing: 3) {
            HStack(spacing: 3) {
                ForEach(Array(options.enumerated()), id: \.offset) { _, opt in
                    segment(opt)
                }
            }
            .padding(3)
            .glassEffect(Glass.regular, in: Capsule(style: .continuous))
        }
        .shadow(color: .black.opacity(pal.isDark ? 0.30 : 0.12), radius: 8, y: 3)
    }

    private var opaque: some View {
        HStack(spacing: 3) {
            ForEach(Array(options.enumerated()), id: \.offset) { _, opt in
                let active = opt == selection
                Button {
                    withAnimation(Anim.snappy) { selection = opt }
                } label: {
                    segmentLabel(opt, active: active)
                        .background {
                            if active {
                                Capsule(style: .continuous).fill(accent)
                            }
                        }
                }
                .buttonStyle(.plain)
            }
        }
        .padding(3)
        .background(Capsule(style: .continuous).fill(pal.bg2.opacity(0.92)))
    }

    private func segment(_ opt: T) -> some View {
        let active = opt == selection
        return Button {
            withAnimation(Anim.snappy) { selection = opt }
        } label: {
            segmentLabel(opt, active: active)
                .background {
                    if active {
                        Color.clear
                            .glassEffect(
                                Glass.regular.tint(thumbTint), in: Capsule(style: .continuous)
                            )
                            .glassEffectID("thumb", in: ns)
                    }
                }
        }
        .buttonStyle(.plain)
    }

    private func segmentLabel(_ opt: T, active: Bool) -> some View {
        Text(label(opt))
            .font(.system(size: TypeScale.label, weight: active ? .semibold : .medium))
            .lineLimit(1)
            .fixedSize(horizontal: true, vertical: false)
            .foregroundStyle(active ? pal.text : pal.text.opacity(0.72))
            .padding(.vertical, 6).padding(.horizontal, 12)
            .frame(maxWidth: .infinity)
            .contentShape(Capsule())
    }
}
