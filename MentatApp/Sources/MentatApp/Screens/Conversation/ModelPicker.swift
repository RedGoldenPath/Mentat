import SwiftUI

/// The answer-model picker (Qwen-style), sitting where the model pill used to be.
/// Reads the model options from the engine's settings spec, so the list is the
/// server's, and refreshes health after a switch so the pill reflects reality.
struct ModelPicker: View {
    var engine: Engine
    @Environment(\.ink) private var ink
    @Environment(\.palette) private var pal

    private var models: [String] { engine.settingsOptions["model"] ?? [] }
    private var dot: Color {
        engine.busy ? pal.good
            : (engine.online ? ink(.center).opacity(0.7) : engine.accentColor(.center))
    }
    private var shadow: Color {
        engine.isLight(.center) ? Color.white.opacity(0.7) : Color.black.opacity(0.55)
    }

    var body: some View {
        Menu {
            if models.isEmpty {
                Button(engine.model.isEmpty ? "No model" : engine.model) {}
                    .disabled(true)
            } else {
                ForEach(models, id: \.self) { m in
                    Button {
                        Task {
                            await engine.setSetting("model", m)
                            await engine.checkHealth()
                        }
                    } label: {
                        if m == engine.model { Label(m, systemImage: "checkmark") } else { Text(m) }
                    }
                }
            }
        } label: {
            HStack(spacing: 6) {
                Circle()
                    .fill(dot)
                    .frame(width: 7, height: 7)
                    .shadow(color: shadow, radius: 3)
                Text(engine.model.isEmpty ? "engine" : engine.model)
                    .font(.system(size: TypeScale.caption, weight: .semibold, design: .monospaced))
                    .foregroundStyle(ink(.center))
                    .lineLimit(1)
                    .fixedSize()
                Image(systemName: "chevron.up.chevron.down")
                    .font(.system(size: 8, weight: .bold))
                    .foregroundStyle(ink(.center).opacity(0.6))
            }
            .padding(.horizontal, 9).padding(.vertical, 4)
            .liquid(corner: 11, interactive: true)
            .shadow(color: shadow.opacity(0.5), radius: 2, y: 1)
        }
        .menuStyle(.borderlessButton)
        .menuIndicator(.hidden)
        .fixedSize()
        .help("Answer model")
        .accessibilityLabel("Answer model")
    }
}
