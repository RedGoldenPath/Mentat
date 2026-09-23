import SwiftUI

// MARK: - Command palette

struct CommandPalette: View {
    var debugMode: Bool = false
    let onPick: (String) -> Void
    @State private var query = ""
    @State private var hovered: CommandItem.ID?
    @Environment(\.palette) private var pal

    private var accent: Color { Engine.shared.accentColor(.center) }

    private var items: [CommandItem] {
        CommandItem.all(debug: debugMode)
            .filter {
                query.isEmpty || $0.cmd.contains(query.lowercased())
                    || $0.help.lowercased().contains(query.lowercased())
            }
    }

    /// Balanced two-column split — the palette reads like a reference spread
    /// instead of one long scroll.
    private var columns: [[CommandItem]] {
        guard items.count > 4 else { return [items] }
        let half = Int((Double(items.count) / 2).rounded(.up))
        return [Array(items.prefix(half)), Array(items.dropFirst(half))]
    }

    var body: some View {
        VStack(spacing: 0) {
            TextField("Search commands…", text: $query)
                .textFieldStyle(.plain)
                .padding(12)
                .liquid(corner: 14)
                .padding(.horizontal, 12).padding(.top, 12).padding(.bottom, 4)
            ScrollView {
                HStack(alignment: .top, spacing: 0) {
                    ForEach(Array(columns.enumerated()), id: \.offset) { _, column in
                        VStack(alignment: .leading, spacing: 0) {
                            ForEach(column) { item in row(item) }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
            }
            .softScrollEdges()
        }
        .frame(width: 660, height: 440)
        .background(.regularMaterial)
    }

    private func row(_ item: CommandItem) -> some View {
        let hot = hovered == item.id
        return Button {
            onPick(item.cmd)
        } label: {
            HStack {
                Text("/\(item.cmd)").foregroundStyle(accent).frame(width: 110, alignment: .leading)
                Text(item.help).foregroundStyle(pal.text)
                Spacer()
            }
            .font(.system(size: TypeScale.body))
            .padding(.horizontal, 12).padding(.vertical, 8)
            .background {
                if hot {
                    Color.clear
                        .glassEffect(
                            Glass.regular.tint(accent.opacity(0.55)),
                            in: Capsule(style: .continuous))
                }
            }
            .contentShape(Capsule())
            .padding(.horizontal, 8)
        }
        .buttonStyle(.plain)
        .onHover { hovered = $0 ? item.id : (hovered == item.id ? nil : hovered) }
    }
}
