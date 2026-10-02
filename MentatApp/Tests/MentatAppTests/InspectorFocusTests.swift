import XCTest

@testable import MentatApp

/// The Inspector follows the newest answer by default and pins to a clicked
/// answer — the single data source for every per-answer tab.
@MainActor
final class InspectorFocusTests: XCTestCase {
    func testDefaultsToMostCurrentAnswer() {
        let a1 = ChatMessage(role: .assistant, text: "one")
        let a2 = ChatMessage(role: .assistant, text: "two")
        let messages = [ChatMessage(role: .user, text: "q"), a1, a2]
        XCTAssertTrue(InspectorStore.focusedAnswer(in: messages, focused: nil) === a2)
    }

    func testPinsToFocusedAnswer() {
        let a1 = ChatMessage(role: .assistant, text: "one")
        let a2 = ChatMessage(role: .assistant, text: "two")
        XCTAssertTrue(InspectorStore.focusedAnswer(in: [a1, a2], focused: a1.id) === a1)
    }

    func testUserFocusFallsBackToCurrentAnswer() {
        let u = ChatMessage(role: .user, text: "q")
        let a = ChatMessage(role: .assistant, text: "a")
        XCTAssertTrue(InspectorStore.focusedAnswer(in: [u, a], focused: u.id) === a)
    }

    func testStaleFocusFallsBackToCurrentAnswer() {
        let a = ChatMessage(role: .assistant, text: "a")
        XCTAssertTrue(InspectorStore.focusedAnswer(in: [a], focused: UUID()) === a)
    }

    func testNoAnswerIsNil() {
        let messages = [ChatMessage(role: .user, text: "q")]
        XCTAssertNil(InspectorStore.focusedAnswer(in: messages, focused: nil))
    }

    func testFocusPinsAndReveals() {
        let store = InspectorStore()
        store.visible = false
        let id = UUID()
        store.focus(id)
        XCTAssertEqual(store.focusedAnswerID, id)
        XCTAssertTrue(store.visible)
        store.clearFocus()
        XCTAssertNil(store.focusedAnswerID)
    }
}
