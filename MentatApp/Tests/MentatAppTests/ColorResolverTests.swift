import XCTest

@testable import MentatApp

final class ColorResolverTests: XCTestCase {
    private func palette(hue: Double, chroma: Double, light: Double) -> ImagePalette {
        ImagePalette(
            clusters: [], baseHue: hue, meanChroma: chroma, meanLightness: light,
            isLight: light >= 0.6, isNeutral: chroma < 0.04)
    }

    func testInkMeetsBodyContrast() {
        for light in [0.2, 0.45, 0.8] {
            let t = ColorResolver.theme(
                for: palette(hue: 30, chroma: 0.10, light: light),
                controls: .default)
            XCTAssertGreaterThanOrEqual(
                ColorScience.contrast(NSColor(t.ink), NSColor(t.surface)), 4.5)
            XCTAssertGreaterThanOrEqual(
                ColorScience.contrast(NSColor(t.inkDim), NSColor(t.surface)), 4.5)
        }
    }

    func testAccentMeetsLargeContrast() {
        for hue in [30.0, 140.0, 210.0, 300.0] {
            let t = ColorResolver.theme(
                for: palette(hue: hue, chroma: 0.12, light: 0.5),
                controls: .default)
            XCTAssertGreaterThanOrEqual(
                ColorScience.contrast(NSColor(t.accent), NSColor(t.background)), 3.0)
            XCTAssertGreaterThanOrEqual(
                ColorScience.contrast(NSColor(t.good), NSColor(t.background)), 3.0)
            XCTAssertGreaterThanOrEqual(
                ColorScience.contrast(NSColor(t.bad), NSColor(t.background)), 3.0)
        }
    }

    func testOnAccentMeetsBodyContrast() {
        let t = ColorResolver.theme(
            for: palette(hue: 200, chroma: 0.12, light: 0.5), controls: .default)
        XCTAssertGreaterThanOrEqual(
            ColorScience.contrast(NSColor(t.onAccent), NSColor(t.accent)), 4.5)
    }

    func testHueFollowsImageAndShift() {
        let p = palette(hue: 30, chroma: 0.10, light: 0.4)
        XCTAssertEqual(ColorResolver.theme(for: p, controls: .default).baseHue, 30, accuracy: 0.001)
        var shifted = ColorControls.default
        shifted.hueShift = 90
        XCTAssertEqual(ColorResolver.theme(for: p, controls: shifted).baseHue, 120, accuracy: 0.001)
        var wrapped = ColorControls.default
        wrapped.hueShift = 350
        XCTAssertEqual(ColorResolver.theme(for: p, controls: wrapped).baseHue, 20, accuracy: 0.001)
    }

    func testMonochromeCollapsesToNeutral() {
        var c = ColorControls.default
        c.monochrome = true
        let t = ColorResolver.theme(for: palette(hue: 30, chroma: 0.02, light: 0.4), controls: c)
        for col in [t.ink, t.inkDim, t.surface, t.background, t.accent, t.border] {
            let ns = NSColor(col)
            XCTAssertEqual(Double(ns.redComponent), Double(ns.greenComponent), accuracy: 0.01)
            XCTAssertEqual(Double(ns.greenComponent), Double(ns.blueComponent), accuracy: 0.01)
        }
    }

    func testLightSchemeFlipsBackground() {
        var c = ColorControls.default
        c.light = true
        let t = ColorResolver.theme(for: palette(hue: 30, chroma: 0.10, light: 0.8), controls: c)
        XCTAssertTrue(t.isLight)
        XCTAssertGreaterThan(ColorScience.relativeLuminance(NSColor(t.background)), 0.7)
        XCTAssertLessThan(ColorScience.relativeLuminance(NSColor(t.ink)), 0.3)
        XCTAssertGreaterThanOrEqual(ColorScience.contrast(NSColor(t.ink), NSColor(t.surface)), 4.5)
    }

    func testStainedGlassTintIsTranslucent() {
        let t = ColorResolver.theme(
            for: palette(hue: 30, chroma: 0.10, light: 0.4), controls: .default)
        XCTAssertLessThan(NSColor(t.surfaceTint).alphaComponent, 1.0)
        XCTAssertGreaterThan(NSColor(t.surfaceTint).alphaComponent, 0.0)
    }
}
