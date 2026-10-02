import SwiftUI

/// Engine/trajectory summary for the Developer scene, registered through the
/// `developerPanels` slot (not hard-coded into the scene). Reads the engine
/// observably, so the numbers track the live run.
struct EngineInfoPanel: View {
    var engine: Engine
    @Environment(\.palette) private var pal

    private var lastAnswer: ChatMessage? { engine.messages.last { $0.role == .assistant } }

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            Text("ENGINE")
                .font(.system(size: 10, weight: .semibold)).tracking(1.1)
                .foregroundStyle(pal.text.opacity(0.92))
                .padding(.horizontal, 13).padding(.vertical, 6)
                .background(.ultraThinMaterial, in: Capsule(style: .continuous))
                .overlay(Capsule(style: .continuous)
                    .stroke(Color.white.opacity(pal.isDark ? 0.14 : 0.5), lineWidth: 1))
            row("Model", engine.model)
            row("Status", engine.status)
            row("Build", engine.buildStamp)
            row("Look", engine.surfaceLook.label)
            if let m = lastAnswer?.meta {
                row("Route", m.route_reason ?? "—")
                row("Kind", m.kind?.uppercased() ?? "—")
                if let t = m.t_content { row("Answer", String(format: "%.1fs", t)) }
                if let tin = m.tokens_in, let tout = m.tokens_out {
                    row("Tokens", "\(tin) in · \(tout) out")
                }
            }
        }
        .padding(.horizontal, 14).padding(.vertical, 12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .surface(shape: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous)
            .stroke(pal.border.opacity(0.28), lineWidth: 1))
    }

    private func row(_ title: String, _ value: String) -> some View {
        HStack(spacing: 8) {
            Text(title)
                .font(.system(size: TypeScale.caption))
                .foregroundStyle(pal.textDim)
            Spacer(minLength: 8)
            Text(value.isEmpty ? "—" : value)
                .font(.system(size: TypeScale.caption, weight: .medium, design: .monospaced))
                .foregroundStyle(pal.text)
                .lineLimit(1)
        }
    }
}
