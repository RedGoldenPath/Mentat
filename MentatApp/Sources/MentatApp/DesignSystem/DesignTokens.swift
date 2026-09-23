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
    var chrome = Chrome()
    var inspector = Inspector()

    static let `default` = DesignTokens()

    /// The control language: circles, capsules, super-rounded cards, and the one
    /// focal per screen. Every piece of chrome draws its shape from here, so the
    /// vocabulary is data (editable in Design) rather than per-view literals.
    struct Chrome: Codable, Equatable, Sendable {
        var circle: Double = 38          // icon-button diameter
        var circleSmall: Double = 30
        var capsuleHeight: Double = 36
        var capsulePadH: Double = 16
        var radiusS: Double = 12         // chips / small cards
        var radiusM: Double = 18         // cards
        var radiusL: Double = 26         // panels
        var radiusXL: Double = 34        // hero plates
        var nestedInset: Double = 6      // concentric-corner rule
        var focal: Double = 28           // the one solid focal per screen
        var glassRim: Double = 0.30      // specular edge opacity
        var pressedScale: Double = 0.955
    }

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
        var display: Double = 30
        var title: Double = 16
        var micro: Double = 9
        var meta: Double = 9.5
        var caption: Double = 10
        var label: Double = 11
        var body: Double = 12
        var bodyMono: Double = 12.5
        var emphasis: Double = 14
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

// MARK: - Tolerant decoding

/// A string-addressed coding key so every token group can be decoded field by
/// field. A saved blob that predates a field (or a field added later) then keeps
/// its default instead of failing the whole decode and wiping the user's tokens.
private struct AnyKey: CodingKey {
    var stringValue: String
    var intValue: Int?
    init(_ s: String) {
        stringValue = s
        intValue = nil
    }
    init?(stringValue: String) {
        self.stringValue = stringValue
        intValue = nil
    }
    init?(intValue: Int) {
        self.intValue = intValue
        stringValue = String(intValue)
    }
}

extension KeyedDecodingContainer where Key == AnyKey {
    /// The stored value, or the default when the key is absent or malformed.
    func tolerant<T: Decodable>(_ key: String, _ fallback: T) -> T {
        (try? decode(T.self, forKey: AnyKey(key))) ?? fallback
    }
}

extension DesignTokens {
    init(from decoder: Decoder) throws {
        self = DesignTokens()
        let c = try decoder.container(keyedBy: AnyKey.self)
        typography = c.tolerant("typography", typography)
        motion = c.tolerant("motion", motion)
        metrics = c.tolerant("metrics", metrics)
        composition = c.tolerant("composition", composition)
        chrome = c.tolerant("chrome", chrome)
        inspector = c.tolerant("inspector", inspector)
    }
}

extension DesignTokens.Chrome {
    init(from decoder: Decoder) throws {
        self = DesignTokens.Chrome()
        let c = try decoder.container(keyedBy: AnyKey.self)
        circle = c.tolerant("circle", circle)
        circleSmall = c.tolerant("circleSmall", circleSmall)
        capsuleHeight = c.tolerant("capsuleHeight", capsuleHeight)
        capsulePadH = c.tolerant("capsulePadH", capsulePadH)
        radiusS = c.tolerant("radiusS", radiusS)
        radiusM = c.tolerant("radiusM", radiusM)
        radiusL = c.tolerant("radiusL", radiusL)
        radiusXL = c.tolerant("radiusXL", radiusXL)
        nestedInset = c.tolerant("nestedInset", nestedInset)
        focal = c.tolerant("focal", focal)
        glassRim = c.tolerant("glassRim", glassRim)
        pressedScale = c.tolerant("pressedScale", pressedScale)
    }
}

extension DesignTokens.Typography {
    init(from decoder: Decoder) throws {
        self = DesignTokens.Typography()
        let c = try decoder.container(keyedBy: AnyKey.self)
        fontSize = c.tolerant("fontSize", fontSize)
        measureChars = c.tolerant("measureChars", measureChars)
        maxChars = c.tolerant("maxChars", maxChars)
        maxColumns = c.tolerant("maxColumns", maxColumns)
        linesPerColumn = c.tolerant("linesPerColumn", linesPerColumn)
        lineSpacing = c.tolerant("lineSpacing", lineSpacing)
        paragraphSpacing = c.tolerant("paragraphSpacing", paragraphSpacing)
        display = c.tolerant("display", display)
        title = c.tolerant("title", title)
        micro = c.tolerant("micro", micro)
        meta = c.tolerant("meta", meta)
        caption = c.tolerant("caption", caption)
        label = c.tolerant("label", label)
        body = c.tolerant("body", body)
        bodyMono = c.tolerant("bodyMono", bodyMono)
        emphasis = c.tolerant("emphasis", emphasis)
    }
}

extension DesignTokens.Motion {
    init(from decoder: Decoder) throws {
        self = DesignTokens.Motion()
        let c = try decoder.container(keyedBy: AnyKey.self)
        smoothDuration = c.tolerant("smoothDuration", smoothDuration)
        snappyDuration = c.tolerant("snappyDuration", snappyDuration)
        snappyBounce = c.tolerant("snappyBounce", snappyBounce)
        bubbleBounce = c.tolerant("bubbleBounce", bubbleBounce)
        pageSlide = c.tolerant("pageSlide", pageSlide)
    }
}

extension DesignTokens.Metrics {
    init(from decoder: Decoder) throws {
        self = DesignTokens.Metrics()
        let c = try decoder.container(keyedBy: AnyKey.self)
        panelPadMin = c.tolerant("panelPadMin", panelPadMin)
        panelRadiusPad = c.tolerant("panelRadiusPad", panelRadiusPad)
        sidebarMin = c.tolerant("sidebarMin", sidebarMin)
        sidebarIdeal = c.tolerant("sidebarIdeal", sidebarIdeal)
        sidebarMax = c.tolerant("sidebarMax", sidebarMax)
    }
}

extension DesignTokens.Composition {
    init(from decoder: Decoder) throws {
        self = DesignTokens.Composition()
        let c = try decoder.container(keyedBy: AnyKey.self)
        headerHeight = c.tolerant("headerHeight", headerHeight)
        composerHeight = c.tolerant("composerHeight", composerHeight)
        bubbleCorner = c.tolerant("bubbleCorner", bubbleCorner)
        bubblePaddingH = c.tolerant("bubblePaddingH", bubblePaddingH)
        bubblePaddingTop = c.tolerant("bubblePaddingTop", bubblePaddingTop)
        bubblePaddingBottom = c.tolerant("bubblePaddingBottom", bubblePaddingBottom)
        roleHeaderTop = c.tolerant("roleHeaderTop", roleHeaderTop)
    }
}

extension DesignTokens.Inspector {
    init(from decoder: Decoder) throws {
        self = DesignTokens.Inspector()
        let c = try decoder.container(keyedBy: AnyKey.self)
        showGrid = c.tolerant("showGrid", showGrid)
        showLines = c.tolerant("showLines", showLines)
        lineOpacity = c.tolerant("lineOpacity", lineOpacity)
        lineBand = c.tolerant("lineBand", lineBand)
        lineFeather = c.tolerant("lineFeather", lineFeather)
        numbers = c.tolerant("numbers", numbers)
        scope = c.tolerant("scope", scope)
        headerHeight = c.tolerant("headerHeight", headerHeight)
    }
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
