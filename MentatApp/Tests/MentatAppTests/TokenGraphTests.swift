import XCTest

@testable import MentatApp

/// The W3C-shaped token graph: aliases, cycle detection, typed accessors, and
/// `.tokens.json` round-trips.
final class TokenGraphTests: XCTestCase {
    private func sample() -> TokenGraph {
        TokenGraph(tokens: [
            Token(path: "palette.brand", type: .color, value: .color("#EA9D5A")),
            Token(path: "color.accent", type: .color, alias: "{palette.brand}"),
            Token(path: "color.accentDeep", type: .color, alias: "{color.accent}"),
            Token(path: "space.m", type: .dimension, value: .dimension(16)),
            Token(path: "duration.smooth", type: .duration, value: .duration(0.3)),
        ])
    }

    func testAliasChainResolves() throws {
        XCTAssertEqual(try sample().resolve("{color.accentDeep}"), .color("#EA9D5A"))
    }

    func testTypedAccessors() throws {
        XCTAssertEqual(try sample().point("space.m"), 16)
        XCTAssertEqual(try sample().seconds("duration.smooth"), 0.3, accuracy: 1e-9)
    }

    func testMissingThrows() {
        XCTAssertThrowsError(try sample().resolve("nope.nope")) { error in
            XCTAssertEqual(error as? TokenError, .missing("nope.nope"))
        }
    }

    func testCycleDetected() {
        let g = TokenGraph(tokens: [
            Token(path: "a", type: .number, alias: "{b}"),
            Token(path: "b", type: .number, alias: "{a}"),
        ])
        XCTAssertThrowsError(try g.resolve("a")) { error in
            if case .cycle = error as? TokenError {} else { XCTFail("expected cycle") }
        }
    }

    func testW3CRoundTrip() throws {
        let g = TokenCatalog.graph(from: .default)
        let data = try g.encode()
        let back = try TokenGraph.decode(data)

        // alias preserved
        XCTAssertEqual(back.token("color.background")?.alias, "{palette.night.background}")
        // value survives
        XCTAssertEqual(try back.resolve("color.background"), .color("#16110C"))
        XCTAssertEqual(try back.point("space.m"), 16)
        XCTAssertEqual(try back.resolveType("material.role"), .fontFamily)
    }

    func testCatalogApplyRoundTrips() {
        var d = DesignTokens.default
        d.space.m = 42
        d.chrome.radiusL = 30
        let g = TokenCatalog.graph(from: d)
        var back = DesignTokens.default
        TokenCatalog.apply(g, into: &back)
        XCTAssertEqual(back.space.m, 42)
        XCTAssertEqual(back.chrome.radiusL, 30)
    }

    func testCatalogSandRoundTrips() {
        var d = DesignTokens.default
        d.sand.swirl = 0.2
        d.sand.dustCount = 12345
        d.sand.shaftStrength = 1.25
        let g = TokenCatalog.graph(from: d)
        var back = DesignTokens.default
        TokenCatalog.apply(g, into: &back)
        XCTAssertEqual(back.sand.swirl, 0.2)
        XCTAssertEqual(back.sand.dustCount, 12345)
        XCTAssertEqual(back.sand.shaftStrength, 1.25)
    }

    func testHexComponentParse() {
        let (r, g, b, a) = TokenGraph.components("#EA9D5A")
        XCTAssertEqual(a, 1, accuracy: 1e-9)
        XCTAssertEqual(r, 234.0 / 255.0, accuracy: 0.01)
        XCTAssertEqual(g, 157.0 / 255.0, accuracy: 0.01)
        XCTAssertEqual(b, 90.0 / 255.0, accuracy: 0.01)
    }
}
