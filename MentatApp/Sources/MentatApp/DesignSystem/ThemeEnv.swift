import SwiftUI
import AppKit

// MARK: - Palettes (Hue = colour theory over the art, Noir = black & white)

struct Palette {
    let isDark: Bool
    let bg, bg2: Color
    let panelTint, panelHi: Color
    let sand, dune, terracotta, spice, gold, ibad: Color
    let text, textDim: Color
    let border, rim: Color
    let good, bad: Color

    static let night = Palette(
        isDark: true,
        bg: Color(red: 0.086, green: 0.067, blue: 0.047),
        bg2: Color(red: 0.153, green: 0.106, blue: 0.072),
        panelTint: Color(red: 0.160, green: 0.110, blue: 0.070).opacity(0.26),
        panelHi: Color(red: 0.220, green: 0.160, blue: 0.100),
        sand: Color(red: 0.906, green: 0.827, blue: 0.671),
        dune: Color(red: 0.784, green: 0.627, blue: 0.416),
        terracotta: Color(red: 0.769, green: 0.439, blue: 0.235),
        spice: Color(red: 0.918, green: 0.616, blue: 0.353),
        gold: Color(red: 0.902, green: 0.753, blue: 0.475),
        ibad: Color(red: 0.494, green: 0.651, blue: 0.780),
        text: Color(red: 0.957, green: 0.914, blue: 0.839),
        textDim: Color(red: 0.663, green: 0.541, blue: 0.400),
        border: Color(red: 0.353, green: 0.251, blue: 0.157),
        rim: .white,
        good: Color(red: 0.565, green: 0.757, blue: 0.529),
        bad: Color(red: 0.831, green: 0.443, blue: 0.376))

    static let day = Palette(
        isDark: false,
        bg: Color(red: 0.910, green: 0.830, blue: 0.690),
        bg2: Color(red: 0.800, green: 0.660, blue: 0.450),
        panelTint: Color.white.opacity(0.30),
        panelHi: Color.white.opacity(0.45),
        sand: Color(red: 0.62, green: 0.45, blue: 0.24),
        dune: Color(red: 0.55, green: 0.38, blue: 0.18),
        terracotta: Color(red: 0.72, green: 0.34, blue: 0.14),
        spice: Color(red: 0.78, green: 0.42, blue: 0.14),
        gold: Color(red: 0.58, green: 0.40, blue: 0.09),
        ibad: Color(red: 0.15, green: 0.34, blue: 0.60),
        text: Color(red: 0.15, green: 0.10, blue: 0.06),
        textDim: Color(red: 0.36, green: 0.27, blue: 0.16),
        border: Color(red: 0.45, green: 0.34, blue: 0.20).opacity(0.55),
        rim: .black,
        good: Color(red: 0.16, green: 0.45, blue: 0.22),
        bad: Color(red: 0.65, green: 0.20, blue: 0.14))

    static let mono = Palette(
        isDark: true,
        bg: Color(white: 0.06),
        bg2: Color(white: 0.12),
        panelTint: Color.white.opacity(0.06),
        panelHi: Color.white.opacity(0.12),
        sand: Color(white: 0.86),
        dune: Color(white: 0.68),
        terracotta: Color(white: 0.80),
        spice: Color(white: 0.94),
        gold: Color(white: 0.88),
        ibad: Color(white: 0.72),
        text: Color(white: 0.96),
        textDim: Color(white: 0.60),
        border: Color(white: 0.28),
        rim: .white,
        good: Color(white: 0.82),
        bad: Color(white: 0.58))

    static func forTheme(_ t: AppTheme) -> Palette {
        t == .hue ? .day : .mono
    }

    /// When the OKLCH theme is active, derive the whole palette from it, so every
    /// static `pal.*` usage (headers, chips, labels, sheens, statuses) follows
    /// the image hue. Falls back to the classic desert palette otherwise.
    static func forTheme(_ t: AppTheme, colorTheme: ColorTheme, active: Bool) -> Palette {
        guard active, colorTheme != .placeholder else { return forTheme(t) }
        let ct = colorTheme
        return Palette(
            isDark: !ct.isLight,
            bg: ct.background,
            bg2: ct.surface,
            panelTint: ct.surfaceTint,
            panelHi: ct.surface,
            sand: ct.ink,
            dune: ct.inkDim,
            terracotta: ct.secondary,
            spice: ct.accent,
            gold: ct.tertiary,
            ibad: ct.tertiary,
            text: ct.ink,
            textDim: ct.inkDim,
            border: ct.border,
            rim: ct.isLight ? .black : .white,   // specular glass edge stays neutral
            good: ct.good,
            bad: ct.bad)
    }
}

/// The single adaptive palette every piece of floating chrome draws from. Ink,
/// dim, accent and tint are all sampled from the artwork behind `region`, so the
/// history rail, the menu rail, its drop-down panels and the pill cards read as
/// one surface that belongs to the photograph currently on the page. This is the
/// design language: colour is *earned from the art*, never a fixed theme colour.
struct ChromePalette {
    let ink, dim, accent, tint, panel: Color
    let isLight: Bool
    @MainActor init(_ engine: Engine, _ region: BgRegion) {
        ink = engine.text(region)
        dim = engine.dim(region)
        accent = engine.accentColor(region)
        tint = engine.tint(region)
        isLight = engine.isLight(region)
        panel = (isLight ? Color.white : Color.black).opacity(engine.scrimOpacity(region))
    }
    /// High-contrast ink for text sitting directly on `panel`.
    var onPanel: Color { isLight ? Color(white: 0.06) : .white }
}

private struct PaletteKey: EnvironmentKey { static let defaultValue = Palette.mono }
extension EnvironmentValues {
    var palette: Palette {
        get { self[PaletteKey.self] }
        set { self[PaletteKey.self] = newValue }
    }
}

/// The one globally-governed text-colour authority. Every adaptive text surface
/// reads its ink from here (provided once at the root from the current artwork),
/// so contrast decisions are made in a single place instead of per view.
struct AppInk {
    var left: Color
    var center: Color
    var right: Color
    /// Ink for the masthead/top band (the wordmark).
    var top: Color

    func callAsFunction(_ region: BgRegion) -> Color {
        switch region {
        case .left: return left
        case .center: return center
        case .right: return right
        }
    }

    /// Fallback used before the root provides the real sampled ink.
    static let neutral = AppInk(left: .primary, center: .primary, right: .primary, top: .primary)
}

private struct AppInkKey: EnvironmentKey { static let defaultValue = AppInk.neutral }
extension EnvironmentValues {
    var ink: AppInk {
        get { self[AppInkKey.self] }
        set { self[AppInkKey.self] = newValue }
    }
}

/// The global artwork palette, provided once at the root. Every UI colour can be
/// resolved through this (`@Environment(\.bgPalette)`) instead of hard-coding.
private struct BgPaletteKey: EnvironmentKey { static let defaultValue = BackgroundPalette.placeholder }
extension EnvironmentValues {
    var bgPalette: BackgroundPalette {
        get { self[BgPaletteKey.self] }
        set { self[BgPaletteKey.self] = newValue }
    }
}

// MARK: - Appearance preference (in-app light/dark toggle)

enum AppTheme: String, CaseIterable, Identifiable {
    case hue, mono            // Hue = colour theory over the art · Noir = contrasty B&W
    static let fallback = AppTheme.mono
    var id: String { rawValue }
    var label: String { self == .mono ? "Noir" : "Hue" }
    var colorScheme: ColorScheme { self == .hue ? .light : .dark }
    var symbol: String { self == .hue ? "paintpalette.fill" : "circle.lefthalf.filled" }
    var next: AppTheme { self == .hue ? .mono : .hue }

    /// Migrates the retired "light" value so existing preferences keep working.
    init?(rawValue: String) {
        switch rawValue {
        case "hue", "light": self = .hue
        case "mono": self = .mono
        default: return nil
        }
    }
}

private struct AppThemeKey: EnvironmentKey { static let defaultValue = AppTheme.mono }
extension EnvironmentValues {
    var appTheme: AppTheme {
        get { self[AppThemeKey.self] }
        set { self[AppThemeKey.self] = newValue }
    }
}
