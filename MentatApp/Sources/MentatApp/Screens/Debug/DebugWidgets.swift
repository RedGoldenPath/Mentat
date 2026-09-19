import SwiftUI

/// The image's main colours as circles — the top three larger, the rest smaller
/// — so the palette's hierarchy reads at a glance.
struct PaletteSwatches: View {
    let colors: [Color]
    var bigCount: Int = 3
    var big: CGFloat = 20
    var small: CGFloat = 12

    var body: some View {
        HStack(spacing: 4) {
            ForEach(Array(colors.enumerated()), id: \.offset) { i, c in
                let d = i < bigCount ? big : small
                Circle()
                    .fill(c)
                    .frame(width: d, height: d)
                    .overlay(Circle().stroke(Color.white.opacity(0.18), lineWidth: 1))
            }
        }
        .frame(height: big)
    }
}

/// The `/debug` palette graph: the image's main colours as weighted bars, a hue
/// histogram, and the resulting palette roles.
struct PaletteGraph: View {
    let analysis: ImageAnalysis
    let palette: BackgroundPalette

    /// Roles ordered by how dominant their colour is in the image.
    private var rolesByDominance: [PaletteRole] {
        func dominance(_ c: Color) -> Double {
            let ns = NSColor(c)
            var best = 0.0
            for cl in analysis.clusters where PaletteAnalyzer.distance(ns, cl.color.nsColor) < 0.30
            {
                best = max(best, cl.weight)
            }
            return best
        }
        return PaletteRole.allCases
            .map { (role: $0, w: dominance(palette.color($0))) }
            .sorted { $0.w > $1.w }
            .map(\.role)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(
                String(
                    format:
                        "base %3.0f°  ·  weighted %3.0f°  ·  sat %2.0f%%  ·  bright %2.0f%%  ·  %@",
                    analysis.baseHue * 360, analysis.dominantHue * 360,
                    analysis.saturation * 100, analysis.brightness * 100, analysis.temperature)
            )
            .font(.system(size: TypeScale.meta, design: .monospaced))
            .foregroundStyle(.secondary)
            .lineLimit(1)

            if analysis.clusters.isEmpty {
                Text("no analysis").font(.system(size: 10)).foregroundStyle(.secondary)
            } else {
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(Array(analysis.clusters.enumerated()), id: \.offset) { _, c in
                        clusterRow(c)
                    }
                }
                hueBars
                HStack(spacing: 3) {
                    ForEach(Array(rolesByDominance.enumerated()), id: \.offset) { _, role in
                        RoundedRectangle(cornerRadius: 3, style: .continuous)
                            .fill(palette.color(role))
                            .frame(maxWidth: .infinity).frame(height: 14)
                            .overlay(
                                RoundedRectangle(cornerRadius: 3, style: .continuous)
                                    .stroke(Color.white.opacity(0.14), lineWidth: 1))
                    }
                }
            }
        }
    }

    private func clusterRow(_ c: ColorCluster) -> some View {
        let ns = c.color.nsColor
        var h: CGFloat = 0
        var s: CGFloat = 0
        var b: CGFloat = 0
        var a: CGFloat = 0
        ns.getHue(&h, saturation: &s, brightness: &b, alpha: &a)
        let lum = ColorTheory.luminance(ns)
        return HStack(spacing: 6) {
            RoundedRectangle(cornerRadius: 3, style: .continuous)
                .fill(c.color.color)
                .frame(width: 16, height: 12)
                .overlay(
                    RoundedRectangle(cornerRadius: 3, style: .continuous)
                        .stroke(Color.white.opacity(0.15), lineWidth: 1))
            GeometryReader { g in
                ZStack(alignment: .leading) {
                    Capsule().fill(Color.white.opacity(0.08))
                    Capsule().fill(c.color.color)
                        .frame(width: max(3, g.size.width * CGFloat(c.weight)))
                }
            }
            .frame(height: 11)
            Text(
                String(
                    format: "%3.0f%% h%3.0f s%2.0f l%2.0f",
                    c.weight * 100, h * 360, s * 100, lum * 100)
            )
            .font(.system(size: 8.5, design: .monospaced))
            .foregroundStyle(.secondary)
            .frame(width: 116, alignment: .leading)
        }
    }

    private var hueBars: some View {
        HStack(alignment: .bottom, spacing: 3) {
            ForEach(0..<12, id: \.self) { i in
                let v = analysis.hueHistogram.indices.contains(i) ? analysis.hueHistogram[i] : 0
                VStack(spacing: 2) {
                    RoundedRectangle(cornerRadius: 2, style: .continuous)
                        .fill(Color(hue: Double(i) / 12, saturation: 0.7, brightness: 0.85))
                        .frame(height: max(2, 26 * CGFloat(v)))
                    Text("\(i * 30)").font(.system(size: 7)).foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity)
            }
        }
    }
}
