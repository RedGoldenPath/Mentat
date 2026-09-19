import SwiftUI

/// A numbered layout grid you can tune live. Meant for "inspect element"-style
/// alignment: read the numbers, then tell me which ones to change.
struct GridOverlay: View {
    /// Size of the whole window, so we can show how the page layer sits inside
    /// it once the sidebar is open.
    var windowSize: CGSize = .zero
    @AppStorage("gridCols") private var cols = 9
    @AppStorage("gridGutter") private var gutter = 16.0
    @AppStorage("gridMargin") private var margin = 20.0
    @AppStorage("gridBaseline") private var baseline = 12.0
    @AppStorage("gridRows") private var rows = 8
    @Environment(DesignStore.self) private var designStore: DesignStore?
    private var inspector: DesignTokens.Inspector { designStore?.tokens.inspector ?? .init() }
    private var numbers: Bool { inspector.numbers }
    private var headerHeight: Double { inspector.headerHeight }
    private var scope: String { inspector.scope }  // layer | window | both

    private var showLayer: Bool { scope == "layer" || scope == "both" }
    private var showWindow: Bool { scope == "window" || scope == "both" }

    var body: some View {
        GeometryReader { geo in
            let W = geo.size.width
            let H = geo.size.height
            let m = CGFloat(margin)
            let g = CGFloat(gutter)
            let n = max(1, cols)
            let content = max(20, W - m * 2)
            let colW = max(2, (content - g * CGFloat(n - 1)) / CGFloat(n))
            let winW = windowSize.width > 0 ? windowSize.width : W
            let winH = windowSize.height > 0 ? windowSize.height : H
            let winLeft = -(winW - W)  // window's left edge in this layer's space

            ZStack(alignment: .topLeading) {
                Canvas { ctx, size in
                    // ---- window reference grid: where the real window is ----
                    if showWindow {
                        let wcontent = max(20, winW - m * 2)
                        let wcolW = max(2, (wcontent - g * CGFloat(n - 1)) / CGFloat(n))
                        for i in 0..<n {
                            let x = winLeft + m + CGFloat(i) * (wcolW + g)
                            let r = CGRect(x: x, y: m, width: wcolW, height: winH - m * 2)
                            ctx.stroke(
                                Path(roundedRect: r, cornerRadius: 3),
                                with: .color(Color.gray.opacity(0.45)), lineWidth: 1)
                            if numbers {
                                ctx.draw(
                                    Text("W\(i + 1)")
                                        .font(.system(size: 8, design: .monospaced))
                                        .foregroundColor(.gray),
                                    at: CGPoint(x: x + wcolW / 2, y: m + 26))
                            }
                        }
                        ctx.stroke(
                            Path(
                                CGRect(x: winLeft + m, y: m, width: wcontent, height: winH - m * 2)),
                            with: .color(Color.gray.opacity(0.6)), lineWidth: 1)
                        if numbers {
                            ctx.draw(
                                Text("window \(Int(winW))×\(Int(winH))")
                                    .font(.system(size: 9, design: .monospaced)).foregroundColor(
                                        .gray),
                                at: CGPoint(x: winLeft + winW / 2, y: max(10, m - 4)))
                        }
                    }

                    // ---- layer grid: what the app actually lays out to ----
                    if showLayer {
                        // column bands
                        for i in 0..<n {
                            let x = m + CGFloat(i) * (colW + g)
                            let r = CGRect(x: x, y: m, width: colW, height: size.height - m * 2)
                            ctx.fill(
                                Path(roundedRect: r, cornerRadius: 3),
                                with: .color(Color.blue.opacity(0.10)))
                            ctx.stroke(
                                Path(roundedRect: r, cornerRadius: 3),
                                with: .color(Color.blue.opacity(0.30)), lineWidth: 1)
                            if numbers {
                                ctx.draw(
                                    Text("C\(i + 1)\n\(Int(colW))")
                                        .font(.system(size: 8, design: .monospaced))
                                        .foregroundColor(.cyan),
                                    at: CGPoint(x: x + colW / 2, y: m + 12))
                            }
                        }
                        // row bands (vertical axis — mirrors the column bands)
                        let rowsN = max(1, rows)
                        let contentH = max(20, size.height - m * 2)
                        let rowH = max(2, (contentH - g * CGFloat(rowsN - 1)) / CGFloat(rowsN))
                        for j in 0..<rowsN {
                            let y = m + CGFloat(j) * (rowH + g)
                            let rr = CGRect(x: m, y: y, width: content, height: rowH)
                            ctx.fill(
                                Path(roundedRect: rr, cornerRadius: 3),
                                with: .color(Color.teal.opacity(0.07)))
                            ctx.stroke(
                                Path(roundedRect: rr, cornerRadius: 3),
                                with: .color(Color.teal.opacity(0.22)), lineWidth: 1)
                            if numbers {
                                ctx.draw(
                                    Text("R\(j + 1)  \(Int(rowH))")
                                        .font(.system(size: 8, design: .monospaced))
                                        .foregroundColor(.teal),
                                    at: CGPoint(x: m + 40, y: y + rowH / 2))
                            }
                        }

                        // baseline + row numbers
                        if baseline > 2 {
                            var y = m
                            var row = 0
                            while y < size.height - m {
                                var p = Path()
                                p.move(to: CGPoint(x: m, y: y))
                                p.addLine(to: CGPoint(x: size.width - m, y: y))
                                ctx.stroke(
                                    p, with: .color(Color.pink.opacity(0.16)), lineWidth: 0.5)
                                if numbers {
                                    ctx.draw(
                                        Text("\(row)")
                                            .font(.system(size: 7, design: .monospaced))
                                            .foregroundColor(.pink),
                                        at: CGPoint(x: max(8, m - 10), y: y))
                                }
                                y += CGFloat(baseline)
                                row += 1
                            }
                        }
                        // horizontal layout guides — the page rows as I see them
                        let rows: [(String, CGFloat)] = [
                            ("top", m),
                            ("header", CGFloat(headerHeight)),
                            ("content top", 96),
                            ("1/3", size.height / 3),
                            ("mid", size.height / 2),
                            ("2/3", size.height * 2 / 3),
                            ("content btm", size.height - 96),
                            ("composer", size.height - 68),
                            ("bottom", size.height - m),
                        ]
                        for (name, y) in rows {
                            var p = Path()
                            p.move(to: CGPoint(x: 0, y: y))
                            p.addLine(to: CGPoint(x: size.width, y: y))
                            ctx.stroke(p, with: .color(Color.yellow.opacity(0.35)), lineWidth: 1)
                            if numbers {
                                ctx.draw(
                                    Text("\(name) \(Int(y))")
                                        .font(.system(size: 8, design: .monospaced))
                                        .foregroundColor(.yellow),
                                    at: CGPoint(x: size.width - 66, y: max(8, y - 7)))
                            }
                        }

                        // margin box
                        ctx.stroke(
                            Path(
                                roundedRect: CGRect(
                                    x: m, y: m, width: content, height: size.height - m * 2),
                                cornerRadius: 4),
                            with: .color(Color.orange.opacity(0.55)), lineWidth: 1)
                        // thirds + center
                        for (f, c) in [
                            (1.0 / 3.0, Color.green.opacity(0.30)),
                            (2.0 / 3.0, Color.green.opacity(0.30)),
                            (0.5, Color.red.opacity(0.40)),
                        ] {
                            var v = Path()
                            v.move(to: CGPoint(x: size.width * f, y: 0))
                            v.addLine(to: CGPoint(x: size.width * f, y: size.height))
                            ctx.stroke(v, with: .color(c), lineWidth: 1)
                        }
                        // readouts
                        if numbers {
                            ctx.draw(
                                Text(
                                    "layer \(Int(W))×\(Int(H))   cols \(n)   gutter \(Int(g))   margin \(Int(m))   baseline \(Int(baseline))   colW \(Int(colW))"
                                )
                                .font(.system(size: 10, design: .monospaced))
                                .foregroundColor(.orange),
                                at: CGPoint(x: size.width / 2, y: 12))
                            // margin edge numbers
                            ctx.draw(
                                Text("\(Int(m))").font(.system(size: 8, design: .monospaced))
                                    .foregroundColor(.orange),
                                at: CGPoint(x: m, y: size.height - 8))
                            ctx.draw(
                                Text("\(Int(W - m))").font(.system(size: 8, design: .monospaced))
                                    .foregroundColor(.orange),
                                at: CGPoint(x: W - m, y: size.height - 8))
                            ctx.draw(
                                Text("\(Int(m))").font(.system(size: 8, design: .monospaced))
                                    .foregroundColor(.orange),
                                at: CGPoint(x: 8, y: m))
                        }
                    }

                    // layer boundary lines, so the sidebar push is obvious
                    for x in [CGFloat(0), W] {
                        var p = Path()
                        p.move(to: CGPoint(x: x, y: 0))
                        p.addLine(to: CGPoint(x: x, y: size.height))
                        ctx.stroke(p, with: .color(Color.white.opacity(0.22)), lineWidth: 1)
                    }
                }
                .allowsHitTesting(false)

                if numbers { GridControls() }
            }
        }
        .ignoresSafeArea(edges: .top)
    }
}

/// A quiet, always-on layer of thin white lines that trace the layout grid.
/// It sits *underneath* the UI (above the page art) and is bound to the same
/// grid settings, so it breathes with the columns and rows.
struct GridLinesLayer: View {
    /// Extra space below the margin — the content rows start under the masthead
    /// row rather than being squeezed by it.
    var topInset: CGFloat = 0
    /// How far above the bottom edge the grid stops. Keeps the last row clear of
    /// the composer instead of clipping into the input box. `nil` = plain margin.
    var bottomTrim: CGFloat? = nil

    @AppStorage("gridCols") private var cols = 9
    @AppStorage("gridGutter") private var gutter = 16.0
    @AppStorage("gridMargin") private var margin = 20.0
    @AppStorage("gridRows") private var rows = 8
    @AppStorage("gridBaseline") private var baseline = 12.0
    @Environment(DesignStore.self) private var designStore: DesignStore?
    private var inspector: DesignTokens.Inspector { designStore?.tokens.inspector ?? .init() }
    private var linesOn: Bool { inspector.showLines }
    private var lineOpacity: Double { inspector.lineOpacity }
    /// Height of the clean "hole" in the middle of the grid, in grid boxes
    /// (one box = `gridBaseline`).
    private var bandBoxes: Double { inspector.lineBand }
    /// Width of the fade at each end of the hole, in grid boxes (0 = hard edge).
    private var featherBoxes: Double { inspector.lineFeather }

    var body: some View {
        if linesOn {
            GeometryReader { geo in
                let m = CGFloat(margin)
                let g = CGFloat(gutter)
                let n = max(1, cols)
                let content = max(20, geo.size.width - m * 2)
                let colW = max(2, (content - g * CGFloat(n - 1)) / CGFloat(n))
                let op = max(0, min(1, lineOpacity))
                // the grid proper lives between the masthead row and the composer
                let top = m + max(0, topInset)
                let bottom = geo.size.height - max(0, bottomTrim ?? m)
                let h = max(0, bottom - top)

                // Feathered band: 40 boxes tall, centred on the grid, one box of
                // feather at each end, fading opacity to zero.
                let H = max(1, geo.size.height)
                let box = max(2, CGFloat(baseline))
                let band = max(0, CGFloat(bandBoxes) * box)
                let mid = (top + bottom) / 2
                let feather = max(2, box * max(0, CGFloat(featherBoxes)))
                let at: (CGFloat) -> CGFloat = { max(0, min(1, $0 / H)) }
                let s0 = at(mid - band / 2 - feather)
                let s1 = at(mid - band / 2 + feather)
                let s2 = at(mid + band / 2 - feather)
                let s3 = at(mid + band / 2 + feather)

                Canvas { ctx, _ in
                    // the column bands read a touch brighter than the raw value
                    let line = Color.white.opacity(min(1, op * 1.9))

                    // column bands — stroked so the gutters read as gaps
                    for i in 0..<n {
                        let x = m + CGFloat(i) * (colW + g)
                        let r = CGRect(x: x, y: top, width: colW, height: h)
                        ctx.stroke(
                            Path(roundedRect: r, cornerRadius: 6),
                            with: .color(line), lineWidth: 1.0)
                    }
                    // margin frame ties it together
                    ctx.stroke(
                        Path(
                            roundedRect: CGRect(x: m, y: top, width: content, height: h),
                            cornerRadius: 6),
                        with: .color(line), lineWidth: 1.0)
                }
                .mask(
                    LinearGradient(
                        stops: [
                            .init(color: .white, location: 0),
                            .init(color: .white, location: max(0, min(s0, 1))),
                            .init(color: .white.opacity(0), location: max(s0, min(s1, 1))),
                            .init(color: .white.opacity(0), location: max(s1, min(s2, 1))),
                            .init(color: .white, location: max(s2, min(s3, 1))),
                            .init(color: .white, location: 1),
                        ], startPoint: .top, endPoint: .bottom)
                )
                .allowsHitTesting(false)
            }
            .ignoresSafeArea(edges: .top)
        }
    }
}

/// The bare grid controls, with no panel chrome, so they can be dropped into
/// another surface (the debug panel) or wrapped by `GridControls`.
///
/// When a `LayoutGridStore` is in the environment (the normal app), these drive
/// the live armature — presets, margins, baseline, guides. Without one (e.g. a
/// preview) they fall back to the legacy `@AppStorage` keys.
struct GridControlsContent: View {
    @Environment(LayoutGridStore.self) private var layoutStore: LayoutGridStore?
    @Environment(DesignStore.self) private var designStore: DesignStore?
    @AppStorage("gridCols") private var cols = 9
    @AppStorage("gridGutter") private var gutter = 16.0
    @AppStorage("gridMargin") private var margin = 20.0
    @AppStorage("gridBaseline") private var baseline = 12.0
    @AppStorage("gridRows") private var rows = 8

    /// The grid-display tokens (data-driven), with a constant fallback for
    /// previews without a store.
    private func ins<T>(_ kp: WritableKeyPath<DesignTokens.Inspector, T>, _ fallback: T) -> Binding<
        T
    > {
        Binding(
            get: { designStore?.tokens.inspector[keyPath: kp] ?? fallback },
            set: { designStore?.tokens.inspector[keyPath: kp] = $0 })
    }

    var body: some View {
        VStack(alignment: .leading, spacing: PanelGrid.gap(gutter)) {
            Picker("Scope", selection: ins(\.scope, "both")) {
                Text("Layer").tag("layer")
                Text("Window").tag("window")
                Text("Both").tag("both")
            }
            .pickerStyle(.segmented)
            Divider()

            if let store = layoutStore {
                armatureControls(store)
            } else {
                legacyControls
            }

            Stepper(
                "Header   \(Int(designStore?.tokens.inspector.headerHeight ?? 68))",
                value: ins(\.headerHeight, 68), in: 40...140, step: 4)
            Toggle("Lines", isOn: ins(\.showLines, true)).toggleStyle(.checkbox)
            if designStore?.tokens.inspector.showLines ?? true {
                Stepper(
                    "Opacity  \(Int((designStore?.tokens.inspector.lineOpacity ?? 0.18) * 100))%",
                    value: ins(\.lineOpacity, 0.18), in: 0.02...0.5, step: 0.02)
                sliderRow(
                    "Fade", value: ins(\.lineFeather, 1), range: 0...6, step: 0.5, format: "%.1f×")
                sliderRow(
                    "Band", value: ins(\.lineBand, 40), range: 0...120, step: 4, format: "%.0f")
            }
            Toggle("Numbers", isOn: ins(\.numbers, true)).toggleStyle(.checkbox)
        }
        .font(.system(size: 11, design: .monospaced))
    }

    /// A compact labelled slider row for the mask controls.
    private func sliderRow(
        _ label: String, value: Binding<Double>,
        range: ClosedRange<Double>, step: Double,
        format: String
    ) -> some View {
        HStack(spacing: 6) {
            Text(label).frame(width: 52, alignment: .leading)
            Slider(value: value, in: range, step: step)
            Text(String(format: format, value.wrappedValue))
                .foregroundStyle(.secondary).frame(width: 40, alignment: .trailing)
        }
    }

    // MARK: live armature

    @ViewBuilder
    private func armatureControls(_ store: LayoutGridStore) -> some View {
        Text("ARMATURE").font(.system(size: 9, weight: .semibold)).foregroundStyle(.secondary)
        FlowRow(spacing: 4) {
            ForEach(LayoutGrid.Preset.allCases) { p in
                Button(p.label) { store.apply(p) }
                    .font(.system(size: 10))
                    .buttonStyle(.bordered)
                    .controlSize(.mini)
            }
        }
        Stepper("Columns  \(store.grid.columns)", value: int(store, \.columns), in: 1...24)
        Stepper(
            "Gutter   \(Int(store.grid.gutter))", value: cg(store, \.gutter), in: 0...64, step: 4)
        Stepper(
            "Baseline \(Int(store.grid.baseline))", value: cg(store, \.baseline), in: 0...48,
            step: 2)
        Stepper("Rows     \(store.grid.rows)", value: int(store, \.rows), in: 1...24)
        Stepper(
            "Top      \(Int(store.grid.margins.top))", value: mg(store, \.top), in: 0...120, step: 4
        )
        Stepper(
            "Leading  \(Int(store.grid.margins.leading))", value: mg(store, \.leading), in: 0...120,
            step: 4)
        Stepper(
            "Bottom   \(Int(store.grid.margins.bottom))", value: mg(store, \.bottom), in: 0...120,
            step: 4)
        Stepper(
            "Trailing \(Int(store.grid.margins.trailing))", value: mg(store, \.trailing),
            in: 0...120, step: 4)
        HStack {
            Text("\(store.grid.guides.count) guides")
            Spacer()
            Button("Clear") { store.clearGuides() }
                .controlSize(.mini)
                .disabled(store.grid.guides.isEmpty)
        }
        Divider()
    }

    private var legacyControls: some View {
        Group {
            Stepper("Columns  \(cols)", value: $cols, in: 1...24)
            Stepper("Gutter   \(Int(gutter))", value: $gutter, in: 0...64, step: 4)
            Stepper("Margin   \(Int(margin))", value: $margin, in: 0...80, step: 4)
            Stepper("Baseline \(Int(baseline))", value: $baseline, in: 0...48, step: 2)
            Stepper("Rows     \(rows)", value: $rows, in: 1...24)
        }
    }

    // MARK: bindings

    private func int(_ s: LayoutGridStore, _ kp: WritableKeyPath<LayoutGrid, Int>) -> Binding<Int> {
        Binding(get: { s.grid[keyPath: kp] }, set: { s.grid[keyPath: kp] = $0 })
    }
    private func cg(_ s: LayoutGridStore, _ kp: WritableKeyPath<LayoutGrid, CGFloat>) -> Binding<
        CGFloat
    > {
        Binding(get: { s.grid[keyPath: kp] }, set: { s.grid[keyPath: kp] = $0 })
    }
    private func mg(_ s: LayoutGridStore, _ kp: WritableKeyPath<LayoutGrid.Margins, CGFloat>)
        -> Binding<CGFloat>
    {
        Binding(get: { s.grid.margins[keyPath: kp] }, set: { s.grid.margins[keyPath: kp] = $0 })
    }
}

/// Small floating panel to change the grid itself.
struct GridControls: View {
    @AppStorage("gridGutter") private var gutter = 16.0

    var body: some View {
        VStack(alignment: .leading, spacing: PanelGrid.gap(gutter)) {
            Text("Grid").font(.caption).bold()
            Divider()
            GridControlsContent()
        }
        .font(.system(size: 11, design: .monospaced))
        .frame(width: 220, alignment: .leading)
        .padding(PanelGrid.pad(gutter))
        .glassPanel(corner: PanelGrid.radius(gutter))
        .padding(.trailing, PanelGrid.pad(gutter))
        // vertically centred on the trailing edge, clear of the C7 menu
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .trailing)
    }
}
