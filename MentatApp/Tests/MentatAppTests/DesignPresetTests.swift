import AppKit
import XCTest

@testable import MentatApp

/// Looks are whole-system: selecting one writes the shared token, and the
/// palette resolves cohesively for each.
final class DesignPresetTests: XCTestCase {
    func testPresetsCoverEveryLook() {
        XCTAssertEqual(DesignPreset.all.count, SurfaceLook.allCases.count)
        XCTAssertEqual(Set(DesignPreset.all.map(\.id)).count, SurfaceLook.allCases.count)
    }

    func testApplyWritesLook() {
        var d = DesignTokens.default
        DesignPreset(.paper).apply(to: &d)
        XCTAssertEqual(d.look, .paper)
        XCTAssertEqual(DesignPreset.matching(d), "paper")
    }

    func testLookResolvesDistinctivity() {
        let sysLight = ColorTheme.look(.system, isDark: false)
        let paper = ColorTheme.look(.paper, isDark: false)
        let mono = ColorTheme.look(.mono, isDark: true)
        let sand = ColorTheme.look(.sand, isDark: true)
        XCTAssertTrue(sysLight.isLight)
        XCTAssertTrue(paper.isLight)
        XCTAssertFalse(mono.isLight)
        XCTAssertFalse(sand.isLight)
        XCTAssertNotEqual(paper.background, sysLight.background)
        XCTAssertLessThan(
            ColorScience.relativeLuminance(NSColor(sand.background)),
            ColorScience.relativeLuminance(NSColor(mono.background)))  // sand is darker
        for t in [sysLight, paper, mono, sand] {
            let ratio = ColorScience.contrast(NSColor(t.ink), NSColor(t.background))
            XCTAssertGreaterThan(ratio, 4.5, "\(t.isLight)")
        }
    }
}
