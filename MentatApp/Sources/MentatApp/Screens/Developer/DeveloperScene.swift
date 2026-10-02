import SwiftUI

// MARK: - Developer scene (first-class; revealed by /debug or ⌥⌘D)

/// The Developer scene: diagnostics, the layout armature, the colour system,
/// the design-token editor and the advanced settings — kept out of the everyday
/// UI. Extra panels register through the `developerPanels` slot, so new tooling
/// never has to edit this file.
struct DeveloperScene: View {
    var engine: Engine
    let onClose: () -> Void
    @Environment(DesignStore.self) private var designStore: DesignStore?
    @State private var cmd = ""

    private var showGridBinding: Binding<Bool> {
        Binding(
            get: { designStore?.tokens.inspector.showGrid ?? false },
            set: { designStore?.tokens.inspector.showGrid = $0 })
    }

    private var chrome: ChromePalette { ChromePalette(engine, .right) }

    /// Everything that is *not* an everyday knob, grouped by server section.
    private var sections: [(String, [SettingSpec])] {
        SettingSection.group(engine.settingsSpec) { !SettingSpec.primaryKeys.contains($0.key) }
    }

    /// The server-side debug commands, from the one shared registry.
    private var tools: [Command] {
        CommandRegistry.all(debug: true).filter { $0.section == .debug && $0.isSlash }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            header
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    toolsSection
                    StudioPanel()
                    SandDebugPanel()
                    SlotView(key: .developerPanels)
                    gridSection
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
        .frame(width: min(372, TextStyle.maxMeasure() + 2 * PanelGrid.pad(16)))
        .frame(maxHeight: 680)
        .glassPanel(corner: PanelGrid.radius(16) + 6)
        .task { await engine.loadSettings() }
    }

    private var header: some View {
        HStack(spacing: 8) {
            Image(systemName: "hammer")
            Text("DEVELOPER").tracking(1.4)
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
            .help("Close developer scene (or type /debug off)")
            .accessibilityLabel("Close developer scene")
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
            .surface(shape: Capsule(style: .continuous))
            .overlay(
                Capsule(style: .continuous)
                    .stroke(Color.white.opacity(chrome.isLight ? 0.5 : 0.14), lineWidth: 1))
    }

    private var toolsSection: some View {
        VStack(alignment: .leading, spacing: 9) {
            chip("Tools")
            FlowRow(spacing: 6) {
                ForEach(tools) { t in
                    Button {
                        Task { await engine.runCommand(t.slash ?? "", "") }
                    } label: {
                        Label(t.title, systemImage: t.systemImage)
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
        .surface(shape: RoundedRectangle(cornerRadius: 16, style: .continuous))
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
