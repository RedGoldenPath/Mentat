import AppKit

/// Semantic text colours — the reading-surface analogue of an editor's syntax
/// theme. One data-driven palette per `SurfaceLook`, so a quote, a heading, a
/// link, a citation and a number each read distinctly while staying cohesive.
///
/// References: VS Code / opencode semantic tokens; Apple HIG *Color* (colour is
/// never the *only* cue — headings/italics/underline stay as redundant signals).
struct TextInk {
    var body: NSColor
    var heading: NSColor
    var quote: NSColor
    var link: NSColor
    var citation: NSColor
    var number: NSColor
    var dim: NSColor

    /// The brand mark: a constant warm sand. On light surfaces the pale sand
    /// vanishes, so the mark deepens to a legible warm brown while keeping its
    /// brand tone (Apple HIG *Color* — decorative text still needs contrast).
    static let brandSand = NSColor(srgbRed: 0.906, green: 0.827, blue: 0.671, alpha: 1)
    static let brandSandDeep = NSColor(srgbRed: 0.50, green: 0.39, blue: 0.20, alpha: 1)

    static func brandMark(isLight: Bool) -> NSColor { isLight ? brandSandDeep : brandSand }

    static func look(_ look: SurfaceLook, isDark: Bool) -> TextInk {
        let t = ColorTheme.look(look, isDark: isDark)
        let gold = NSColor(srgbRed: 0.95, green: 0.80, blue: 0.45, alpha: 1)
        let darkSand = NSColor(srgbRed: 0.50, green: 0.39, blue: 0.20, alpha: 1)
        let darkGold = NSColor(srgbRed: 0.56, green: 0.41, blue: 0.11, alpha: 1)
        // Links read like an editor's hyperlink: a cool blue, distinct from the
        // warm heading/quote family.
        let darkLink = NSColor(srgbRed: 0.55, green: 0.75, blue: 1.0, alpha: 1)
        let lightLink = NSColor(srgbRed: 0.10, green: 0.42, blue: 0.85, alpha: 1)
        switch look {
        case .sand:
            return TextInk(
                body: NSColor(t.ink), heading: NSColor(t.accent), quote: brandSand,
                link: darkLink, citation: NSColor(t.inkDim), number: gold,
                dim: NSColor(t.inkDim))
        case .mono:
            // Mono stays grayscale, with a whisper of warmth on quotes.
            return TextInk(
                body: NSColor(t.ink), heading: NSColor(white: 0.90, alpha: 1),
                quote: NSColor(white: 0.86, alpha: 1), link: NSColor(t.ink),
                citation: NSColor(white: 0.62, alpha: 1), number: NSColor(white: 0.88, alpha: 1),
                dim: NSColor(white: 0.62, alpha: 1))
        case .paper:
            return TextInk(
                body: NSColor(t.ink), heading: NSColor(t.accent), quote: darkSand,
                link: lightLink, citation: NSColor(t.inkDim), number: darkGold,
                dim: NSColor(t.inkDim))
        case .system:
            if isDark {
                return TextInk(
                    body: NSColor(t.ink), heading: NSColor(t.accent), quote: brandSand,
                    link: darkLink, citation: NSColor(t.inkDim), number: gold,
                    dim: NSColor(t.inkDim))
            }
            return TextInk(
                body: NSColor(t.ink), heading: NSColor(t.accent), quote: darkSand,
                link: lightLink, citation: NSColor(t.inkDim), number: darkGold,
                dim: NSColor(t.inkDim))
        }
    }

    /// Stable cache key (the attributed-string memo keys on it).
    var cacheKey: String {
        [body, heading, quote, link, citation, number, dim]
            .map { $0.description }.joined(separator: "|")
    }
}
