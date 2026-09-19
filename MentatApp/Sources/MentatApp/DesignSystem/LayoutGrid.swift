import CoreGraphics
import Foundation

// MARK: - Axis / guides

enum GuideAxis: String, Codable, Sendable { case vertical, horizontal }

/// A single alignment guide running across the layout frame.
struct LayoutGuide: Codable, Equatable, Identifiable, Sendable {
    var id = UUID()
    var axis: GuideAxis
    /// Position in points from the frame's leading (vertical) or top (horizontal).
    var position: CGFloat
    /// User-created guides can be moved/deleted; derived ones (margins, columns)
    /// cannot.
    var locked: Bool = false
}

// MARK: - LayoutGrid

/// The app's layout armature: margins, columns, baseline grid, row guides and an
/// optional pixel grid. One Codable model that *governs* placement — tunable in
/// Layout mode first, then consumed everywhere else (reading columns, sidebar,
/// composer, panels). The Affinity/InDesign "master page" idea.
struct LayoutGrid: Codable, Equatable, Sendable {
    struct Margins: Codable, Equatable, Sendable {
        var top: CGFloat
        var leading: CGFloat
        var bottom: CGFloat
        var trailing: CGFloat

        static let all = Margins(top: 20, leading: 20, bottom: 20, trailing: 20)
        init(top: CGFloat, leading: CGFloat, bottom: CGFloat, trailing: CGFloat) {
            self.top = top
            self.leading = leading
            self.bottom = bottom
            self.trailing = trailing
        }
        init(_ uniform: CGFloat) {
            self.init(top: uniform, leading: uniform, bottom: uniform, trailing: uniform)
        }
    }

    var margins: Margins = .all
    /// Number of equal-width text columns between the margins.
    var columns: Int = 9
    var gutter: CGFloat = 16
    /// Horizontal row bands (vertical rhythm reference, e.g. the inspector).
    var rows: Int = 8
    /// Baseline grid spacing in points. `0` disables it.
    var baseline: CGFloat = 12
    /// Where the baseline grid starts, offset from the top margin.
    var baselineOffset: CGFloat = 0
    /// Optional square pixel grid spacing (`nil` = off).
    var pixel: CGFloat? = nil
    /// Derived overlays the user can toggle independently of the armature.
    var showBaseline: Bool = true
    var showColumns: Bool = true
    /// Composition overlays — design principles the eye reads as balanced.
    var showThirds: Bool = true
    var showGolden: Bool = false
    var showCenter: Bool = true
    /// User-created guides, dragged in Layout mode.
    var guides: [LayoutGuide] = []

    static let `default` = LayoutGrid()

    /// Composition guide fractions (0…1 across the content frame): rule of
    /// thirds, golden ratio, and the optical centre.
    var compositionFractions: [Double] {
        var f: [Double] = []
        if showThirds { f += [1.0 / 3.0, 2.0 / 3.0] }
        if showGolden { f += [0.382, 0.618] }
        if showCenter { f += [0.5] }
        return f
    }

    // MARK: presets

    enum Preset: String, CaseIterable, Identifiable, Sendable {
        case bookOneColumn, bookTwoColumn, loose, tight
        var id: String { rawValue }
        var label: String {
            switch self {
            case .bookOneColumn: return "Book · 1 Column"
            case .bookTwoColumn: return "Book · 2 Column"
            case .loose: return "Loose"
            case .tight: return "Tight"
            }
        }
        var grid: LayoutGrid {
            switch self {
            case .bookOneColumn:
                return LayoutGrid(
                    margins: .init(top: 36, leading: 48, bottom: 28, trailing: 48),
                    columns: 3, gutter: 24, rows: 8, baseline: 12)
            case .bookTwoColumn:
                return LayoutGrid(
                    margins: .init(top: 32, leading: 40, bottom: 28, trailing: 40),
                    columns: 6, gutter: 20, rows: 8, baseline: 12)
            case .loose:
                return LayoutGrid(margins: .init(28), columns: 6, gutter: 20, rows: 6, baseline: 14)
            case .tight:
                return LayoutGrid(
                    margins: .init(16), columns: 12, gutter: 12, rows: 10, baseline: 10)
            }
        }
    }
}

// MARK: - Geometry

extension LayoutGrid {
    /// Resolved geometry for a given canvas size. All coordinates are in the
    /// canvas' own space (origin top-left, matching SwiftUI).
    struct Geometry {
        var content: CGRect
        var columnWidth: CGFloat
        var columns: [CGRect]
        var rows: [CGRect]
        var baselineYs: [CGFloat]
        var guides: [LayoutGuide]

        /// Vertical guide positions (column edges + margins + user guides).
        var verticalGuides: [CGFloat] {
            var x: [CGFloat] = [content.minX, content.maxX]
            for c in columns {
                x.append(c.minX)
                x.append(c.maxX)
            }
            x.append(contentsOf: guides.filter { $0.axis == .vertical }.map(\.position))
            return x
        }
        var horizontalGuides: [CGFloat] {
            var y: [CGFloat] = [content.minY, content.maxY]
            y.append(contentsOf: guides.filter { $0.axis == .horizontal }.map(\.position))
            y.append(contentsOf: baselineYs)
            return y
        }
    }

    /// Resolve the armature for a canvas. `topInset` nudges the content top down
    /// (masthead row); `bottomTrim` lifts the content bottom above the composer.
    func geometry(in size: CGSize, topInset: CGFloat = 0, bottomTrim: CGFloat? = nil) -> Geometry {
        let m = margins
        let top = m.top + max(0, topInset)
        let bottom = max(top, size.height - max(0, bottomTrim ?? m.bottom))
        let content = CGRect(
            x: m.leading, y: top,
            width: max(1, size.width - m.leading - m.trailing),
            height: max(1, bottom - top))

        let n = max(1, columns)
        let g = max(0, gutter)
        let colW = max(1, (content.width - g * CGFloat(n - 1)) / CGFloat(n))
        let cols: [CGRect] = (0..<n).map { i in
            CGRect(
                x: content.minX + CGFloat(i) * (colW + g), y: content.minY,
                width: colW, height: content.height)
        }

        let rn = max(1, rows)
        let rowH = max(1, (content.height - g * CGFloat(rn - 1)) / CGFloat(rn))
        let rowRects: [CGRect] = (0..<rn).map { j in
            CGRect(
                x: content.minX, y: content.minY + CGFloat(j) * (rowH + g),
                width: content.width, height: rowH)
        }

        var baselineYs: [CGFloat] = []
        if baseline > 2 {
            var y = content.minY + baselineOffset
            while y <= content.maxY {
                baselineYs.append(y)
                y += baseline
            }
        }

        return Geometry(
            content: content, columnWidth: colW, columns: cols,
            rows: rowRects, baselineYs: baselineYs, guides: guides)
    }

    /// Which column band a point falls in (`nil` when in a gutter or outside).
    func columnIndex(
        atX x: CGFloat, in size: CGSize, topInset: CGFloat = 0,
        bottomTrim: CGFloat? = nil
    ) -> Int? {
        let geo = geometry(in: size, topInset: topInset, bottomTrim: bottomTrim)
        return geo.columns.firstIndex { x >= $0.minX && x <= $0.maxX }
    }
}

// MARK: - SnapEngine

/// Snaps dragged values to the armature's guides (margins, column edges,
/// baseline, user guides, canvas centre/thirds). The "layout does the work" half
/// of the LayoutGrid idea.
struct SnapEngine: Sendable {
    /// How close (points) a value must be before it snaps.
    var threshold: CGFloat = 6
    var enabled: Bool = true

    /// Snap a horizontal position (x).
    func snapX(_ x: CGFloat, guides: [CGFloat]) -> CGFloat { snap(x, to: guides) }
    /// Snap a vertical position (y).
    func snapY(_ y: CGFloat, guides: [CGFloat]) -> CGFloat { snap(y, to: guides) }

    /// Nearest guide within `threshold`, else the original value.
    func snap(_ value: CGFloat, to guides: [CGFloat]) -> CGFloat {
        guard enabled, let best = guides.min(by: { abs($0 - value) < abs($1 - value) }),
            abs(best - value) <= threshold
        else { return value }
        return best
    }

    /// Guides for the current canvas, including useful derived targets the user
    /// expects in a layout tool (centre, thirds).
    func guides(
        for grid: LayoutGrid, in size: CGSize,
        topInset: CGFloat = 0, bottomTrim: CGFloat? = nil
    ) -> (x: [CGFloat], y: [CGFloat]) {
        let geo = grid.geometry(in: size, topInset: topInset, bottomTrim: bottomTrim)
        var xs = geo.verticalGuides
        var ys = geo.horizontalGuides
        for f in grid.compositionFractions {
            xs.append(geo.content.minX + geo.content.width * f)
            ys.append(geo.content.minY + geo.content.height * f)
        }
        xs.append(contentsOf: [size.width / 3, size.width / 2, size.width * 2 / 3])
        ys.append(contentsOf: [size.height / 3, size.height / 2, size.height * 2 / 3])
        return (xs.sorted(), ys.sorted())
    }
}
