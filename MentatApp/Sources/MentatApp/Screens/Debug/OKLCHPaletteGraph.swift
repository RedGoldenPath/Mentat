import SwiftUI

/// The `/debug` OKLCH view: the image's perceptual clusters as weighted bars,
/// the global hue / chroma / lightness, and the contrast-enforced theme roles
/// they resolve to.
struct OKLCHPaletteGraph: View {
    let palette: ImagePalette
    let theme: ColorTheme

    private var roles: [(String, Color)] {
        [
            ("bg", theme.background), ("surface", theme.surface), ("accent", theme.accent),
            ("ink", theme.ink), ("dim", theme.inkDim), ("border", theme.border),
            ("good", theme.good), ("bad", theme.bad),
        ]
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(
                String(
                    format: "hue %3.0f°  ·  chroma %.3f  ·  L %.2f  ·  %@%@",
                    palette.baseHue, palette.meanChroma, palette.meanLightness,
                    palette.isLight ? "light" : "dark",
                    palette.isNeutral ? " · neutral" : "")
            )
            .font(.system(size: 9.5, design: .monospaced))
            .foregroundStyle(.secondary)
            .lineLimit(1)

            if palette.clusters.isEmpty {
                Text("no analysis").font(.system(size: 10)).foregroundStyle(.secondary)
            } else {
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(Array(palette.clusters.enumerated()), id: \.offset) { _, c in
                        clusterRow(c)
                    }
                }
            }

            Text("ROLES").font(.system(size: 9, weight: .semibold)).foregroundStyle(.secondary)
            HStack(spacing: 3) {
                ForEach(Array(roles.enumerated()), id: \.offset) { _, r in
                    RoundedRectangle(cornerRadius: 3, style: .continuous)
                        .fill(r.1)
                        .frame(maxWidth: .infinity).frame(height: 16)
                        .overlay(
                            RoundedRectangle(cornerRadius: 3, style: .continuous)
                                .stroke(Color.white.opacity(0.14), lineWidth: 1))
                }
            }
        }
    }

    private func clusterRow(_ c: ImagePalette.Cluster) -> some View {
        HStack(spacing: 6) {
            RoundedRectangle(cornerRadius: 3, style: .continuous)
                .fill(c.color.color)
                .frame(width: 18, height: 14)
                .overlay(
                    RoundedRectangle(cornerRadius: 3, style: .continuous)
                        .stroke(Color.white.opacity(0.14), lineWidth: 1))
            Text(String(format: "L %.2f  C %.3f  H %3.0f°", c.color.l, c.color.c, c.color.h))
                .font(.system(size: 9.5, design: .monospaced))
                .foregroundStyle(.secondary)
            Spacer(minLength: 6)
            Text(String(format: "%.0f%%", c.weight * 100))
                .font(.system(size: 9.5, design: .monospaced))
                .foregroundStyle(.secondary)
            RoundedRectangle(cornerRadius: 2)
                .fill(Color.secondary.opacity(0.35))
                .frame(width: max(2, CGFloat(c.weight) * 90), height: 6)
        }
    }
}
