import XCTest

@testable import MentatApp

/// The one command registry and the one settings-section grouping.
final class CommandsTests: XCTestCase {
    func testCommandIDsAreUnique() {
        let ids = CommandRegistry.everything.map(\.id)
        XCTAssertEqual(ids.count, Set(ids).count)
    }

    func testDebugFiltering() {
        let primary = CommandRegistry.all(debug: false)
        let full = CommandRegistry.all(debug: true)
        XCTAssertTrue(full.count > primary.count)
        XCTAssertFalse(primary.contains { $0.debugOnly })
        XCTAssertTrue(full.contains { $0.debugOnly })
    }

    func testKindInvariants() {
        for c in CommandRegistry.everything {
            switch c.kind {
            case .slash: XCTAssertNotNil(c.slash)
            case .ui: XCTAssertNil(c.slash)
            }
        }
    }

    func testACommandForEverySurface() {
        // every section is represented, so the palette never shows a blank group
        let covered = Set(CommandRegistry.everything.map(\.section))
        XCTAssertEqual(covered, Set(Command.Section.allCases))
    }

    func testInspectorShortcutAndSlashSettings() {
        let inspector = CommandRegistry.everything.first { $0.id == "inspector" }
        XCTAssertEqual(inspector?.shortcut, "⌘I")
        let settings = CommandRegistry.everything.first { $0.id == "settings" }
        XCTAssertEqual(settings?.slash, "settings")
    }

    func testGroupsBySectionPreservingOrder() {
        let specs = [
            SettingSpec(key: "a", section: "One", help: nil),
            SettingSpec(key: "b", section: "Two", help: nil),
            SettingSpec(key: "c", section: "One", help: nil),
        ]
        let g = SettingSection.group(specs)
        XCTAssertEqual(g.map(\.0), ["One", "Two"])
        XCTAssertEqual(g[0].1.map(\.key), ["a", "c"])
        XCTAssertEqual(g[1].1.map(\.key), ["b"])
    }

    func testGroupPredicateAndNilSection() {
        let specs = [
            SettingSpec(key: "keep", section: "S", help: nil),
            SettingSpec(key: "drop", section: "S", help: nil),
            SettingSpec(key: "loose", section: nil, help: nil),
        ]
        let g = SettingSection.group(specs) { $0.key != "drop" }
        XCTAssertEqual(g.first(where: { $0.0 == "S" })?.1.map(\.key), ["keep"])
        XCTAssertEqual(g.first(where: { $0.0 == "Other" })?.1.map(\.key), ["loose"])
    }
}
