import AppKit
import CoreText

/// Pure pagination engine for the reading surface. No SwiftUI, no state — it
/// takes measured line breaks plus the typographic rules and returns pages of
/// column slices. Keeping this pure is what makes the reading quirks testable.
///
/// The rules (ported from the established reading surface):
/// - a fixed book measure per column, hard-capped at the 55-char ceiling;
/// - `linesPerColumn` lines per column, filled top-to-bottom (columns are read
///   down, then across — *not* balanced);
/// - columns multiply 1 → 2 → 3 only when the text is long enough to spill past
///   a full column, then the text paginates;
/// - a lone column that fits one page is centred.
struct PageEngine: Equatable {
    var measure: CGFloat
    var maxColumnWidth: CGFloat
    var linesPerColumn: Int
    var maxColumns: Int
    var gutter: CGFloat

    /// Resolved shape of a laid-out answer.
    struct Layout: Equatable {
        var lineCount: Int
        var columns: Int
        var pages: Int
        /// A single column on a single page reads best centred.
        var centredSingleColumn: Bool
    }

    /// One rendered page: the column slices to draw.
    struct Page: Equatable {
        var columns: Int
        var columnWidth: CGFloat
        var slices: [NSRange]
    }

    /// How many columns the view is wide enough to hold (1…`maxColumns`).
    func columnsThatFit(availableWidth: CGFloat) -> Int {
        let raw = Int(((availableWidth + gutter) / (measure + gutter)).rounded())
        return max(1, min(maxColumns, raw))
    }

    /// Resolve columns/pages from the measured line count.
    func layout(lineCount: Int, availableWidth: CGFloat) -> Layout {
        let need = max(1, (lineCount + linesPerColumn - 1) / linesPerColumn)
        let cols = max(
            1, min(min(maxColumns, columnsThatFit(availableWidth: availableWidth)), need))
        let pages = max(1, (need + cols - 1) / cols)
        return Layout(
            lineCount: lineCount, columns: cols, pages: pages,
            centredSingleColumn: pages == 1 && cols == 1)
    }

    /// Width of one column when `n` share the available width. A lone column is
    /// never wider than the comfortable book measure, and no column may exceed
    /// the hard ceiling.
    func columnWidth(_ n: Int, availableWidth: CGFloat) -> CGFloat {
        if n <= 1 { return max(120, min(min(measure, availableWidth), maxColumnWidth)) }
        let raw = (availableWidth - gutter * CGFloat(n - 1)) / CGFloat(n)
        return max(120, min(raw, maxColumnWidth))
    }

    /// Slice one page into its column ranges. The first column is filled all the
    /// way down before a new column is started.
    func page(_ index: Int, layout L: Layout, lines: [NSRange], availableWidth: CGFloat) -> Page {
        let pageCap = L.columns * linesPerColumn
        let start = min(lines.count, index * pageCap)
        let end = min(lines.count, start + pageCap)
        let count = max(0, end - start)
        let pageCols = max(1, min(L.columns, (count + linesPerColumn - 1) / linesPerColumn))
        guard count > 0 else {
            return Page(
                columns: 1,
                columnWidth: columnWidth(1, availableWidth: availableWidth),
                slices: [])
        }
        var slices: [NSRange] = []
        var cur = start
        for _ in 0..<pageCols {
            let remaining = count - (cur - start)
            let take = min(linesPerColumn, remaining)
            if take <= 0 { break }
            let hi = cur + take
            let s = lines[cur].location
            let e = lines[hi - 1].location + lines[hi - 1].length
            slices.append(NSRange(location: s, length: e - s))
            cur = hi
        }
        return Page(
            columns: pageCols,
            columnWidth: columnWidth(pageCols, availableWidth: availableWidth),
            slices: slices)
    }
}
