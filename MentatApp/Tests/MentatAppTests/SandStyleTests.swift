import XCTest

@testable import MentatApp

/// The dust system is data-driven: a preset plus tolerant token overrides.
final class SandStyleTests: XCTestCase {
    func testSandPresetHasDefaults() {
        let s = SandStyle.sand
        XCTAssertEqual(s.swirl, 0.2844362745098039, accuracy: 1e-9)
        XCTAssertEqual(s.drag, 9.498008578431373, accuracy: 1e-9)
        XCTAssertEqual(s.brownian, 0.008, accuracy: 1e-9)
        XCTAssertEqual(s.dustCount, 12000, accuracy: 1e-9)
        XCTAssertEqual(s.shaftStrength, 1.0865093954248366, accuracy: 1e-9)
        XCTAssertEqual(s.shaftSpread, 90.0, accuracy: 1e-9)
        XCTAssertEqual(s.shaftSourceGlow, 0.9056883169934641, accuracy: 1e-9)
        XCTAssertEqual(s.bloomIntensity, 0.4209354575163399, accuracy: 1e-9)
        XCTAssertEqual(s.parallaxDepth, 0.6, accuracy: 1e-9)
        XCTAssertEqual(s.goboStrength, 0.0, accuracy: 1e-9)
        XCTAssertTrue(s.layerClose && s.layerNear && s.layerMid && s.layerFar && s.layerHaze)
        XCTAssertEqual(s.volSteps, 24, accuracy: 1e-9)
        XCTAssertEqual(s.volDensity, 1.4, accuracy: 1e-9)
        XCTAssertEqual(s.taaAlpha, 0.18, accuracy: 1e-9)
        // the beam is warm, not pure white; sparkles are their own spice orange
        XCTAssertNotEqual(s.shaftColor, .white)
        XCTAssertNotEqual(s.sparkleColor, .white)
    }

    func testLayerTogglesReachConfig() {
        var t = DesignTokens.Sand()
        t.layerClose = false
        t.parallaxDepth = 0.9
        let c = SandStyle.sand.merging(t).config
        XCTAssertFalse(c.layerClose)
        XCTAssertTrue(c.layerFar)
        XCTAssertEqual(c.parallaxDepth, 0.9, accuracy: 1e-9)
    }

    func testVolumetricKnobsReachConfig() {
        var t = DesignTokens.Sand()
        t.volSteps = 32
        t.volDensity = 1.3
        t.taaAlpha = 0.25
        let c = SandStyle.sand.merging(t).config
        XCTAssertEqual(c.volSteps, 32, accuracy: 1e-9)
        XCTAssertEqual(c.volDensity, 1.3, accuracy: 1e-9)
        XCTAssertEqual(c.taaAlpha, 0.25, accuracy: 1e-9)
    }

    func testMergingAppliesTokenOverrides() {
        var t = DesignTokens.Sand()
        t.swirl = 0.3
        t.drag = 5.0
        t.dustCount = 12345
        t.shaftStrength = 2.0
        t.shaftSpread = 40
        t.shaftSourceGlow = 0.5
        let s = SandStyle.sand.merging(t)
        XCTAssertEqual(s.swirl, 0.3)
        XCTAssertEqual(s.drag, 5.0)
        XCTAssertEqual(s.dustCount, 12345)
        XCTAssertEqual(s.shaftStrength, 2.0)
        XCTAssertEqual(s.shaftSpread, 40)
        XCTAssertEqual(s.shaftSourceGlow, 0.5)
        // the palette comes from the preset, not the tokens
        XCTAssertEqual(s.shaftColor, SandStyle.sand.shaftColor)
    }

    func testSandTokenDecodesTolerantly() throws {
        let json = #"{"enabled":false,"swirl":0.3,"drag":4.0}"#.data(using: .utf8)!
        let t = try JSONDecoder().decode(DesignTokens.Sand.self, from: json)
        XCTAssertFalse(t.enabled)
        XCTAssertEqual(t.swirl, 0.3)
        XCTAssertEqual(t.drag, 4.0)
        XCTAssertEqual(t.dustCount, 12000)      // missing keys keep defaults
        XCTAssertEqual(t.shaftSpread, 90.0)
        XCTAssertEqual(t.shaftSourceGlow, 0.9056883169934641)
        XCTAssertEqual(t.impulseScale, 1.15)
    }

    func testSurfaceLookRenamesNoirToSand() {
        XCTAssertEqual(SurfaceLook(rawValue: "noir"), .sand)
        XCTAssertEqual(SurfaceLook(rawValue: "sand"), .sand)
        XCTAssertEqual(SurfaceLook.sand.label, "Sand")
    }
}
