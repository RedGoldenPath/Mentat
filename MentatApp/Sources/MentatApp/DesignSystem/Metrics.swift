import SwiftUI

/// Panel metrics derived from the layout gutter and `DesignTokens.metrics`, so
/// every floating panel shares one rhythm instead of hard-coding its own.
enum PanelGrid {
    private static var m: DesignTokens.Metrics { DesignTokens.current.metrics }

    static func pad(_ gutter: Double) -> CGFloat { max(CGFloat(m.panelPadMin), CGFloat(gutter)) }
    static func gap(_ gutter: Double) -> CGFloat { max(4, CGFloat(gutter) / 2) }
    static func row(_ gutter: Double) -> CGFloat { max(6, CGFloat(gutter) * 0.75) }
    static func radius(_ gutter: Double) -> CGFloat {
        max(12, CGFloat(gutter) + CGFloat(m.panelRadiusPad))
    }
    static func border(_ pal: Palette) -> Color { Color.white.opacity(pal.isDark ? 0.15 : 0.35) }
}
