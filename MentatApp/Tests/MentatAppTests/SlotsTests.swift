import SwiftUI
import XCTest

@testable import MentatApp

/// The named-slot registry (dsh-style) and the Inspector tab catalogue.
@MainActor
final class SlotsTests: XCTestCase {
    func testRegisterAndReadInOrder() {
        let r = SlotRegistry()
        XCTAssertTrue(r.isEmpty(.menuItems))
        r.register(.menuItems) { Text("a") }
        r.register(.menuItems) { Text("b") }
        XCTAssertEqual(r.views(.menuItems).count, 2)
        XCTAssertFalse(r.isEmpty(.menuItems))
    }

    func testSlotsAreIndependent() {
        let r = SlotRegistry()
        r.register(.composerLeading) { Text("x") }
        XCTAssertTrue(r.isEmpty(.composerTrailing))
        XCTAssertEqual(r.views(.composerLeading).count, 1)
        // every declared slot starts empty
        for key in SlotRegistry.Key.allCases where key != .composerLeading {
            XCTAssertTrue(r.isEmpty(key), "\(key) unexpectedly populated")
        }
    }

    func testInspectorTabs() {
        XCTAssertEqual(InspectorTab.allCases.count, 5)
        XCTAssertEqual(InspectorTab(rawValue: "artifacts"), .artifacts)
        XCTAssertEqual(InspectorTab(rawValue: "citations"), .citations)
        XCTAssertEqual(InspectorTab(rawValue: "nope"), nil)
    }

    func testSingleKeepsLast() {
        let r = SlotRegistry()
        r.declare(.menuItems, as: .single)
        r.register(.menuItems) { Text("a") }
        r.register(.menuItems) { Text("b") }
        XCTAssertEqual(r.views(.menuItems).count, 1)
    }

    func testKeyedDispatch() {
        let r = SlotRegistry()
        r.declare(.inspectorTabs, as: .keyed)
        r.register(.inspectorTabs, id: "citations") { Text("c") }
        r.register(.inspectorTabs, id: "context") { Text("x") }
        XCTAssertEqual(r.views(.inspectorTabs).count, 2)
        XCTAssertEqual(r.views(.inspectorTabs, keyed: "context").count, 1)
    }

    func testChainElectsByPriority() {
        let r = SlotRegistry()
        r.declare(.composerLeading, as: .chain)
        r.register(.composerLeading, priority: 5) { Text("late") }
        r.register(.composerLeading, priority: 1) { Text("early") }
        XCTAssertEqual(r.views(.composerLeading).count, 1)
    }

    func testDisposeIsReversible() {
        let r = SlotRegistry()
        r.declare(.menuItems)
        let undo = r.dispose(.menuItems)
        r.register(.menuItems) { Text("x") }
        XCTAssertFalse(r.isEmpty(.menuItems))
        undo()
        XCTAssertTrue(r.isEmpty(.menuItems))
    }

    func testDeclarationIsAuthoritative() {
        let r = SlotRegistry()
        r.declare(.developerPanels, as: .single)
        r.declare(.developerPanels, as: .list)   // ignored
        XCTAssertEqual(r.kind(.developerPanels), .single)
    }
}
