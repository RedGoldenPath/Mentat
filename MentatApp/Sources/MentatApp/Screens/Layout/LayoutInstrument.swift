import SwiftUI

/// The user-facing Layout instrument: tune the armature *first* (presets,
/// margins, columns, baseline, guides), then the rest of the app composes into
/// it. Drag from the rulers to pull out guides; guides snap to the grid.
///
/// This is the "layout does the work" surface. The legacy feather + numeric
/// inspector remain the developer view; this is the authoring view.
struct LayoutInstrument: View {
    var store: LayoutGridStore
    @Binding var isOn: Bool

    @State private var snapEnabled = true
    @State private var pending: PendingGuide?

    private struct PendingGuide {
        var axis: GuideAxis
        var position: CGFloat
    }

    private let ruler: CGFloat = 22
    private var snap: SnapEngine { SnapEngine(enabled: snapEnabled) }

    var body: some View {
        GeometryReader { geo in
            let grid = store.grid
            let frame = grid.geometry(in: geo.size)
            let targets = snap.guides(for: grid, in: geo.size)

            ZStack(alignment: .topLeading) {
                // dim the app so the armature reads, and swallow stray clicks
                Rectangle().fill(.black.opacity(0.22))
                    .contentShape(Rectangle())
                    .onTapGesture {}

                armature(frame, grid: grid)
                guideLines(grid, targets: targets, size: geo.size)
                if let p = pending {
                    Rectangle().fill(Color.cyan.opacity(0.55))
                        .frame(
                            width: p.axis == .vertical ? 1 : geo.size.width,
                            height: p.axis == .vertical ? geo.size.height : 1
                        )
                        .position(
                            x: p.axis == .vertical ? p.position : geo.size.width / 2,
                            y: p.axis == .vertical ? geo.size.height / 2 : p.position
                        )
                        .allowsHitTesting(false)
                }
                rulerStrips(targets: targets, size: geo.size)
                panel
            }
            .coordinateSpace(name: "layoutCanvas")
        }
        .ignoresSafeArea()
        .transition(.opacity)
    }

    // MARK: armature

    private func armature(_ frame: LayoutGrid.Geometry, grid: LayoutGrid) -> some View {
        Canvas { ctx, _ in
            ctx.stroke(
                Path(roundedRect: frame.content, cornerRadius: 6),
                with: .color(.orange.opacity(0.65)), lineWidth: 1)

            if grid.showColumns {
                for (i, c) in frame.columns.enumerated() {
                    ctx.fill(
                        Path(roundedRect: c, cornerRadius: 3), with: .color(.blue.opacity(0.08)))
                    ctx.stroke(
                        Path(roundedRect: c, cornerRadius: 3),
                        with: .color(.blue.opacity(0.30)), lineWidth: 1)
                    ctx.draw(
                        Text("C\(i + 1)").font(.system(size: 8, design: .monospaced))
                            .foregroundColor(.cyan),
                        at: CGPoint(x: c.midX, y: max(12, frame.content.minY - 10)))
                }
            }
            if grid.showBaseline {
                for y in frame.baselineYs {
                    var p = Path()
                    p.move(to: CGPoint(x: frame.content.minX, y: y))
                    p.addLine(to: CGPoint(x: frame.content.maxX, y: y))
                    ctx.stroke(p, with: .color(.pink.opacity(0.18)), lineWidth: 0.5)
                }
            }
            // composition guides: rule of thirds, golden ratio, optical centre
            for f in grid.compositionFractions {
                let x = frame.content.minX + frame.content.width * f
                var v = Path()
                v.move(to: CGPoint(x: x, y: frame.content.minY))
                v.addLine(to: CGPoint(x: x, y: frame.content.maxY))
                ctx.stroke(v, with: .color(.green.opacity(0.30)), lineWidth: 1)
                let y = frame.content.minY + frame.content.height * f
                var h = Path()
                h.move(to: CGPoint(x: frame.content.minX, y: y))
                h.addLine(to: CGPoint(x: frame.content.maxX, y: y))
                ctx.stroke(h, with: .color(.green.opacity(0.30)), lineWidth: 1)
            }
        }
        .allowsHitTesting(false)
    }

    // MARK: guides

    private func guideLines(
        _ grid: LayoutGrid, targets: (x: [CGFloat], y: [CGFloat]),
        size: CGSize
    ) -> some View {
        ForEach(grid.guides) { g in
            let isV = g.axis == .vertical
            Rectangle()
                .fill(Color.cyan.opacity(0.85))
                .frame(width: isV ? 1 : size.width, height: isV ? size.height : 1)
                .frame(width: isV ? 11 : size.width, height: isV ? size.height : 11)
                .contentShape(Rectangle())
                .position(
                    x: isV ? g.position : size.width / 2,
                    y: isV ? size.height / 2 : g.position
                )
                .gesture(
                    DragGesture(minimumDistance: 0, coordinateSpace: .named("layoutCanvas"))
                        .onChanged { v in
                            let raw = isV ? v.location.x : v.location.y
                            let snapped = snap.snap(raw, to: isV ? targets.x : targets.y)
                            store.moveGuide(id: g.id, to: snapped)
                        }
                )
        }
    }

    // MARK: rulers

    private func rulerStrips(targets: (x: [CGFloat], y: [CGFloat]), size: CGSize) -> some View {
        ZStack(alignment: .topLeading) {
            // top ruler → pull out vertical guides
            rulerCanvas(length: size.width, axis: .vertical)
                .frame(width: size.width, height: ruler)
                .background(.ultraThinMaterial)
                .gesture(
                    DragGesture(minimumDistance: 0, coordinateSpace: .named("layoutCanvas"))
                        .onChanged { v in
                            pending = PendingGuide(
                                axis: .vertical,
                                position: snap.snap(v.location.x, to: targets.x))
                        }
                        .onEnded { v in
                            if let p = pending, v.location.y > ruler {
                                store.addGuide(p.axis, at: p.position)
                            }
                            pending = nil
                        }
                )
            // left ruler → pull out horizontal guides
            rulerCanvas(length: size.height, axis: .horizontal)
                .frame(width: ruler, height: size.height)
                .background(.ultraThinMaterial)
                .gesture(
                    DragGesture(minimumDistance: 0, coordinateSpace: .named("layoutCanvas"))
                        .onChanged { v in
                            pending = PendingGuide(
                                axis: .horizontal,
                                position: snap.snap(v.location.y, to: targets.y))
                        }
                        .onEnded { v in
                            if let p = pending, v.location.x > ruler {
                                store.addGuide(p.axis, at: p.position)
                            }
                            pending = nil
                        }
                )
            // corner
            Rectangle().fill(.ultraThinMaterial)
                .frame(width: ruler, height: ruler)
        }
    }

    private func rulerCanvas(length: CGFloat, axis: GuideAxis) -> some View {
        Canvas { ctx, size in
            let major = 100.0
            let minor = 20.0
            var v = 0.0
            while v <= length {
                let isMajor = v.truncatingRemainder(dividingBy: major) < 0.5
                let len = isMajor ? 8.0 : 4.0
                var p = Path()
                if axis == .vertical {
                    p.move(to: CGPoint(x: v, y: size.height - len))
                    p.addLine(to: CGPoint(x: v, y: size.height))
                    if isMajor {
                        ctx.draw(
                            Text("\(Int(v))").font(.system(size: 7, design: .monospaced))
                                .foregroundColor(.secondary), at: CGPoint(x: v + 9, y: 6))
                    }
                } else {
                    p.move(to: CGPoint(x: size.width - len, y: v))
                    p.addLine(to: CGPoint(x: size.width, y: v))
                    if isMajor {
                        ctx.draw(
                            Text("\(Int(v))").font(.system(size: 7, design: .monospaced))
                                .foregroundColor(.secondary), at: CGPoint(x: 3, y: v + 6))
                    }
                }
                ctx.stroke(p, with: .color(.secondary.opacity(0.6)), lineWidth: 0.5)
                v += minor
            }
        }
    }

    // MARK: panel

    private var panel: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("LAYOUT").font(.caption2).tracking(1).foregroundStyle(.secondary)
                Spacer()
                Button {
                    isOn = false
                } label: {
                    Text("Done")
                }
                .glassControl(.small)
            }

            presetRow

            group("Columns") {
                slider(int(\.columns), 1...24, "\(store.grid.columns)")
                slider(cgFloat(\.gutter), 0...64, "\(Int(store.grid.gutter))")
            }
            group("Rhythm") {
                slider(cgFloat(\.baseline), 0...48, "\(Int(store.grid.baseline))")
                slider(int(\.rows), 1...24, "\(store.grid.rows)")
            }
            group("Margins") {
                slider(margin(\.top), 0...120, "T \(Int(store.grid.margins.top))")
                slider(margin(\.leading), 0...120, "L \(Int(store.grid.margins.leading))")
                slider(margin(\.bottom), 0...120, "B \(Int(store.grid.margins.bottom))")
                slider(margin(\.trailing), 0...120, "R \(Int(store.grid.margins.trailing))")
            }

            HStack(spacing: 12) {
                Toggle("Columns", isOn: flag(\.showColumns)).toggleStyle(.checkbox)
                Toggle("Baseline", isOn: flag(\.showBaseline)).toggleStyle(.checkbox)
                Toggle("Snap", isOn: $snapEnabled).toggleStyle(.checkbox)
            }
            .font(.caption2)
            HStack(spacing: 12) {
                Toggle("Thirds", isOn: flag(\.showThirds)).toggleStyle(.checkbox)
                Toggle("Golden", isOn: flag(\.showGolden)).toggleStyle(.checkbox)
                Toggle("Centre", isOn: flag(\.showCenter)).toggleStyle(.checkbox)
            }
            .font(.caption2)

            HStack {
                Text("\(store.grid.guides.count) guides").font(.caption2).foregroundStyle(
                    .secondary)
                Spacer()
                Button("Reset") { store.reset() }
                    .glassControl(.small)
                    .help("Reset the armature to the default grid")
                Button("Clear") { store.clearGuides() }
                    .glassControl(.small)
                    .disabled(store.grid.guides.isEmpty)
            }
        }
        .padding(14)
        .frame(width: 286, alignment: .leading)
        .glassPanel(corner: 18)
        .padding(16)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topTrailing)
    }

    private var presetRow: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text("PRESETS").font(.caption2).tracking(0.6).foregroundStyle(.secondary)
            FlowRow(spacing: 5) {
                ForEach(LayoutGrid.Preset.allCases) { p in
                    Button(p.label) { store.apply(p) }
                        .glassControl(.mini)
                }
            }
        }
    }

    private func group<Content: View>(_ title: String, @ViewBuilder _ content: () -> Content)
        -> some View
    {
        VStack(alignment: .leading, spacing: 4) {
            Text(title.uppercased()).font(.caption2).tracking(0.6).foregroundStyle(.secondary)
            content()
        }
    }

    private func slider(_ value: Binding<Int>, _ range: ClosedRange<Int>, _ label: String)
        -> some View
    {
        HStack(spacing: 6) {
            Slider(
                value: Binding(
                    get: { Double(value.wrappedValue) },
                    set: { value.wrappedValue = Int($0.rounded()) }),
                in: Double(range.lowerBound)...Double(range.upperBound))
            Text(label).font(.system(size: 9, design: .monospaced))
                .foregroundStyle(.secondary).frame(width: 40, alignment: .trailing)
        }
    }

    private func slider(_ value: Binding<CGFloat>, _ range: ClosedRange<CGFloat>, _ label: String)
        -> some View
    {
        HStack(spacing: 6) {
            Slider(
                value: Binding(
                    get: { Double(value.wrappedValue) },
                    set: { value.wrappedValue = CGFloat($0) }),
                in: Double(range.lowerBound)...Double(range.upperBound))
            Text(label).font(.system(size: 9, design: .monospaced))
                .foregroundStyle(.secondary).frame(width: 40, alignment: .trailing)
        }
    }

    // MARK: bindings

    private func int(_ kp: WritableKeyPath<LayoutGrid, Int>) -> Binding<Int> {
        Binding(get: { store.grid[keyPath: kp] }, set: { store.grid[keyPath: kp] = $0 })
    }
    private func cgFloat(_ kp: WritableKeyPath<LayoutGrid, CGFloat>) -> Binding<CGFloat> {
        Binding(get: { store.grid[keyPath: kp] }, set: { store.grid[keyPath: kp] = $0 })
    }
    private func flag(_ kp: WritableKeyPath<LayoutGrid, Bool>) -> Binding<Bool> {
        Binding(get: { store.grid[keyPath: kp] }, set: { store.grid[keyPath: kp] = $0 })
    }
    private func margin(_ kp: WritableKeyPath<LayoutGrid.Margins, CGFloat>) -> Binding<CGFloat> {
        Binding(
            get: { store.grid.margins[keyPath: kp] }, set: { store.grid.margins[keyPath: kp] = $0 })
    }
}
