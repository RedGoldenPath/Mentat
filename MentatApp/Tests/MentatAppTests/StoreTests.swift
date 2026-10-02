import XCTest

@testable import MentatApp

/// The interface reducer: state transitions and the effect it names.
final class StoreTests: XCTestCase {
    func testToggleSidebarFlips() {
        var s = UIReducer.State()
        XCTAssertEqual(UIReducer.reduce(&s, .toggleSidebar), .none)
        XCTAssertFalse(s.sidebarVisible)
        _ = UIReducer.reduce(&s, .toggleSidebar)
        XCTAssertTrue(s.sidebarVisible)
    }

    func testCycleAppearanceAdvances() {
        var s = UIReducer.State()
        let before = s.appearanceRaw
        XCTAssertEqual(UIReducer.reduce(&s, .cycleAppearance), .none)
        XCTAssertNotEqual(s.appearanceRaw, before)
    }

    func testEffectsAreNamed() {
        var s = UIReducer.State()
        XCTAssertEqual(UIReducer.reduce(&s, .newConversation), .newConversation)
        XCTAssertEqual(UIReducer.reduce(&s, .toggleInspector), .inspector)
        XCTAssertEqual(UIReducer.reduce(&s, .toggleGrid), .grid)
        XCTAssertEqual(UIReducer.reduce(&s, .toggleDebug), .debug)
    }
}
