import XCTest

@testable import MentatApp

/// The systematized token groups (space · material · elevation) and their
/// tolerant decoding, so old saved blobs keep working.
final class DesignTokensTests: XCTestCase {
    func testRoundTripIncludesNewGroups() throws {
        var t = DesignTokens.default
        t.space.l = 40
        t.material.role = .glass
        t.elevation.mid.opacity = 0.5
        let back = try JSONDecoder().decode(DesignTokens.self, from: JSONEncoder().encode(t))
        XCTAssertEqual(back.space.l, 40)
        XCTAssertEqual(back.material.role, .glass)
        XCTAssertEqual(back.elevation.mid.opacity, 0.5)
    }

    func testTolerantDecodeKeepsDefaultsForNewGroups() throws {
        // A blob that predates space/material/elevation must still load.
        let json = Data(#"{"typography":{"fontSize":14}}"#.utf8)
        let t = try JSONDecoder().decode(DesignTokens.self, from: json)
        XCTAssertEqual(t.typography.fontSize, 14)
        XCTAssertEqual(t.space.m, DesignTokens.Space().m)
        XCTAssertEqual(t.material.role, .tonal)
        XCTAssertEqual(t.elevation.mid.radius, DesignTokens.Elevation().mid.radius)
    }

    func testTolerantDecodeWithinSpaceGroup() throws {
        // Adding a field to a group must not wipe the rest of it.
        let json = Data(#"{"space":{"xs":10}}"#.utf8)
        let t = try JSONDecoder().decode(DesignTokens.self, from: json)
        XCTAssertEqual(t.space.xs, 10)
        XCTAssertEqual(t.space.m, DesignTokens.Space().m)
    }

    func testMaterialRoleCatalogue() {
        XCTAssertEqual(MaterialRole.allCases.count, 5)
        for r in [MaterialRole.material, .tonal, .outline, .solid, .glass] {
            XCTAssertTrue(MaterialRole.allCases.contains(r))
        }
    }

    func testSpaceGridIsStrictlyIncreasing() {
        let s = DesignTokens.Space()
        XCTAssertLessThan(s.xxs, s.xs)
        XCTAssertLessThan(s.xs, s.s)
        XCTAssertLessThan(s.s, s.m)
        XCTAssertLessThan(s.m, s.l)
        XCTAssertLessThan(s.l, s.xl)
        XCTAssertLessThan(s.xl, s.xxl)
        XCTAssertLessThan(s.xxl, s.xxxl)
    }

    func testElevationRampIsIncreasing() {
        let e = DesignTokens.Elevation()
        XCTAssertLessThan(e.low.radius, e.mid.radius)
        XCTAssertLessThan(e.mid.radius, e.high.radius)
        XCTAssertLessThan(e.low.opacity, e.high.opacity)
    }
}
