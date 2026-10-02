import XCTest

@testable import MentatApp

/// Token decode for the (legacy) bubble group. Bubbles are no longer the content
/// surface — content is plain prose on a surface — but the token round-trips so
/// older saved token blobs still decode.
final class BubbleTests: XCTestCase {
    func testBubbleTokenTolerantDecode() throws {
        let json = Data(#"{"material":{"role":"glass"},"bubble":{"userOpacity":0.95}}"#.utf8)
        let t = try JSONDecoder().decode(DesignTokens.self, from: json)
        XCTAssertEqual(t.bubble.userOpacity, 0.95)
        XCTAssertEqual(t.bubble.role, .tonal)              // default kept
        XCTAssertEqual(t.material.role, .glass)
    }

    func testBubbleRoundTrip() throws {
        var t = DesignTokens.default
        t.bubble.role = .outline
        t.bubble.assistantOpacity = 0.6
        let back = try JSONDecoder().decode(DesignTokens.self, from: JSONEncoder().encode(t))
        XCTAssertEqual(back.bubble.role, .outline)
        XCTAssertEqual(back.bubble.assistantOpacity, 0.6, accuracy: 1e-9)
    }

    func testLookRoundTrip() throws {
        var t = DesignTokens.default
        t.look = .paper
        let back = try JSONDecoder().decode(DesignTokens.self, from: JSONEncoder().encode(t))
        XCTAssertEqual(back.look, .paper)
    }
}
