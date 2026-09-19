import XCTest
@testable import MentatApp

/// The reading surface's pagination rules are the product; these pin them.
final class PageEngineTests: XCTestCase {
    private func engine(availableWidth: CGFloat = 1000) -> PageEngine {
        PageEngine(measure: 300, maxColumnWidth: 400,
                   linesPerColumn: 30, maxColumns: 3, gutter: 20)
    }

    /// Synthetic line ranges: line `i` occupies `[i*10, i*10+10)`.
    private func lines(_ n: Int) -> [NSRange] {
        (0..<n).map { NSRange(location: $0 * 10, length: 10) }
    }

    func testColumnsThatFitRoundsAndCaps() {
        let e = engine()
        XCTAssertEqual(e.columnsThatFit(availableWidth: 1000), 3)   // (1020)/(320) ≈ 3.19
        XCTAssertEqual(e.columnsThatFit(availableWidth: 320), 1)    // one measure
        XCTAssertEqual(e.columnsThatFit(availableWidth: 100), 1)    // never zero
    }

    func testShortAnswerIsOneCentredColumn() {
        let e = engine()
        let L = e.layout(lineCount: 5, availableWidth: 1000)
        XCTAssertEqual(L.columns, 1)
        XCTAssertEqual(L.pages, 1)
        XCTAssertTrue(L.centredSingleColumn)
    }

    func testColumnsMultiplyOnlyWhenTextSpills() {
        let e = engine()
        // 40 lines = 2 measure-columns of 30 → 2 columns, 1 page (not 3).
        let L = e.layout(lineCount: 40, availableWidth: 1000)
        XCTAssertEqual(L.columns, 2)
        XCTAssertEqual(L.pages, 1)
        XCTAssertFalse(L.centredSingleColumn)
    }

    func testPagesAfterColumnsFill() {
        let e = engine()
        // 91 lines = 4 columns of 30 → 3 per page → 2 pages.
        let L = e.layout(lineCount: 91, availableWidth: 1000)
        XCTAssertEqual(L.columns, 3)
        XCTAssertEqual(L.pages, 2)
    }

    func testFirstColumnFillsBeforeNextColumnStarts() {
        let e = engine()
        let L = e.layout(lineCount: 65, availableWidth: 1000)
        let page = e.page(0, layout: L, lines: lines(65), availableWidth: 1000)
        XCTAssertEqual(page.columns, 3)
        XCTAssertEqual(page.slices.count, 3)
        // 30 lines, then 30, then the remaining 5 (read top-to-bottom).
        XCTAssertEqual(page.slices[0], NSRange(location: 0, length: 300))
        XCTAssertEqual(page.slices[1], NSRange(location: 300, length: 300))
        XCTAssertEqual(page.slices[2], NSRange(location: 600, length: 50))
    }

    func testSecondPageStartsWhereFirstEnded() {
        let e = engine()
        let L = e.layout(lineCount: 91, availableWidth: 1000)
        let page = e.page(1, layout: L, lines: lines(91), availableWidth: 1000)
        // page 0 held lines 0..89; page 1 holds the final line.
        XCTAssertEqual(page.slices.count, 1)
        XCTAssertEqual(page.slices[0], NSRange(location: 900, length: 10))
    }

    func testColumnWidthRespectsMeasureAndCeiling() {
        let e = engine()
        XCTAssertEqual(e.columnWidth(1, availableWidth: 1000), 300)   // lone column = measure
        XCTAssertEqual(e.columnWidth(3, availableWidth: 1000), 320)   // (1000 - 40)/3
        // Never above the hard ceiling.
        XCTAssertEqual(e.columnWidth(2, availableWidth: 2000), 400)
    }

    func testPaginationIsIndependentOfWindowWidth() {
        // Resizing the window changes how many columns fit, but the number of
        // measure-columns the text needs (and so the page count) stays fixed.
        let e = engine()
        let need = 7  // 200 lines ÷ 30 per column
        for width in [620.0, 1000.0, 1600.0] {
            let L = e.layout(lineCount: 200, availableWidth: width)
            XCTAssertEqual(L.pages, Int(ceil(Double(need) / Double(L.columns))))
        }
    }
}
