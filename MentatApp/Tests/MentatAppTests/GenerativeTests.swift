import XCTest

@testable import MentatApp

/// The generative-UI element schema: the model composes from a client-owned
/// vocabulary; unknown kinds degrade safely.
final class GenerativeTests: XCTestCase {
    func testParsesSceneObject() throws {
        let json = """
        {"title":"Q3","elements":[
          {"kind":"kpi","kpi":{"label":"Revenue","value":"$1.2M","delta":"+8%","deltaUp":true}},
          {"kind":"chart","chart":{"style":"bar","series":[{"label":"A","value":3},{"label":"B","value":5}]}}
        ]}
        """
        let spec = try XCTUnwrap(SceneParser.parse(json))
        XCTAssertEqual(spec.title, "Q3")
        XCTAssertEqual(spec.elements.count, 2)
        XCTAssertEqual(spec.elements[0].kind, .kpi)
        XCTAssertEqual(spec.elements[0].kpi?.value, "$1.2M")
        XCTAssertEqual(spec.elements[1].chart?.series.count, 2)
    }

    func testParsesBareArray() throws {
        let json = #"[{"kind":"text","text":"hello"}]"#
        let spec = try XCTUnwrap(SceneParser.parse(json))
        XCTAssertEqual(spec.elements.first?.kind, .text)
        XCTAssertEqual(spec.elements.first?.text, "hello")
    }

    func testUnknownKindDegrades() throws {
        let json = #"{"elements":[{"kind":"hologram","zzz":true}]}"#
        let spec = try XCTUnwrap(SceneParser.parse(json))
        XCTAssertEqual(spec.elements.first?.kind, .unknown)
    }

    func testInvalidJSONReturnsNil() {
        XCTAssertNil(SceneParser.parse("not json at all"))
    }

    func testSceneLanguages() {
        XCTAssertTrue(SceneParser.languages.contains("scene"))
        XCTAssertTrue(SceneParser.languages.contains("genui"))
    }

    func testExtractFromProse() {
        let prose = """
        Here you go.

        ```scene
        {"elements":[{"kind":"text","text":"hi"}]}
        ```

        Done.
        """
        let specs = SceneParser.extract(from: prose)
        XCTAssertEqual(specs.count, 1)
        XCTAssertEqual(specs.first?.elements.first?.kind, .text)
    }

    func testExtractIgnoresPlainCode() {
        let prose = "```swift\nlet x = 1\n```"
        XCTAssertTrue(SceneParser.extract(from: prose).isEmpty)
    }
}
