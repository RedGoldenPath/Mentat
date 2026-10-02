import SwiftUI

// MARK: - Command palette (⌘K)

/// One palette over the shared `Command` registry, grouped by section and
/// annotated with icons and shortcuts. Picking a command hands the whole
/// `Command` back so the host can run slash commands or UI actions.
struct CommandPalette: View {
    var debugMode: Bool = false
    let onPick: (Command) -> Void
    @State private var query = ""
    @State private var hovered: String?
    @Environment(\.palette) private var pal

    private var accent: Color { Engine.shared.accentColor(.center) }

    private var items: [Command] {
        CommandRegistry.all(debug: debugMode).filter {
            query.isEmpty
                || $0.title.localizedCaseInsensitiveContains(query)
                || $0.help.localizedCaseInsensitiveContains(query)
                || ($0.slash?.contains(query.lowercased()) ?? false)
        }
    }

    private var sections: [(Command.Section, [Command])] {
        Command.Section.allCases.compactMap { sec in
            let list = items.filter { $0.section == sec }
            return list.isEmpty ? nil : (sec, list)
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            TextField("Search commands…", text: $query)
                .textFieldStyle(.plain)
                .padding(12)
                .liquid(corner: 14)
                .padding(.horizontal, 12).padding(.top, 12).padding(.bottom, 4)
            ScrollView {
                VStack(alignment: .leading, spacing: 2) {
                    if sections.isEmpty {
                        Text("No commands")
                            .font(.system(size: TypeScale.body))
                            .foregroundStyle(pal.textDim)
                            .frame(maxWidth: .infinity, alignment: .center)
                            .padding(.vertical, 40)
                    }
                    ForEach(sections, id: \.0) { section, list in
                        Text(section.title)
                            .font(.system(size: TypeScale.caption, weight: .semibold))
                            .tracking(1.1)
                            .foregroundStyle(pal.textDim)
                            .padding(.horizontal, 20).padding(.top, 10).padding(.bottom, 2)
                        ForEach(list) { item in row(item) }
                    }
                }
                .padding(.bottom, 10)
            }
            .softScrollEdges()
        }
        .frame(width: 660, height: 440)
        .background(.regularMaterial)
    }

    private func row(_ item: Command) -> some View {
        let hot = hovered == item.id
        return Button {
            onPick(item)
        } label: {
            HStack(spacing: 12) {
                Image(systemName: item.systemImage)
                    .font(.system(size: TypeScale.body))
                    .foregroundStyle(hot ? accent : pal.textDim)
                    .frame(width: 20)
                VStack(alignment: .leading, spacing: 1) {
                    Text(item.title)
                        .font(.system(size: TypeScale.body, weight: .medium))
                        .foregroundStyle(pal.text)
                    Text(item.help)
                        .font(.system(size: TypeScale.micro))
                        .foregroundStyle(pal.textDim)
                }
                Spacer(minLength: 8)
                if let s = item.slash {
                    Text("/\(s)")
                        .font(.system(size: TypeScale.caption, design: .monospaced))
                        .foregroundStyle(accent)
                } else if let sc = item.shortcut {
                    Text(sc)
                        .font(.system(size: TypeScale.caption, weight: .semibold))
                        .foregroundStyle(pal.textDim)
                        .padding(.horizontal, 6).padding(.vertical, 2)
                        .background(pal.text.opacity(0.08),
                                    in: RoundedRectangle(cornerRadius: 5, style: .continuous))
                }
            }
            .padding(.horizontal, 12).padding(.vertical, 7)
            .background {
                if hot {
                    Color.clear.glassEffect(
                        Glass.regular.tint(accent.opacity(0.45)),
                        in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                }
            }
            .contentShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
            .padding(.horizontal, 8)
        }
        .buttonStyle(.plain)
        .onHover { hovered = $0 ? item.id : (hovered == item.id ? nil : hovered) }
    }
}
