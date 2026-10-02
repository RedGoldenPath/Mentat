import SwiftUI

/// The authoring studio: compose a generative scene live and preview it through
/// the element registry, and move the whole token graph in and out as W3C
/// `.tokens.json`. This is the interface editing its own vocabulary.
struct StudioPanel: View {
    @Environment(DesignStore.self) private var store: DesignStore?
    @Environment(\.palette) private var pal
    @State private var sceneText = StudioPanel.seed
    @State private var status = ""

    private var parsed: SceneSpec? { SceneParser.parse(sceneText) }

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            Text("STUDIO")
                .font(.system(size: 10, weight: .semibold)).tracking(1.1)
                .foregroundStyle(pal.textDim)

            Text("Scene (JSON) → preview")
                .font(.system(size: TypeScale.micro, weight: .semibold))
                .foregroundStyle(pal.textDim)
            TextEditor(text: $sceneText)
                .font(.system(size: TypeScale.caption, design: .monospaced))
                .scrollContentBackground(.hidden)
                .frame(height: 116)
                .padding(6)
                .surface(.tonal, corner: ChromeShape.radiusS)

            if let spec = parsed {
                SceneRenderer(spec: spec)
            } else {
                Text("Not a valid scene")
                    .font(.system(size: TypeScale.caption)).foregroundStyle(pal.bad)
            }

            FlowRow(spacing: 6) {
                studioButton("Copy W3C tokens") { copyTokens() }
                studioButton("Import W3C") { importTokens() }
                studioButton("Reset scene") { sceneText = StudioPanel.seed }
            }
            if !status.isEmpty {
                Text(status)
                    .font(.system(size: TypeScale.micro))
                    .foregroundStyle(pal.textDim)
                    .lineLimit(2)
            }
        }
        .padding(.horizontal, 14).padding(.vertical, 12)
        .surface(shape: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .stroke(pal.border.opacity(0.28), lineWidth: 1))
    }

    private func studioButton(_ title: String, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title)
                .font(.system(size: TypeScale.label, weight: .medium))
                .padding(.horizontal, 10).padding(.vertical, 6)
                .background(.ultraThinMaterial, in: Capsule(style: .continuous))
                .overlay(Capsule(style: .continuous).stroke(pal.border.opacity(0.3), lineWidth: 1))
        }
        .buttonStyle(.plain)
        .foregroundStyle(pal.text)
    }

    private func copyTokens() {
        guard let data = store?.exportW3CTokens(),
              let s = String(data: data, encoding: .utf8) else { return }
        copyToPasteboard(s)
        status = "Copied \(store?.graph.allPaths.count ?? 0) tokens as .tokens.json"
    }

    private func importTokens() {
        guard let s = NSPasteboard.general.string(forType: .string),
              let data = s.data(using: .utf8) else { status = "Clipboard is empty"; return }
        do {
            try store?.importW3CTokens(data)
            status = "Imported tokens"
        } catch {
            status = "Import failed: \(error)"
        }
    }

    static let seed = #"""
    {"title":"Studio demo","elements":[
      {"kind":"kpi","kpi":{"label":"Chunks indexed","value":"8,214","delta":"+1.2%","deltaUp":true}},
      {"kind":"chart","chart":{"style":"bar","title":"By work","series":[{"label":"Kojeve","value":9},{"label":"Hegel","value":6},{"label":"Dune","value":4}]}},
      {"kind":"diagram","diagram":{"title":"Flow","nodes":["route","retrieve","claims","sublate"]}}
    ]}
    """#
}
