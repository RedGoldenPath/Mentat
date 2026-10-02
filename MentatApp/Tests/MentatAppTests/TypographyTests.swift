import AppKit
import XCTest

@testable import MentatApp

/// Pins the text builder's markdown handling — the heading path once emitted each
/// title twice (append, then fall through and append again).
final class TypographyTests: XCTestCase {
    private func plain(_ s: String) -> String {
        TextStyle.attributed(s, color: .black).string
    }

    func testHeadingIsNotDuplicated() {
        let out = plain("# Dune and the Denial of Popular Sovereignty\nBody line.")
        let count = out.components(separatedBy: "Dune and the Denial").count - 1
        XCTAssertEqual(count, 1, "heading text must appear exactly once")
    }

    func testHeadingMarkersAreStripped() {
        let out = plain("## Introduction to the Logic of Dune\nBody.")
        XCTAssertFalse(out.contains("#"))
        XCTAssertEqual(out.components(separatedBy: "Introduction to the Logic").count - 1, 1)
    }

    func testBodyLineIsNotDuplicated() {
        let out = plain("just a normal sentence")
        XCTAssertEqual(out.components(separatedBy: "just a normal sentence").count - 1, 1)
    }

    func testMultipleHeadingsEachAppearOnce() {
        let out = plain("# One\ntext\n## Two\nmore")
        XCTAssertEqual(out.components(separatedBy: "One").count - 1, 1)
        XCTAssertEqual(out.components(separatedBy: "Two").count - 1, 1)
    }
}
