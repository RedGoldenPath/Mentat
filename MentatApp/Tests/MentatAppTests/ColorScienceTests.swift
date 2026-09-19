import XCTest

@testable import MentatApp

final class ColorScienceTests: XCTestCase {
    private func srgb(_ r: Double, _ g: Double, _ b: Double) -> NSColor {
        NSColor(srgbRed: r, green: g, blue: b, alpha: 1)
    }

    func testRoundTripThroughOKLCH() {
        let samples: [(Double, Double, Double)] = [
            (1, 0, 0), (0, 1, 0), (0, 0, 1),
            (0.2, 0.4, 0.6), (0.85, 0.8, 0.7), (0.5, 0.5, 0.5),
        ]
        for (r, g, b) in samples {
            let back = ColorScience.nsColor(ColorScience.oklch(r: r, g: g, b: b))
            XCTAssertEqual(Double(back.redComponent), r, accuracy: 0.002, "r for \(r),\(g),\(b)")
            XCTAssertEqual(Double(back.greenComponent), g, accuracy: 0.002, "g for \(r),\(g),\(b)")
            XCTAssertEqual(Double(back.blueComponent), b, accuracy: 0.002, "b for \(r),\(g),\(b)")
        }
    }

    func testLightnessEndpoints() {
        XCTAssertEqual(ColorScience.oklch(r: 1, g: 1, b: 1).l, 1.0, accuracy: 0.005)
        XCTAssertEqual(ColorScience.oklch(r: 0, g: 0, b: 0).l, 0.0, accuracy: 0.005)
    }

    func testRedHue() {
        XCTAssertEqual(ColorScience.oklch(r: 1, g: 0, b: 0).h, 29.2, accuracy: 1.5)
    }

    func testWCAGExtremes() {
        XCTAssertEqual(ColorScience.contrast(srgb(1, 1, 1), srgb(0, 0, 0)), 21, accuracy: 0.1)
        XCTAssertEqual(
            ColorScience.contrast(srgb(0.5, 0.5, 0.5), srgb(0.5, 0.5, 0.5)), 1, accuracy: 0.01)
    }

    func testContrastEnforcementReachesLevel() {
        let bg = ColorScience.oklch(r: 1, g: 1, b: 1)  // white
        let fg = OKLCHGray(l: 0.62)  // low contrast on white
        let fixed = ColorScience.enforce(fg, on: bg, level: .body)
        XCTAssertGreaterThanOrEqual(ColorScience.contrast(fixed, bg), 4.5)
    }

    func testContrastEnforcementKeepsGoodColour() {
        let bg = ColorScience.oklch(r: 1, g: 1, b: 1)
        let fg = ColorScience.oklch(r: 0.1, g: 0.1, b: 0.1)  // already high contrast
        XCTAssertEqual(ColorScience.enforce(fg, on: bg, level: .body), fg)
    }

    func testGamutMappingBringsColourInsideSRGB() {
        let wild = ColorScience.OKLCH(l: 0.6, c: 0.5, h: 140)
        XCTAssertFalse(ColorScience.inGamut(wild))
        XCTAssertTrue(ColorScience.inGamut(ColorScience.gamutMapped(wild)))
    }

    func testMixEndpointsAndMidpoint() {
        let a = ColorScience.OKLCH(l: 0.2, c: 0.1, h: 10)
        let b = ColorScience.OKLCH(l: 0.8, c: 0.1, h: 10)
        XCTAssertEqual(ColorScience.mix(a, b, 0).l, 0.2, accuracy: 1e-9)
        XCTAssertEqual(ColorScience.mix(a, b, 1).l, 0.8, accuracy: 1e-9)
        XCTAssertEqual(ColorScience.mix(a, b, 0.5).l, 0.5, accuracy: 1e-9)
    }

    func testHueRotationWraps() {
        let c = ColorScience.OKLCH(l: 0.5, c: 0.1, h: 350)
        XCTAssertEqual(ColorScience.rotate(c, 20).h, 10, accuracy: 1e-9)
    }
}

/// Small helper so the test reads clearly (a neutral at a given lightness).
private func OKLCHGray(l: Double) -> ColorScience.OKLCH {
    ColorScience.OKLCH(l: l, c: 0, h: 0)
}
