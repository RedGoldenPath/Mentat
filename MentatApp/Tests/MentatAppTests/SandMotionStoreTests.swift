import XCTest

@testable import MentatApp

/// The sand motion is a sum of decaying impulses: it responds to UI events and
/// always settles to rest, and the amplitude ladder keeps small moves small.
@MainActor
final class SandMotionStoreTests: XCTestCase {
    private func store() -> SandMotionStore {
        let s = SandMotionStore()
        s.idleWindow = 0.05   // don't leave long sleeps in the test process
        return s
    }

    func testImpulseSettlesToRest() {
        let s = store()
        s.emit(.send, at: 100)
        XCTAssertTrue(s.isActive)
        let atEvent = s.motion(at: 100)
        XCTAssertGreaterThan(atEvent.gust, 0.5)
        let later = s.motion(at: 130)
        XCTAssertLessThan(abs(later.gust), 0.01)
        XCTAssertLessThan(abs(later.shift.height), 0.5)
    }

    func testImpulsesSum() {
        let s = store()
        s.emit(.panel(.trailing, open: true), at: 0)
        let one = s.motion(at: 0).shift.width
        s.emit(.panel(.trailing, open: true), at: 0)
        let two = s.motion(at: 0).shift.width
        XCTAssertEqual(two, one * 2, accuracy: 1e-6)
    }

    func testPanelDirectionsOppose() {
        let open = store(), close = store()
        open.emit(.panel(.trailing, open: true), at: 0)
        close.emit(.panel(.trailing, open: false), at: 0)
        let a = open.motion(at: 0).shift.width
        let b = close.motion(at: 0).shift.width
        XCTAssertEqual(a, -b, accuracy: 1e-6)
        XCTAssertLessThan(a, 0)   // opening the trailing pane shifts left
    }

    func testBigMovesAreBiggerThanSmall() {
        let big = store(), small = store()
        big.emit(.send, at: 0)
        small.emit(.scroll(dy: 3), at: 0)
        XCTAssertGreaterThan(big.motion(at: 0).gust, small.motion(at: 0).gust)
        XCTAssertLessThan(small.motion(at: 0).shear, 0.1)   // scroll stays light
    }

    func testImpulseScaleZeroDisablesEvents() {
        let s = store()
        var t = DesignTokens.Sand()
        t.impulseScale = 0
        s.configure(t)
        s.emit(.send, at: 0)
        let m = s.motion(at: 0)
        XCTAssertEqual(m.gust, 0, accuracy: 1e-9)
        XCTAssertEqual(m.pulse, 0, accuracy: 1e-9)
        XCTAssertEqual(m.shift.height, 0, accuracy: 1e-9)
    }

    func testContinuousCouplingsPassThrough() {
        let s = store()
        s.setBreath(0.5)
        XCTAssertEqual(s.motion(at: 0).breath, 0.5)
    }

    func testGlobalTransitionsEmitNoWalls() {
        let s = store()
        s.emit(.scroll(dy: 40), at: 0)
        s.emit(.modeChange, at: 0)
        s.emit(.resize(dx: 120, dy: 0), at: 0)
        // global motion is a force now — no full-span collider to trap the dust
        XCTAssertTrue(s.solids(at: 0).isEmpty)
    }

    func testLocalSolidsKeptAndBounded() {
        let s = store()
        s.emit(.panel(.trailing, open: true), at: 0)
        s.emit(.send, at: 0)
        let rects = s.solids(at: 0)
        XCTAssertEqual(rects.count, 2)
        for r in rects {
            XCTAssertLessThan(r.z, 0.98)
            XCTAssertLessThan(r.w, 0.98)
        }
    }

    func testParallaxTracksPointer() {
        let s = store()
        s.setPointer(CGPoint(x: 75, y: 25), in: CGSize(width: 100, height: 100))
        XCTAssertEqual(s.parallax.width, 0.25, accuracy: 1e-6)
        XCTAssertEqual(s.parallax.height, -0.25, accuracy: 1e-6)
    }

    func testPointerTracksPositionAndVelocity() {
        let s = store()
        s.setPointer(CGPoint(x: 50, y: 25), in: CGSize(width: 100, height: 100))
        XCTAssertTrue(s.hasPointer)
        XCTAssertEqual(s.pointer.x, 0.5, accuracy: 1e-6)
        XCTAssertEqual(s.pointer.y, 0.25, accuracy: 1e-6)
        s.setPointer(CGPoint(x: 60, y: 40), in: CGSize(width: 100, height: 100))
        XCTAssertEqual(s.pointerVelocity.x, 0.1, accuracy: 1e-6)
        XCTAssertGreaterThan(s.pointerVelocity.y, 0)
        s.clearPointer()
        XCTAssertFalse(s.hasPointer)
    }
}
