import XCTest

@testable import MentatApp

/// Fenced-block extraction for the Inspector's Artifacts tab.
final class ArtifactsTests: XCTestCase {
    func testSingleBlockWithLanguage() {
        let text = """
        Here is the fix:
        ```swift
        let x = 1
        print(x)
        ```
        Done.
        """
        let a = ArtifactParser.parse(text)
        XCTAssertEqual(a.count, 1)
        XCTAssertEqual(a[0].language, "swift")
        XCTAssertEqual(a[0].code, "let x = 1\nprint(x)")
    }

    func testMultipleBlocksPreserveOrderAndLanguage() {
        let text = "```python\nprint(1)\n```\nprose\n```bash\necho hi\n```"
        let a = ArtifactParser.parse(text)
        XCTAssertEqual(a.map(\.language), ["python", "bash"])
        XCTAssertEqual(a.map(\.code), ["print(1)", "echo hi"])
    }

    func testNoBlocks() {
        XCTAssertTrue(ArtifactParser.parse("just prose, no fences").isEmpty)
    }

    func testBlankLinesInsideBlockAreKept() {
        let text = "```\na\n\nb\n```"
        XCTAssertEqual(ArtifactParser.parse(text).first?.code, "a\n\nb")
    }

    func testUnterminatedBlockStillYields() {
        let text = "```json\n{\"a\": 1}"
        let a = ArtifactParser.parse(text)
        XCTAssertEqual(a.count, 1)
        XCTAssertEqual(a[0].language, "json")
        XCTAssertEqual(a[0].code, "{\"a\": 1}")
    }
}
