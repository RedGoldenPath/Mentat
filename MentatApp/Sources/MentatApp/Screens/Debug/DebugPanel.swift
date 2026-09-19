import SwiftUI

// MARK: - Debug panel (hidden; revealed by /debug)

private struct DebugTool {
    let title: String
    let symbol: String
    let cmd: String
}

/// A floating panel of the app's niche mechanics — diagnostics, the layout
/// grid, and the advanced settings — kept out of the everyday UI. Typing
/// `/debug` reveals it; it is session-only, so quitting hides it again.
struct DebugPanel: View {
    var engine: Engine
    let onClose: () -> Void
    @Environment(DesignStore.self) private var designStore: DesignStore?
    @State private var cmd = ""
    @State private var debugImage = ""

    private var showGridBinding: Binding<Bool> {
        Binding(
            get: { designStore?.tokens.inspector.showGrid ?? false },
            set: { designStore?.tokens.inspector.showGrid = $0 })
    }

    private var chrome: ChromePalette { ChromePalette(engine, .right) }

    /// Everything that is *not* an everyday knob, grouped by server section.
    private var sections: [(String, [SettingSpec])] {
        var order: [String] = []
        var map: [String: [SettingSpec]] = [:]
        for s in engine.settingsSpec where !SettingSpec.primaryKeys.contains(s.key) {
            let sec = s.section ?? "Other"
            if map[sec] == nil {
                order.append(sec)
                map[sec] = []
            }
            map[sec]?.append(s)
        }
        return order.map { ($0, map[$0] ?? []) }
    }

    private let tools: [DebugTool] = [
        .init(title: "Health", symbol: "heart.text.square", cmd: "health"),
        .init(title: "Verify", symbol: "checkmark.seal", cmd: "verify"),
        .init(title: "Index", symbol: "square.stack.3d.up", cmd: "index"),
        .init(title: "Stats", symbol: "chart.bar", cmd: "stats"),
        .init(title: "Inventory", symbol: "list.bullet.rectangle", cmd: "inventory"),
        .init(title: "Served", symbol: "cpu", cmd: "served"),
        .init(title: "Graph", symbol: "point.3.connected.trianglepath.dotted", cmd: "graph"),
        .init(title: "Freq", symbol: "number", cmd: "freq"),
        .init(title: "Heal", symbol: "bandage", cmd: "heal"),
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            header
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    toolsSection
                    gridSection
                    paletteSection
                    DesignPanel()
                    PerfHUD()
                    ForEach(sections, id: \.0) { section, specs in
                        VStack(alignment: .leading, spacing: 9) {
                            chip(section)
                            ForEach(specs) { spec in
                                SettingRow(engine: engine, spec: spec, chrome: chrome)
                            }
                        }
                    }
                }
                .padding(.bottom, 2)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .softScrollEdges()
        }
        .padding(16)
        .frame(width: min(344, TextStyle.maxMeasure() + 2 * PanelGrid.pad(16)))
        .frame(maxHeight: 620)
        .glassPanel(corner: PanelGrid.radius(16) + 6)
        .task { await engine.loadSettings() }
    }

    private var header: some View {
        HStack(spacing: 8) {
            Image(systemName: "ladybug")
            Text("DEBUG").tracking(1.4)
            Text(engine.buildStamp)
                .font(.system(size: TypeScale.micro, design: .monospaced))
                .foregroundStyle(chrome.dim)
                .lineLimit(1)
            Spacer()
            Button(action: onClose) {
                Image(systemName: "xmark")
                    .font(.system(size: TypeScale.label, weight: .semibold))
                    .contentShape(Rectangle())
            }
            .glassControl(.small, shape: .circle)
            .help("Close debug (or type /debug off)")
            .accessibilityLabel("Close debug")
        }
        .font(.system(size: TypeScale.label, weight: .semibold))
        .foregroundStyle(chrome.ink)
    }

    private func chip(_ title: String) -> some View {
        Text(title.uppercased())
            .font(.system(size: 10, weight: .semibold)).tracking(1.1)
            .foregroundStyle(chrome.ink.opacity(0.92))
            .lineLimit(1)
            .padding(.horizontal, 13).padding(.vertical, 6)
            .background(.ultraThinMaterial, in: Capsule(style: .continuous))
            .overlay(
                Capsule(style: .continuous)
                    .stroke(Color.white.opacity(chrome.isLight ? 0.5 : 0.14), lineWidth: 1))
    }

    private var toolsSection: some View {
        VStack(alignment: .leading, spacing: 9) {
            chip("Tools")
            FlowRow(spacing: 6) {
                ForEach(tools, id: \.cmd) { t in
                    Button {
                        Task { await engine.runCommand(t.cmd, "") }
                    } label: {
                        Label(t.title, systemImage: t.symbol)
                            .font(.system(size: TypeScale.label, weight: .medium))
                            .padding(.horizontal, 10).padding(.vertical, 6)
                            .background(.ultraThinMaterial, in: Capsule(style: .continuous))
                            .overlay(
                                Capsule(style: .continuous).stroke(
                                    chrome.dim.opacity(0.3), lineWidth: 1))
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(chrome.ink)
                }
            }
            HStack(spacing: 8) {
                TextField("run command…   e.g. search dune", text: $cmd)
                    .textFieldStyle(.plain)
                    .font(.system(size: TypeScale.label, design: .monospaced))
                    .onSubmit(runTyped)
                Button(action: runTyped) {
                    Image(systemName: "return").font(.system(size: 10, weight: .bold))
                }
                .buttonStyle(.plain)
                .disabled(cmd.trimmingCharacters(in: .whitespaces).isEmpty)
            }
            .foregroundStyle(chrome.ink)
            .padding(.horizontal, 12).padding(.vertical, 8)
            .background(SettingPill(isLight: chrome.isLight))
        }
    }

    private var gridSection: some View {
        VStack(alignment: .leading, spacing: 9) {
            chip("Grid & Armature")
            Toggle("Show grid overlay", isOn: showGridBinding)
                .toggleStyle(.checkbox)
                .font(.system(size: TypeScale.label))
                .foregroundStyle(chrome.ink)
            ArmaturePanel()
        }
        .padding(.horizontal, 14).padding(.vertical, 12)
        .background(
            .ultraThinMaterial,
            in: RoundedRectangle(cornerRadius: 16, style: .continuous)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .stroke(chrome.dim.opacity(0.28), lineWidth: 1))
    }

    /// Debug: the image's OKLCH clusters and the contrast-enforced theme they
    /// resolve to, for any background image.
    private var paletteSection: some View {
        let name = debugImage.isEmpty ? engine.backgroundName : debugImage
        let palette = engine.palette(for: debugImage.isEmpty ? engine.backgroundName : debugImage)
        let resolved = ColorResolver.theme(for: palette, controls: engine.colorControls)
        return VStack(alignment: .leading, spacing: 9) {
            chip("Colour system · OKLCH")
            Menu(name.isEmpty ? "—" : name) {
                ForEach(engine.backgrounds, id: \.self) { b in
                    Button(b) { debugImage = b }
                }
            }
            .menuStyle(.borderlessButton)
            .font(.system(size: TypeScale.label, design: .monospaced))
            .foregroundStyle(chrome.ink)
            OKLCHPaletteGraph(palette: palette, theme: resolved)
        }
        .padding(.horizontal, 14).padding(.vertical, 12)
        .background(
            .ultraThinMaterial,
            in: RoundedRectangle(cornerRadius: 16, style: .continuous)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .stroke(chrome.dim.opacity(0.28), lineWidth: 1))
    }

    private func runTyped() {
        let raw = cmd.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !raw.isEmpty else { return }
        let body = raw.hasPrefix("/") ? String(raw.dropFirst()) : raw
        let parts = body.split(separator: " ", maxSplits: 1, omittingEmptySubsequences: false)
        let c = parts.first.map(String.init) ?? ""
        let arg = parts.count > 1 ? String(parts[1]) : ""
        cmd = ""
        Task { await engine.runCommand(c, arg) }
    }
}
