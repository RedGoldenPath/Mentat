import Foundation

/// A model-authored interface, composed from a **client-owned vocabulary** (the
/// kinds below) and delivered as JSON. This is the registry-based generative-UI
/// path from Vercel `streamUI` / Claude tool-use: the model composes, the client
/// owns the components and can never be handed arbitrary code.
struct SceneSpec: Decodable {
    var title: String?
    var elements: [GenElement]
}

/// One generated element. Unknown kinds degrade to a safe fallback instead of
/// crashing — the SDUI rule.
struct GenElement: Decodable, Identifiable {
    let id = UUID()
    var kind: Kind
    var kpi: KPI?
    var chart: Chart?
    var table: Table?
    var diagram: Diagram?
    var text: String?

    enum Kind: String, Decodable { case kpi, chart, table, diagram, text, unknown }

    struct KPI: Decodable {
        var label: String
        var value: String
        var delta: String?
        var deltaUp: Bool?
    }
    struct Chart: Decodable {
        var style: String?      // "bar" | "line"
        var title: String?
        var series: [Point]
        struct Point: Decodable { var label: String; var value: Double }
    }
    struct Table: Decodable {
        var title: String?
        var columns: [String]
        var rows: [[String]]
    }
    struct Diagram: Decodable {
        var title: String?
        var nodes: [String]
        var edges: [[Int]]?     // pairs of node indices
    }

    private enum CodingKeys: String, CodingKey {
        case kind, kpi, chart, table, diagram, text
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let raw = (try? c.decode(String.self, forKey: .kind)) ?? "unknown"
        kind = Kind(rawValue: raw) ?? .unknown
        kpi = try? c.decode(KPI.self, forKey: .kpi)
        chart = try? c.decode(Chart.self, forKey: .chart)
        table = try? c.decode(Table.self, forKey: .table)
        diagram = try? c.decode(Diagram.self, forKey: .diagram)
        text = try? c.decode(String.self, forKey: .text)
    }
}

/// Parse a fenced scene block: either a `{ "elements": [...] }` object or a bare
/// element array. Pure and testable.
enum SceneParser {
    static let languages: Set<String> = ["scene", "genui", "ui", "mentat"]

    /// Every fenced scene block in a piece of prose, in order — so a generated
    /// view can render inline in the transcript, not only in the Inspector.
    static func extract(from text: String) -> [SceneSpec] {
        var specs: [SceneSpec] = []
        var inBlock = false
        var language = ""
        var buffer: [String] = []
        for line in text.components(separatedBy: .newlines) {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            if trimmed.hasPrefix("```") {
                if inBlock {
                    if languages.contains(language), let spec = parse(buffer.joined(separator: "\n")) {
                        specs.append(spec)
                    }
                    inBlock = false; language = ""; buffer = []
                } else {
                    inBlock = true
                    language = String(trimmed.dropFirst(3))
                        .trimmingCharacters(in: .whitespaces).lowercased()
                }
                continue
            }
            if inBlock { buffer.append(line) }
        }
        return specs
    }

    static func parse(_ body: String) -> SceneSpec? {
        guard let data = body.data(using: .utf8) else { return nil }
        if let spec = try? JSONDecoder().decode(SceneSpec.self, from: data) {
            return spec
        }
        if let elements = try? JSONDecoder().decode([GenElement].self, from: data) {
            return SceneSpec(title: nil, elements: elements)
        }
        return nil
    }
}
