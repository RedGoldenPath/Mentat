import SwiftUI

/// The single source of truth for the app's design: type, motion, metrics, and
/// screen composition. Everything the UI draws from is here, so Settings/Debug
/// edit the same data the app renders — instead of numbers scattered in views.
///
/// Layout lives in `LayoutGridStore`; colour lives in `ColorControls`/`ColorTheme`.
struct DesignTokens: Codable, Equatable, Sendable {
    var typography = Typography()
    var motion = Motion()
    var metrics = Metrics()
    var composition = Composition()
    var inspector = Inspector()

    static let `default` = DesignTokens()

    /// Grid-display settings (the always-on feather + the numeric inspector),
    /// so they live in the same data as everything else rather than as loose
    /// `@AppStorage` keys.
    struct Inspector: Codable, Equatable, Sendable {
        var showGrid: Bool = false
        var showLines: Bool = true
        var lineOpacity: Double = 0.18
        var lineBand: Double = 40
        var lineFeather: Double = 1
        var numbers: Bool = true
        var scope: String = "both"
        var headerHeight: Double = 68
    }

    struct Typography: Codable, Equatable, Sendable {
        var fontSize: Double = 12.5
        var measureChars: Int = 40
        var maxChars: Int = 55
        var maxColumns: Int = 3
        var linesPerColumn: Int = 30
        var lineSpacing: Double = 3.5
        var paragraphSpacing: Double = 6
        // Semantic size scale (used via `TypeScale`).
        var micro: Double = 9
        var meta: Double = 9.5
        var caption: Double = 10
        var label: Double = 11
        var body: Double = 12
        var bodyMono: Double = 12.5
        var emphasis: Double = 13
    }

    struct Motion: Codable, Equatable, Sendable {
        var smoothDuration: Double = 0.3
        var snappyDuration: Double = 0.3
        var snappyBounce: Double = 0.0
        var bubbleBounce: Double = 0.12
        var pageSlide: Double = 16
    }

    struct Metrics: Codable, Equatable, Sendable {
        var panelPadMin: Double = 10
        var panelRadiusPad: Double = 6
        var sidebarMin: Double = 250
        var sidebarIdeal: Double = 320
        var sidebarMax: Double = 440
    }

    struct Composition: Codable, Equatable, Sendable {
        var headerHeight: Double = 68
        var composerHeight: Double = 64
        var bubbleCorner: Double = 20
        var bubblePaddingH: Double = 18
        var bubblePaddingTop: Double = 13
        var bubblePaddingBottom: Double = 15
        var roleHeaderTop: Double = 40
    }
}

extension DesignTokens {
    /// Transitional single source read by the static design helpers (`Anim`,
    /// `PanelGrid`, `TextStyle`). Kept in sync by `DesignStore`.
    nonisolated(unsafe) static var current = DesignTokens()
}

private struct DesignTokensKey: EnvironmentKey {
    static let defaultValue = DesignTokens.default
}

extension EnvironmentValues {
    var design: DesignTokens {
        get { self[DesignTokensKey.self] }
        set { self[DesignTokensKey.self] = newValue }
    }
}
