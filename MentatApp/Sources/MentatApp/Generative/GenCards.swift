import SwiftUI

/// Renders a generated `SceneSpec` through the element registry (kind → view).
/// Unknown kinds render a quiet fallback so a bad generation can never blank the
/// surrounding UI.
struct SceneRenderer: View {
    var spec: SceneSpec
    @Environment(\.palette) private var pal

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.s) {
            if let title = spec.title, !title.isEmpty {
                Text(title)
                    .font(.system(size: TypeScale.label, weight: .semibold))
                    .foregroundStyle(pal.textDim)
            }
            ForEach(spec.elements) { element in
                GenElementView(element: element)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct GenElementView: View {
    var element: GenElement
    @Environment(\.palette) private var pal

    var body: some View {
        switch element.kind {
        case .kpi:
            if let k = element.kpi { KPICard(kpi: k) } else { fallback }
        case .chart:
            if let c = element.chart { ChartCard(chart: c) } else { fallback }
        case .table:
            if let t = element.table { TableCard(table: t) } else { fallback }
        case .diagram:
            if let d = element.diagram { DiagramCard(diagram: d) } else { fallback }
        case .text:
            Text(element.text ?? "").font(.system(size: TypeScale.body)).foregroundStyle(pal.text)
        case .unknown:
            fallback
        }
    }

    private var fallback: some View {
        Text("Unsupported element")
            .font(.system(size: TypeScale.caption))
            .foregroundStyle(pal.textDim)
    }
}

struct KPICard: View {
    var kpi: GenElement.KPI
    @Environment(\.palette) private var pal

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(kpi.label.uppercased())
                .font(.system(size: TypeScale.micro, weight: .semibold)).tracking(0.8)
                .foregroundStyle(pal.textDim)
            Text(kpi.value)
                .font(.system(size: 26, weight: .semibold, design: .rounded))
                .foregroundStyle(pal.text)
            if let delta = kpi.delta {
                Text(delta)
                    .font(.system(size: TypeScale.caption, weight: .semibold))
                    .foregroundStyle((kpi.deltaUp ?? true) ? pal.good : pal.bad)
            }
        }
        .padding(Spacing.m)
        .frame(maxWidth: .infinity, alignment: .leading)
        .surface(.tonal, corner: ChromeShape.radiusS)
    }
}

struct ChartCard: View {
    var chart: GenElement.Chart
    @Environment(\.palette) private var pal
    @Environment(\.colorTheme) private var colorTheme

    private var maxValue: Double { max(0.0001, chart.series.map(\.value).max() ?? 1) }

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            if let title = chart.title, !title.isEmpty {
                Text(title).font(.system(size: TypeScale.caption, weight: .semibold))
                    .foregroundStyle(pal.textDim)
            }
            if chart.style == "line" { line } else { bars }
        }
        .padding(Spacing.m)
        .frame(maxWidth: .infinity, alignment: .leading)
        .surface(.tonal, corner: ChromeShape.radiusS)
    }

    private var bars: some View {
        GeometryReader { geo in
            let count = max(1, chart.series.count)
            let gap = Spacing.xs
            let barW = max(2, (geo.size.width - gap * CGFloat(count - 1)) / CGFloat(count))
            HStack(alignment: .bottom, spacing: gap) {
                ForEach(Array(chart.series.enumerated()), id: \.offset) { _, p in
                    VStack(spacing: 4) {
                        RoundedRectangle(cornerRadius: 3, style: .continuous)
                            .fill(colorTheme.accent.opacity(0.85))
                            .frame(height: max(2, geo.size.height * 0.72 * CGFloat(p.value / maxValue)))
                        Text(p.label)
                            .font(.system(size: TypeScale.micro))
                            .foregroundStyle(pal.textDim).lineLimit(1)
                    }
                    .frame(width: barW)
                }
            }
            .frame(maxHeight: .infinity, alignment: .bottom)
        }
        .frame(height: 120)
    }

    private var line: some View {
        GeometryReader { geo in
            let count = max(2, chart.series.count)
            let stepX = geo.size.width / CGFloat(count - 1)
            let h = geo.size.height * 0.85
            Path { path in
                for (i, p) in chart.series.enumerated() {
                    let x = CGFloat(i) * stepX
                    let y = h - h * CGFloat(p.value / maxValue)
                    if i == 0 { path.move(to: CGPoint(x: x, y: y)) }
                    else { path.addLine(to: CGPoint(x: x, y: y)) }
                }
            }
            .stroke(colorTheme.accent, style: StrokeStyle(lineWidth: 2, lineJoin: .round))
        }
        .frame(height: 120)
    }
}

struct TableCard: View {
    var table: GenElement.Table
    @Environment(\.palette) private var pal

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if let title = table.title, !title.isEmpty {
                Text(title).font(.system(size: TypeScale.caption, weight: .semibold))
                    .foregroundStyle(pal.textDim)
            }
            headerRow
            ForEach(Array(table.rows.prefix(40).enumerated()), id: \.offset) { _, row in
                HStack(spacing: Spacing.s) {
                    ForEach(Array(row.enumerated()), id: \.offset) { _, cell in
                        Text(cell)
                            .font(.system(size: TypeScale.caption))
                            .foregroundStyle(pal.text)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .lineLimit(2)
                    }
                }
                .padding(.vertical, 3)
                Divider().overlay(pal.border.opacity(0.25))
            }
        }
        .padding(Spacing.m)
        .frame(maxWidth: .infinity, alignment: .leading)
        .surface(.tonal, corner: ChromeShape.radiusS)
    }

    private var headerRow: some View {
        HStack(spacing: Spacing.s) {
            ForEach(Array(table.columns.enumerated()), id: \.offset) { _, col in
                Text(col.uppercased())
                    .font(.system(size: TypeScale.micro, weight: .semibold)).tracking(0.6)
                    .foregroundStyle(pal.textDim)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }
}

/// A minimal stacked-node diagram: nodes as chips, edges drawn as connecting
/// rules. Enough for model-authored flow/outline output; richer canvases come
/// with the HTML-app path.
struct DiagramCard: View {
    var diagram: GenElement.Diagram
    @Environment(\.palette) private var pal
    @Environment(\.colorTheme) private var colorTheme

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if let title = diagram.title, !title.isEmpty {
                Text(title).font(.system(size: TypeScale.caption, weight: .semibold))
                    .foregroundStyle(pal.textDim).padding(.bottom, 6)
            }
            ForEach(Array(diagram.nodes.enumerated()), id: \.offset) { i, node in
                HStack(alignment: .top, spacing: Spacing.xs) {
                    Circle().fill(colorTheme.accent.opacity(0.85)).frame(width: 8, height: 8)
                        .padding(.top, 5)
                    Text(node)
                        .font(.system(size: TypeScale.caption))
                        .foregroundStyle(pal.text)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                if i < diagram.nodes.count - 1 {
                    Rectangle().fill(pal.border.opacity(0.4))
                        .frame(width: 1.5, height: 12).padding(.leading, 3.5)
                }
            }
        }
        .padding(Spacing.m)
        .frame(maxWidth: .infinity, alignment: .leading)
        .surface(.tonal, corner: ChromeShape.radiusS)
    }
}
