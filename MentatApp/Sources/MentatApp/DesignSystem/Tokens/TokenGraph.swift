import Foundation
import SwiftUI

// =============================================================================
// MARK: - Token vocabulary (W3C Design Tokens shaped)
// =============================================================================

/// The token types we support (W3C "type" + the composite types we use).
enum TokenType: String, Codable, CaseIterable, Sendable {
    case color, dimension, duration, number
    case fontFamily, fontWeight, cubicBezier
    case shadow, gradient, typography, border, strokeStyle
}

struct GradientStop: Equatable, Sendable {
    var position: Double
    var color: String   // hex "#rrggbb" (or "#rrggbbaa")
}

struct ShadowValue: Equatable, Sendable {
    var color: String
    var offsetX: Double
    var offsetY: Double
    var blur: Double
    var spread: Double
}

struct TypographyValue: Equatable, Sendable {
    var fontFamily: String?
    var fontSize: Double
    var fontWeight: Int?
    var lineHeight: Double?
    var letterSpacing: Double?
}

struct BorderValue: Equatable, Sendable {
    var color: String
    var width: Double
    var style: String   // "solid" | "dashed" | "dotted"
}

/// A resolved token value. Colors are kept as hex strings so the graph is
/// platform-agnostic and round-trips through W3C JSON.
enum TokenValue: Equatable, Sendable {
    case color(String)
    case dimension(Double)          // points
    case duration(Double)           // seconds
    case number(Double)
    case fontFamily(String)
    case fontWeight(Int)
    case cubicBezier([Double])
    case shadow(ShadowValue)
    case gradient([GradientStop])
    case typography(TypographyValue)
    case border(BorderValue)
    case strokeStyle(Double)
}

/// One token: a name, a type, and either a value or an alias to another token.
struct Token: Equatable, Sendable {
    var path: String
    var type: TokenType
    var value: TokenValue?
    var alias: String?          // "{color.surface}"
    var description: String?
    var deprecated: Bool = false

    var isAlias: Bool { alias != nil }
}

enum TokenError: Error, Equatable {
    case missing(String)
    case cycle(String)
    case typeMismatch(String)
    case malformed(String)
}

// =============================================================================
// MARK: - The graph
// =============================================================================

/// The token graph: a flat table of `path -> Token`, with alias resolution and
/// cycle detection. This is the "unified memory" every element resolves from.
struct TokenGraph: Equatable {
    private(set) var tokens: [String: Token] = [:]

    init(tokens: [Token] = []) {
        for t in tokens { self.tokens[t.path] = t }
    }

    func token(_ path: String) -> Token? { tokens[path] }
    var allPaths: [String] { tokens.keys.sorted() }

    // MARK: resolution

    /// Resolve a path or a `{path}` alias reference to a concrete value.
    func resolve(_ reference: String) throws -> TokenValue {
        var seen: Set<String> = []
        var current = Self.normalize(reference)
        while true {
            if seen.contains(current) { throw TokenError.cycle(current) }
            seen.insert(current)
            guard let t = tokens[current] else { throw TokenError.missing(current) }
            if let alias = t.alias {
                current = Self.normalize(alias)
                continue
            }
            guard let v = t.value else { throw TokenError.missing(current) }
            return v
        }
    }

    /// The type a reference ultimately resolves to (following aliases).
    func resolveType(_ reference: String) throws -> TokenType {
        var seen: Set<String> = []
        var current = Self.normalize(reference)
        while true {
            if seen.contains(current) { throw TokenError.cycle(current) }
            seen.insert(current)
            guard let t = tokens[current] else { throw TokenError.missing(current) }
            if let alias = t.alias {
                current = Self.normalize(alias)
                continue
            }
            return t.type
        }
    }

    // MARK: typed accessors

    func color(_ reference: String) throws -> Color {
        guard case let .color(hex) = try resolve(reference) else {
            throw TokenError.typeMismatch(reference)
        }
        return Color(tokenHex: hex)
    }

    func point(_ reference: String) throws -> CGFloat {
        switch try resolve(reference) {
        case let .dimension(v), let .number(v): return CGFloat(v)
        case let .duration(v): return CGFloat(v)
        default: throw TokenError.typeMismatch(reference)
        }
    }

    func seconds(_ reference: String) throws -> Double {
        guard case let .duration(v) = try resolve(reference) else {
            throw TokenError.typeMismatch(reference)
        }
        return v
    }

    func shadow(_ reference: String) throws -> ShadowValue {
        guard case let .shadow(v) = try resolve(reference) else {
            throw TokenError.typeMismatch(reference)
        }
        return v
    }

    static func normalize(_ reference: String) -> String {
        reference.trimmingCharacters(in: CharacterSet(charactersIn: "{} "))
    }

    // MARK: - W3C JSON

    /// Decode a W3C `.tokens.json` document. Groups nest; any object with a
    /// `$value` (or a `$ref`) is a token; types inherit from the nearest `$type`.
    static func decode(_ data: Data) throws -> TokenGraph {
        guard let root = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw TokenError.malformed("root is not an object")
        }
        var graph = TokenGraph()
        try walk(root, prefix: [], inheritedType: nil, into: &graph)
        return graph
    }

    private static func walk(
        _ node: [String: Any], prefix: [String], inheritedType: TokenType?, into graph: inout TokenGraph
    ) throws {
        let ownType = (node["$type"] as? String).flatMap(TokenType.init(rawValue:)) ?? inheritedType
        let isToken = node["$value"] != nil || node["$ref"] != nil
        if isToken {
            let path = prefix.joined(separator: ".")
            guard let type = ownType else { throw TokenError.malformed("no $type for \(path)") }
            var token = Token(path: path, type: type,
                              description: node["$description"] as? String,
                              deprecated: (node["$deprecated"] as? Bool) ?? false)
            if let ref = node["$ref"] as? String {
                token.alias = ref
            } else if let s = node["$value"] as? String, s.hasPrefix("{") {
                token.alias = s              // "{alias}" string form
            } else {
                token.value = parseValue(node["$value"] as Any, type: type)
            }
            graph.tokens[path] = token
            return
        }
        for (key, child) in node where !key.hasPrefix("$") {
            if let childObj = child as? [String: Any] {
                try walk(childObj, prefix: prefix + [key], inheritedType: ownType, into: &graph)
            }
        }
    }

    private static func parseValue(_ any: Any, type: TokenType) -> TokenValue? {
        switch type {
        case .color:
            if let s = any as? String { return .color(s) }
            if let o = any as? [String: Any] {
                if let hex = o["hex"] as? String { return .color(hex) }
                if let comps = o["components"] as? [Double], comps.count == 3 {
                    let a = o["alpha"] as? Double ?? 1
                    return .color(hexString(comps[0], comps[1], comps[2], a))
                }
            }
        case .dimension:
            if let o = any as? [String: Any], let v = o["value"] as? Double { return .dimension(v) }
            if let d = any as? Double { return .dimension(d) }
        case .duration:
            if let o = any as? [String: Any], let v = o["value"] as? Double {
                let unit = o["unit"] as? String ?? "ms"
                return .duration(unit == "s" ? v : v / 1000)
            }
            if let d = any as? Double { return .duration(d / 1000) }
        case .number:
            if let d = any as? Double { return .number(d) }
        case .fontFamily:
            if let s = any as? String { return .fontFamily(s) }
        case .fontWeight:
            if let i = any as? Int { return .fontWeight(i) }
        case .cubicBezier:
            if let a = any as? [Double], a.count == 4 { return .cubicBezier(a) }
        case .shadow:
            if let o = any as? [String: Any] {
                return .shadow(ShadowValue(
                    color: (o["color"] as? String) ?? "#000000",
                    offsetX: o["offsetX"] as? Double ?? 0,
                    offsetY: o["offsetY"] as? Double ?? 0,
                    blur: o["blur"] as? Double ?? 0,
                    spread: o["spread"] as? Double ?? 0))
            }
        case .gradient:
            if let a = any as? [[String: Any]] {
                return .gradient(a.compactMap { s in
                    guard let color = s["color"] as? String else { return nil }
                    return GradientStop(position: s["position"] as? Double ?? 0, color: color)
                })
            }
        case .typography:
            if let o = any as? [String: Any], let size = o["fontSize"] as? Double {
                return .typography(TypographyValue(
                    fontFamily: o["fontFamily"] as? String, fontSize: size,
                    fontWeight: o["fontWeight"] as? Int,
                    lineHeight: o["lineHeight"] as? Double,
                    letterSpacing: o["letterSpacing"] as? Double))
            }
        case .border:
            if let o = any as? [String: Any] {
                return .border(BorderValue(
                    color: o["color"] as? String ?? "#000000",
                    width: o["width"] as? Double ?? 1,
                    style: o["style"] as? String ?? "solid"))
            }
        case .strokeStyle:
            if let d = any as? Double { return .strokeStyle(d) }
        }
        return nil
    }

    /// Encode a W3C `.tokens.json` document (pretty-printed).
    func encode() throws -> Data {
        var root: [String: Any] = [:]
        for token in tokens.values {
            var leaf: [String: Any] = ["$type": token.type.rawValue]
            if let alias = token.alias {
                leaf["$value"] = alias
            } else if let value = token.value {
                leaf["$value"] = encodeValue(value)
            }
            if let d = token.description { leaf["$description"] = d }
            if token.deprecated { leaf["$deprecated"] = true }
            insert(leaf, at: token.path.split(separator: ".").map(String.init),
                   ignored: token.type.rawValue, into: &root)
        }
        return try JSONSerialization.data(withJSONObject: root,
                                          options: [.prettyPrinted, .sortedKeys])
    }

    private func insert(_ leaf: [String: Any], at parts: [String],
                        ignored: String, into node: inout [String: Any]) {
        guard let head = parts.first else { return }
        if parts.count == 1 { node[head] = leaf; return }
        var child = node[head] as? [String: Any] ?? [:]
        insert(leaf, at: Array(parts.dropFirst()), ignored: ignored, into: &child)
        node[head] = child
    }

    private func encodeValue(_ v: TokenValue) -> Any {
        switch v {
        case let .color(hex):
            let (r, g, b, a) = Self.components(hex)
            return ["colorSpace": "srgb", "components": [r, g, b], "alpha": a, "hex": hex]
        case let .dimension(v): return ["value": v, "unit": "px"]
        case let .duration(v): return ["value": v * 1000, "unit": "ms"]
        case let .number(v): return v
        case let .fontFamily(s): return s
        case let .fontWeight(i): return i
        case let .cubicBezier(a): return a
        case let .shadow(s):
            return ["color": s.color, "offsetX": s.offsetX, "offsetY": s.offsetY,
                    "blur": s.blur, "spread": s.spread]
        case let .gradient(stops): return stops.map { ["color": $0.color, "position": $0.position] }
        case let .typography(t):
            var o: [String: Any] = ["fontSize": t.fontSize]
            if let f = t.fontFamily { o["fontFamily"] = f }
            if let w = t.fontWeight { o["fontWeight"] = w }
            if let l = t.lineHeight { o["lineHeight"] = l }
            if let s = t.letterSpacing { o["letterSpacing"] = s }
            return o
        case let .border(b): return ["color": b.color, "width": b.width, "style": b.style]
        case let .strokeStyle(v): return v
        }
    }

    // MARK: hex helpers

    static func hexString(_ r: Double, _ g: Double, _ b: Double, _ a: Double = 1) -> String {
        func c(_ v: Double) -> Int { max(0, min(255, Int((v * 255).rounded()))) }
        if a >= 0.999 { return String(format: "#%02X%02X%02X", c(r), c(g), c(b)) }
        return String(format: "#%02X%02X%02X%02X", c(r), c(g), c(b), c(a))
    }

    static func components(_ hex: String) -> (Double, Double, Double, Double) {
        var s = hex.trimmingCharacters(in: CharacterSet(charactersIn: "# ")).uppercased()
        if s.count == 3 { s = s.map { "\($0)\($0)" }.joined() }
        var value: UInt64 = 0
        Scanner(string: s).scanHexInt64(&value)
        switch s.count {
        case 8:
            return (Double((value >> 24) & 0xFF) / 255, Double((value >> 16) & 0xFF) / 255,
                    Double((value >> 8) & 0xFF) / 255, Double(value & 0xFF) / 255)
        default:
            return (Double((value >> 16) & 0xFF) / 255, Double((value >> 8) & 0xFF) / 255,
                    Double(value & 0xFF) / 255, 1)
        }
    }
}

// MARK: - Color from token hex

extension Color {
    /// Build a SwiftUI `Color` from a token hex string (`#rgb[a]` / `#rrggbb[aa]`).
    init(tokenHex hex: String) {
        let (r, g, b, a) = TokenGraph.components(hex)
        self.init(.sRGB, red: r, green: g, blue: b, opacity: a)
    }
}
