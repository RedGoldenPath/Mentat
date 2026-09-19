import AppKit
import CoreText

/// The reading type system: a justified, monospaced, book-ish treatment plus the
/// typographic *measure* rules (column width, lines-per-column, column ceiling)
/// that the paginator obeys. Kept free of SwiftUI so it can be unit-tested.
enum TextStyle {
    /// Strip a trailing auto-generated `References` block from an answer.
    static func clean(_ raw: String) -> String {
        var t = raw
        let patterns = [
            #"\n#{1,6}\s*References\b[\s\S]*$"#,
            #"\n\*\*References\*\*[\s\S]*$"#,
            #"\n\s*References\s*\n[\s\S]*$"#,
        ]
        for p in patterns {
            if let r = t.range(of: p, options: .regularExpression) {
                t = String(t[..<r.lowerBound])
                break
            }
        }
        return t.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// Typography is data-driven — see `DesignTokens.typography`.
    static var fontSize: CGFloat { CGFloat(DesignTokens.current.typography.fontSize) }
    static func monoFont(_ weight: NSFont.Weight = .regular, size: CGFloat? = nil) -> NSFont {
        NSFont.monospacedSystemFont(ofSize: size ?? fontSize, weight: weight)
    }
    static func italicFont(size: CGFloat? = nil) -> NSFont {
        let sz = size ?? fontSize
        let base = NSFont.monospacedSystemFont(ofSize: sz, weight: .regular)
        let d = base.fontDescriptor.withSymbolicTraits(.italic)
        return NSFont(descriptor: d, size: sz) ?? base
    }
    /// Width of `chars` monospace characters (book measure).
    static func measure(chars: Int? = nil, size: CGFloat? = nil) -> CGFloat {
        let n = chars ?? DesignTokens.current.typography.measureChars
        let sz = size ?? fontSize
        let font =
            sz == fontSize
            ? monoFont() : NSFont.monospacedSystemFont(ofSize: sz, weight: .regular)
        return CGFloat(n) * ("M" as NSString).size(withAttributes: [.font: font]).width
    }
    /// Hard ceiling on a text column's line length: no line should read wider
    /// than this many characters (the typographic *measure*).
    static var maxChars: Int { DesignTokens.current.typography.maxChars }
    /// Hard ceiling on how many text columns a bubble may ever split into.
    static var maxColumns: Int { DesignTokens.current.typography.maxColumns }
    /// Lines a single column holds before spilling into the next.
    static var linesPerColumn: Int { DesignTokens.current.typography.linesPerColumn }
    /// The width of the widest allowed text column, at `size`.
    static func maxMeasure(size: CGFloat = TextStyle.fontSize) -> CGFloat {
        measure(chars: maxChars, size: size)
    }
    /// Width the text needs (longest line), capped at the measure.
    static func hugWidth(_ text: String, max measure: CGFloat) -> CGFloat {
        let cw = ("M" as NSString).size(withAttributes: [.font: monoFont()]).width
        let longest = text.components(separatedBy: "\n").map(\.count).max() ?? 1
        return min(measure, max(24, CGFloat(longest) * cw))
    }

    private enum Run { case normal, bold, italic }

    /// Split a line into runs, honouring **bold**, *italic*, and dropping the
    /// marker characters (and stray carets) instead of showing them.
    private static func runs(_ s: String) -> [(String, Run)] {
        var out: [(String, Run)] = []
        var style: Run = .normal
        var buf = ""
        var i = s.startIndex
        func flush() {
            if !buf.isEmpty {
                out.append((buf, style))
                buf = ""
            }
        }
        while i < s.endIndex {
            let c = s[i]
            if c == "*" {
                flush()
                if let n = s.index(i, offsetBy: 1, limitedBy: s.endIndex), n < s.endIndex,
                    s[n] == "*"
                {
                    style = (style == .bold) ? .normal : .bold
                    i = s.index(after: n)
                } else {
                    style = (style == .italic) ? .normal : .italic
                    i = s.index(after: i)
                }
                continue
            }
            if c == "^" || c == "`" {
                i = s.index(after: i)
                continue
            }
            buf.append(c)
            i = s.index(after: i)
        }
        flush()
        return out
    }

    /// Build a justified, monospaced, book-ish attributed string.
    ///
    /// Cached so streaming/long answers don't rebuild the attributed string on
    /// every render. Keyed on length + params (no O(n) hashing); the exact string
    /// is verified on a hit, so streaming growth never hashes per frame. When
    /// `baseline > 0` the line spacing lands each line on the baseline grid.
    private struct AttrEntry {
        let raw: String
        let attr: NSAttributedString
    }
    /// TRANSITIONAL: main-thread-only memo cache; the rewritten reader owns its
    /// isolation properly.
    nonisolated(unsafe) private static var attrCache: [String: AttrEntry] = [:]

    static func attributed(
        _ raw: String, color: NSColor,
        alignment: NSTextAlignment = .justified,
        baseline: CGFloat = 0,
        size: CGFloat? = nil
    ) -> NSAttributedString {
        let sz = size ?? fontSize
        let key =
            "\(alignment.rawValue)|\(color.description)|\(Int(baseline))|\(Int(sz))|\(raw.count)"
        if let hit = attrCache[key], hit.raw == raw { return hit.attr }
        let built = build(raw, color: color, alignment: alignment, baseline: baseline, size: sz)
        if attrCache.count > 300 { attrCache.removeAll() }
        attrCache[key] = AttrEntry(raw: raw, attr: built)
        return built
    }

    private static func build(
        _ raw: String, color: NSColor,
        alignment: NSTextAlignment,
        baseline: CGFloat,
        size: CGFloat
    ) -> NSAttributedString {
        // Snap lines to the baseline grid when one is set; else the tuned spacing
        // from the design tokens.
        let tuned = CGFloat(DesignTokens.current.typography.lineSpacing)
        let lineSpacing = baseline > 2 ? max(tuned, baseline - size * 1.45) : tuned
        let base: [NSAttributedString.Key: Any] = [
            .font: monoFont(.regular, size: size), .foregroundColor: color,
        ]
        let bold: [NSAttributedString.Key: Any] = [
            .font: monoFont(.bold, size: size), .foregroundColor: color,
        ]
        let ital: [NSAttributedString.Key: Any] = [
            .font: italicFont(size: size), .foregroundColor: color,
        ]
        let out = NSMutableAttributedString()
        let lines = raw.components(separatedBy: "\n")
        for (idx, line) in lines.enumerated() {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            let para = NSMutableParagraphStyle()
            para.alignment = alignment
            para.lineSpacing = lineSpacing
            para.paragraphSpacing = CGFloat(DesignTokens.current.typography.paragraphSpacing)
            var body = line
            if let m = trimmed.range(of: #"^#{1,6}\s+"#, options: .regularExpression) {
                body = String(trimmed[m.upperBound...])
                out.append(NSAttributedString(string: body, attributes: bold))
            } else if trimmed.hasPrefix(">") {
                body = String(trimmed.dropFirst()).trimmingCharacters(in: .whitespaces)
                let pq = para
                pq.alignment = .left
                pq.headIndent = 24
                pq.firstLineHeadIndent = 24
                pq.tailIndent = -8
                for (t, st) in runs(body) {
                    switch st {
                    case .normal, .italic:
                        out.append(NSAttributedString(string: t, attributes: ital))
                    case .bold: out.append(NSAttributedString(string: t, attributes: bold))
                    }
                }
                out.addAttribute(
                    .paragraphStyle, value: pq,
                    range: NSRange(location: out.length - body.count, length: body.count))
                if idx < lines.count - 1 {
                    out.append(NSAttributedString(string: "\n", attributes: base))
                }
                continue
            } else if let m = trimmed.range(of: #"^[-*]\s+"#, options: .regularExpression) {
                body = "•  " + String(trimmed[m.upperBound...])
                para.headIndent = 18
                para.firstLineHeadIndent = 0
            }
            let start = out.length
            for (t, st) in runs(body) {
                switch st {
                case .normal: out.append(NSAttributedString(string: t, attributes: base))
                case .bold: out.append(NSAttributedString(string: t, attributes: bold))
                case .italic: out.append(NSAttributedString(string: t, attributes: ital))
                }
            }
            // citations like (Dune · Chapter 3) in italics
            let re = try? NSRegularExpression(pattern: "\\(([^()\\n]{3,90}) · ([^()\\n]{1,90})\\)")
            re?.enumerateMatches(
                in: out.string, range: NSRange(location: start, length: out.length - start)
            ) { m, _, _ in
                if let r = m?.range { out.addAttribute(.font, value: italicFont(size: size), range: r) }
            }
            if idx < lines.count - 1 {
                out.append(NSAttributedString(string: "\n", attributes: base))
            }
            out.addAttribute(
                .paragraphStyle, value: para,
                range: NSRange(location: start, length: out.length - start))
        }
        return out
    }
}

/// Monospaced, justified body text via a real text engine.
enum TextLayout {
    /// Keyed on the attributed string's *identity* + width, so a hit is O(1).
    /// (`Typography.attributed` returns cached instances, so identity is stable.)
    private struct LineKey: Hashable {
        let id: ObjectIdentifier
        let width: Int
    }
    /// TRANSITIONAL: main-thread-only memo cache; the rewritten reader owns its
    /// isolation properly.
    nonisolated(unsafe) private static var cache: [LineKey: [NSRange]] = [:]

    /// Exact line breaks for an attributed string at a given width (Core Text).
    /// Memoized — this is the expensive part during streaming.
    static func lineRanges(_ attr: NSAttributedString, width: CGFloat) -> [NSRange] {
        guard attr.length > 0 else { return [] }
        let w = max(20, width)
        let key = LineKey(id: ObjectIdentifier(attr), width: Int(w))
        if let hit = cache[key] { return hit }
        let ts = CTTypesetterCreateWithAttributedString(attr as CFAttributedString)
        var out: [NSRange] = []
        var start = 0
        while start < attr.length {
            let n = max(1, CTTypesetterSuggestLineBreak(ts, start, Double(w)))
            out.append(NSRange(location: start, length: n))
            start += n
        }
        if cache.count > 160 { cache.removeAll() }
        cache[key] = out
        return out
    }
}
