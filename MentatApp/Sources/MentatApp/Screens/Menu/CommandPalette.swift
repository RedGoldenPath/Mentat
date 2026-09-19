import SwiftUI

// MARK: - Command palette

struct CommandPalette: View {
    var debugMode: Bool = false
    let onPick: (String) -> Void
    @State private var query = ""
    @Environment(\.palette) private var pal

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
        Button {
            onPick(item.cmd)
        } label: {
            HStack {
                Text("/\(item.cmd)").foregroundStyle(
                    Engine.shared.accentColor(.center)
                ).frame(width: 110, alignment: .leading)
                Text(item.help).foregroundStyle(pal.text)
                Spacer()
            }
            .padding(.horizontal, 14).padding(.vertical, 7)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}
