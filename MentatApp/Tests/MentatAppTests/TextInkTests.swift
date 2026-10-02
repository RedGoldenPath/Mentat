import AppKit
import XCTest

@testable import MentatApp

/// Semantic text colours resolve per look and stay legible on their canvas.
final class TextInkTests: XCTestCase {
    /// The attributed builder actually paints heading / quote / link / number /
    /// citation with their semantic roles.
    func testSemanticSpansAreColored() {
        let ink = TextInk.look(.sand, isDark: true)
        let md = "# Title\n> \"quoted\"\nSee https://example.com and 42 today (Dune · Ch 3)"
        let a = TextStyle.attributed(md, color: NSColor.white, ink: ink, alignment: .left)
        func color(_ needle: String) -> NSColor? {
            let r = (a.string as NSString).range(of: needle)
            guard r.location != NSNotFound else { return nil }
            return a.attribute(.foregroundColor, at: r.location, effectiveRange: nil) as? NSColor
        }
        XCTAssertEqual(color("Title"), ink.heading)
        XCTAssertEqual(color("quoted"), ink.quote)
        XCTAssertEqual(color("https"), ink.link)
        XCTAssertEqual(color("42"), ink.number)
        XCTAssertEqual(color("Dune"), ink.citation)
    }

    func testSemanticRolesAreDistinct() {
        let ink = TextInk.look(.sand, isDark: true)
        XCTAssertNotEqual(ink.quote, ink.body)
        XCTAssertNotEqual(ink.heading, ink.body)
        XCTAssertNotEqual(ink.link, ink.citation)
    }

    func testBrandSandIsConstant() {
        // The wordmark uses this in every look.
        XCTAssertEqual(TextInk.brandSand, TextInk.brandSand)
        XCTAssertGreaterThan(TextInk.brandSand.redComponent, TextInk.brandSand.blueComponent)
    }

    func testBodyAndAccentsClearContrastOnCanvas() {
        for look in SurfaceLook.allCases {
            for dark in [false, true] {
                // only meaningful dark/light combos for paper/mono/sand
                if look == .paper && dark { continue }
                if (look == .mono || look == .sand) && !dark { continue }
                let t = ColorTheme.look(look, isDark: dark)
                let ink = TextInk.look(look, isDark: dark)
                let bg = NSColor(t.background)
                XCTAssertGreaterThanOrEqual(
                    ColorScience.contrast(ink.body, bg), 4.4, "body \(look) dark=\(dark)")
                XCTAssertGreaterThanOrEqual(
                    ColorScience.contrast(ink.heading, bg), 3.0, "heading \(look) dark=\(dark)")
                XCTAssertGreaterThanOrEqual(
                    ColorScience.contrast(ink.link, bg), 3.0, "link \(look) dark=\(dark)")
            }
        }
    }
}
