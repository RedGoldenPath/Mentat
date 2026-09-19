import SwiftUI

/// The layout armature as a reusable panel: presets, margins, baseline, rows,
/// guides, the grid mask's fade/band, and a way into full-screen Layout mode.
/// Shown in the debug menu (and anywhere else the armature is tuned).
struct ArmaturePanel: View {
    @AppStorage("layoutMode") private var layoutMode = false
    @Environment(\.colorTheme) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Tune the armature first — then everything composes into it.")
                .font(.caption2)
                .foregroundStyle(theme.inkDim)
                .fixedSize(horizontal: false, vertical: true)

            Button {
                layoutMode = true
            } label: {
                Label("Open Layout mode", systemImage: "arrow.up.left.and.arrow.down.right")
                    .frame(maxWidth: .infinity)
            }
            .glassControl(.regular, tint: theme.accent)
            .help("Full-screen armature: rulers, guides, snapping (⌥⌘G)")

            GridControlsContent()
                .foregroundStyle(theme.ink)
        }
    }
}
