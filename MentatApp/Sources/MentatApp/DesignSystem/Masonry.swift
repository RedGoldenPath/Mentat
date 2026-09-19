import SwiftUI

/// A wrapping row: subviews flow left-to-right and wrap to the next line, hugging
/// the content (so a chip/citation bubble never spans the frame). Used by the
/// citation chips.
struct FlowRow: Layout {
    var spacing: CGFloat = 6

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let maxW = proposal.width ?? .infinity
        var x: CGFloat = 0
        var y: CGFloat = 0
        var rowH: CGFloat = 0
        var used: CGFloat = 0
        for v in subviews {
            let s = v.sizeThatFits(.unspecified)
            if x + s.width > maxW && x > 0 {
                used = max(used, x - spacing)
                x = 0
                y += rowH + spacing
                rowH = 0
            }
            x += s.width + spacing
            rowH = max(rowH, s.height)
        }
        used = max(used, x - spacing)
        return CGSize(width: max(0, min(maxW, used)), height: y + rowH)
    }

    func placeSubviews(
        in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()
    ) {
        var x = bounds.minX
        var y = bounds.minY
        var rowH: CGFloat = 0
        for v in subviews {
            let s = v.sizeThatFits(.unspecified)
            if x + s.width > bounds.maxX && x > bounds.minX {
                x = bounds.minX
                y += rowH + spacing
                rowH = 0
            }
            v.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(s))
            x += s.width + spacing
            rowH = max(rowH, s.height)
        }
    }
}

/// A masonry layout: subviews flow into `columns` columns and each next item is
/// placed in the currently shortest column, so variable card heights stagger
/// naturally (the Apple-Intelligence / Siri conversation grid). Unlike
/// `LazyVGrid`, rows do not line up — the columns are packed independently.
///
/// The measured heights are cached per width, so a layout pass doesn't re-measure
/// every card in both `sizeThatFits` and `placeSubviews`.
struct StaggeredGrid: Layout {
    var columns: Int = 2
    var spacing: CGFloat = 8

    struct Cache {
        var width: CGFloat = -1
        var heights: [CGFloat] = []
    }

    func makeCache(subviews: Subviews) -> Cache { Cache() }

    /// Invalidate the measured heights when the content changes.
    func updateCache(_ cache: inout Cache, subviews: Subviews) {
        if cache.heights.count != subviews.count { cache.width = -1 }
    }

    private func columnWidth(_ total: CGFloat) -> CGFloat {
        let c = max(1, columns)
        return max(1, (total - spacing * CGFloat(c - 1)) / CGFloat(c))
    }

    /// Measured per-item heights at `width`, reusing the cache when possible.
    private func heights(_ subviews: Subviews, width: CGFloat, cache: inout Cache) -> [CGFloat] {
        if cache.width == width, cache.heights.count == subviews.count { return cache.heights }
        let colW = columnWidth(width)
        cache.heights = subviews.map {
            $0.sizeThatFits(ProposedViewSize(width: colW, height: nil)).height
        }
        cache.width = width
        return cache.heights
    }

    /// Shortest-column packing gives each item its column index.
    private func packing(_ heights: [CGFloat]) -> ([Int], [CGFloat]) {
        let c = max(1, columns)
        var colHeights = [CGFloat](repeating: 0, count: c)
        var assignment: [Int] = []
        assignment.reserveCapacity(heights.count)
        for h in heights {
            let i = colHeights.indices.min(by: { colHeights[$0] < colHeights[$1] }) ?? 0
            assignment.append(i)
            colHeights[i] += h + spacing
        }
        return (assignment, colHeights)
    }

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout Cache) -> CGSize
    {
        let total = proposal.width ?? 300
        let hs = heights(subviews, width: total, cache: &cache)
        let (_, colHeights) = packing(hs)
        return CGSize(width: total, height: max(0, (colHeights.max() ?? 0) - spacing))
    }

    func placeSubviews(
        in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout Cache
    ) {
        let colW = columnWidth(bounds.width)
        let hs = heights(subviews, width: bounds.width, cache: &cache)
        let (assignment, _) = packing(hs)
        var colHeights = [CGFloat](repeating: 0, count: max(1, columns))
        for (idx, v) in subviews.enumerated() {
            let i = assignment[idx]
            v.place(
                at: CGPoint(
                    x: bounds.minX + CGFloat(i) * (colW + spacing),
                    y: bounds.minY + colHeights[i]),
                proposal: ProposedViewSize(width: colW, height: hs[idx]))
            colHeights[i] += hs[idx] + spacing
        }
    }
}
