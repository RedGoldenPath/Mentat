import SwiftUI

/// A past-conversation card in the history rail: a rounded, translucent tile
/// with the title, a relative date and the turn count (Siri-history style).
struct ConversationCard: View {
    enum Style { case tile, row }
    let title: String
    let date: String
    let turns: Int
    let selected: Bool
    var pinned: Bool = false
    var style: Style = .tile
    let ink: Color
    let dim: Color
    let accent: Color
    let isLight: Bool
    let onTap: () -> Void
    var onPin: () -> Void = {}
    let onDelete: () -> Void
    @State private var hover = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.colorTheme) private var colorTheme

    private var turnsLabel: String { "\(turns) turn\(turns == 1 ? "" : "s")" }

    var body: some View {
        Button(action: onTap) {
            content
                .padding(12)
                .frame(maxWidth: .infinity, alignment: .topLeading)
                .background {
                    ZStack {
                        RoundedRectangle(cornerRadius: 18, style: .continuous).fill(
                            .ultraThinMaterial)
                        // theme-tinted translucent base, so the card takes the image hue
                        if colorTheme != .placeholder {
                            RoundedRectangle(cornerRadius: 18, style: .continuous)
                                .fill(colorTheme.surface.opacity(isLight ? 0.45 : 0.55))
                        }
                        RoundedRectangle(cornerRadius: 18, style: .continuous)
                            .fill(
                                selected
                                    ? accent.opacity(isLight ? 0.16 : 0.24)
                                    : ink.opacity(hover ? 0.07 : 0))
                    }
                }
                .overlay(
                    RoundedRectangle(cornerRadius: 18, style: .continuous)
                        .stroke(
                            selected ? accent.opacity(0.9) : ink.opacity(0.14),
                            lineWidth: selected ? 1.5 : 1)
                )
                .shadow(
                    color: .black.opacity(hover ? 0.28 : 0.14),
                    radius: hover ? 10 : 5, y: hover ? 5 : 2
                )
                .scaleEffect(hover && !reduceMotion ? 1.015 : 1)
                .contentShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        }
        .buttonStyle(.pressable)
        .onHover { hover = $0 }
        .animation(reduceMotion ? nil : Anim.snappy, value: hover)
        .animation(reduceMotion ? nil : Anim.snappy, value: selected)
        .contextMenu {
            Button(pinned ? "Unpin Conversation" : "Pin Conversation", action: onPin)
            Divider()
            Button("Delete Conversation", role: .destructive, action: onDelete)
        }
    }

    @ViewBuilder private var content: some View {
        switch style {
        case .row:
            // compact horizontal row (List mode)
            VStack(alignment: .leading, spacing: 8) {
                header
                Text(title)
                    .font(.system(size: TypeScale.bodyMono, weight: .semibold))
                    .foregroundStyle(ink)
                    .lineLimit(2)
                    .multilineTextAlignment(.leading)
                    .frame(maxWidth: .infinity, alignment: .leading)
                Text(turnsLabel).font(.system(size: TypeScale.meta)).foregroundStyle(dim)
            }
        case .tile:
            // portrait tile (Grid mode): content height varies with the title so
            // the masonry columns stagger
            VStack(alignment: .leading, spacing: 8) {
                header
                Text(title)
                    .font(.system(size: 13.5, weight: .semibold))
                    .foregroundStyle(ink)
                    .lineLimit(4)
                    .multilineTextAlignment(.leading)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)
                Text(turnsLabel).font(.system(size: TypeScale.meta)).foregroundStyle(dim)
            }
            .frame(maxWidth: .infinity, minHeight: 78, alignment: .topLeading)
        }
    }

    private var header: some View {
        HStack(spacing: 6) {
            Image(systemName: "bubble.left.and.bubble.right")
                .font(.system(size: 10, weight: .semibold))
                .foregroundStyle(selected ? accent : dim)
            if pinned {
                Image(systemName: "pin.fill")
                    .font(.system(size: TypeScale.micro, weight: .semibold))
                    .foregroundStyle(accent)
            }
            Spacer(minLength: 0)
            Text(date)
                .font(.system(size: TypeScale.meta, weight: .medium))
                .foregroundStyle(dim)
                .lineLimit(1)
        }
    }
}
