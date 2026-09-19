import XCTest
import SwiftUI
@testable import MentatApp

final class SchemeTests: XCTestCase {
    private func palette(hue: Double, chroma: Double = 0.14) -> ImagePalette {
        ImagePalette(clusters: [], baseHue: hue, meanChroma: chroma, meanLightness: 0.45,
                     isLight: false, isNeutral: false)
    }

    private func hue(_ c: Color) -> Double { ColorScience.oklch(NSColor(c)).h }

    private func angle(_ a: Double, _ b: Double) -> Double {
        let d = abs(a - b).truncatingRemainder(dividingBy: 360)
        return min(d, 360 - d)
    }

    private func theme(_ scheme: PaletteScheme, hue h: Double) -> ColorTheme {
        var c = ColorControls.default
        c.scheme = scheme
        return ColorResolver.theme(for: palette(hue: h), controls: c)
    }

    func testSchemeRotatesSurfaceHue() {
        // The dominant surface hue now follows the scheme (full rotation).
        XCTAssertEqual(angle(hue(theme(.primary, hue: 30).surface), 30), 0, accuracy: 6)
        XCTAssertEqual(angle(hue(theme(.complementary, hue: 30).surface), 210), 0, accuracy: 6)
        XCTAssertEqual(angle(hue(theme(.triadic, hue: 30).surface), 150), 0, accuracy: 6)
        XCTAssertEqual(angle(hue(theme(.analogous, hue: 200).surface), 230), 0, accuracy: 6)
    }

    func testComplementaryRotatesAccent180() {
        let t = theme(.complementary, hue: 30)
        XCTAssertEqual(angle(hue(t.accent), 210), 0, accuracy: 6)
    }

    func testTriadicRotations() {
        let t = theme(.triadic, hue: 30)
        XCTAssertEqual(angle(hue(t.accent), 150), 0, accuracy: 6)     // +120
        XCTAssertEqual(angle(hue(t.secondary), 270), 0, accuracy: 6)  // +240
    }

    func testAnalogousStaysNear() {
        let t = theme(.analogous, hue: 200)
        XCTAssertEqual(angle(hue(t.accent), 230), 0, accuracy: 6)     // +30
        XCTAssertEqual(angle(hue(t.secondary), 170), 0, accuracy: 6)  // -30
    }

    func testPrimaryAndMonochromeAreSingleHue() {
        for scheme in [PaletteScheme.primary, .monochrome] {
            let t = theme(scheme, hue: 120)
            XCTAssertEqual(angle(hue(t.accent), 120), 0, accuracy: 6, "\(scheme)")
            XCTAssertEqual(angle(hue(t.secondary), 120), 0, accuracy: 6, "\(scheme)")
            XCTAssertEqual(angle(hue(t.tertiary), 120), 0, accuracy: 6, "\(scheme)")
        }
    }

    func testRolesMeetContrast() {
        for scheme in PaletteScheme.allCases {
            let t = theme(scheme, hue: 260)
            let bg = NSColor(t.background)
            XCTAssertGreaterThanOrEqual(ColorScience.contrast(NSColor(t.accent), bg), 3.0, "\(scheme).accent")
            XCTAssertGreaterThanOrEqual(ColorScience.contrast(NSColor(t.secondary), bg), 3.0, "\(scheme).secondary")
            XCTAssertGreaterThanOrEqual(ColorScience.contrast(NSColor(t.tertiary), bg), 3.0, "\(scheme).tertiary")
        }
    }

    func testFromImageUsesClusterHues() {
        let clusters: [ImagePalette.Cluster] = [
            .init(color: ColorScience.OKLCH(l: 0.5, c: 0.15, h: 20), weight: 0.5),
            .init(color: ColorScience.OKLCH(l: 0.5, c: 0.15, h: 200), weight: 0.3),
            .init(color: ColorScience.OKLCH(l: 0.5, c: 0.15, h: 80), weight: 0.2),
        ]
        let p = ImagePalette(clusters: clusters, baseHue: 20, meanChroma: 0.15,
                             meanLightness: 0.5, isLight: false, isNeutral: false)
        var c = ColorControls.default
        c.scheme = .fromImage
        let t = ColorResolver.theme(for: p, controls: c)
        XCTAssertEqual(angle(hue(t.accent), 20), 0, accuracy: 6)
        XCTAssertEqual(angle(hue(t.secondary), 200), 0, accuracy: 6)
        XCTAssertEqual(angle(hue(t.tertiary), 80), 0, accuracy: 6)
    }
}
