import SwiftUI

/// A fully resolved, contrast-enforced theme. Built from a `SurfaceLook` (and
/// light/dark for the `system` look) — the single colour authority every surface,
/// ink and control reads from. Contrast is a property of the look, not the photo
/// behind it.
struct ColorTheme: Equatable, Sendable {
    var isLight: Bool
    var baseHue: Double
    var ink: Color
    var inkDim: Color
    var accent: Color
    var onAccent: Color
    /// Additional hued roles so multi-hue schemes show up across the chrome.
    var secondary: Color
    var tertiary: Color
    var surface: Color
    /// The tint to pass to a Liquid Glass material ("stained glass"): a low-alpha
    /// tone from the look that colours the material rather than sitting on top.
    var surfaceTint: Color
    /// Vivid tint for Liquid Glass *controls* (accent-derived).
    var accentTint: Color { accent.opacity(0.55) }
    /// Lighter tint for the *Clear* Liquid Glass variant.
    var clearTint: Color { accent.opacity(0.34) }
    var background: Color
    var border: Color
    var good: Color
    var bad: Color

    static let placeholder = ColorTheme(
        isLight: false, baseHue: 0,
        ink: .white, inkDim: Color(white: 0.72),
        accent: Color(white: 0.90), onAccent: .black,
        secondary: Color(white: 0.80), tertiary: Color(white: 0.70),
        surface: Color(white: 0.18), surfaceTint: Color.white.opacity(0.40),
        background: Color(white: 0.12), border: Color(white: 0.30),
        good: Color(white: 0.70), bad: Color(white: 0.60))
}

/// The surface-first look system. Instead of deriving colour from a photograph
/// (which made text legibility a per-pixel guessing game), the app renders on a
/// small, closed set of **surfaces with paired ink** — the Material 3 "on-"
/// role model and Apple's semantic colours. Cohesion is a property of the look,
/// not of the art behind it.
///
/// References: Material 3 colour roles (`onSurface`/`onPrimary`); Apple HIG
/// *Materials* + semantic colours; Radix Colors (guaranteed-contrast steps);
/// Obsidian's CSS-variable theming (`--background-primary`/`--text-normal`).
enum SurfaceLook: String, Codable, CaseIterable, Identifiable, Sendable {
    case system, paper, mono, sand

    var id: String { rawValue }
    var label: String {
        switch self {
        case .system: return "System"
        case .paper: return "Paper"
        case .mono: return "Mono"
        case .sand: return "Sand"
        }
    }
    var blurb: String {
        switch self {
        case .system: return "Neutral, follows macOS"
        case .paper: return "Warm paper, ink text"
        case .mono: return "Dark grayscale"
        case .sand: return "Living amber sand"
        }
    }
    var symbol: String {
        switch self {
        case .system: return "macwindow"
        case .paper: return "doc.plaintext"
        case .mono: return "moon.stars"
        case .sand: return "sun.haze"
        }
    }

    /// Dark/light the look resolves to for a given appearance choice. `system`
    /// follows the user's toggle; `paper` is always light, `mono`/`sand` dark.
    func isDark(appearance: AppTheme) -> Bool {
        switch self {
        case .system: return appearance == .dark
        case .paper: return false
        case .mono, .sand: return true
        }
    }

    /// Tolerant decode: the retired `"noir"` value migrates to `sand` so existing
    /// installs keep their look.
    init?(rawValue: String) {
        switch rawValue {
        case "sand", "noir": self = .sand
        case "system": self = .system
        case "paper": self = .paper
        case "mono": self = .mono
        default: return nil
        }
    }
}

extension ColorTheme {
    /// The single resolver from `(look, isDark)` → theme. Every `colorTheme.*`
    /// consumer (chrome, sidebar, controls) reads these cohesive roles.
    static func look(_ look: SurfaceLook, isDark: Bool) -> ColorTheme {
        switch look {
        case .system: return isDark ? .systemDark : .systemLight
        case .paper: return .paper
        case .mono: return .monoDark
        case .sand: return .sand
        }
    }

    // MARK: System (neutral, Apple-blue accent)

    static let systemLight = ColorTheme(
        isLight: true, baseHue: 0.60,
        ink: Color(white: 0.12), inkDim: Color(white: 0.42),
        accent: Color(red: 0.0, green: 0.478, blue: 1.0), onAccent: .white,
        secondary: Color(white: 0.45), tertiary: Color(white: 0.56),
        surface: Color(white: 0.955), surfaceTint: Color(red: 0.0, green: 0.478, blue: 1.0).opacity(0.10),
        background: Color(white: 0.98), border: Color(white: 0.85),
        good: Color(red: 0.20, green: 0.78, blue: 0.35),
        bad: Color(red: 1.0, green: 0.23, blue: 0.19))

    static let systemDark = ColorTheme(
        isLight: false, baseHue: 0.60,
        ink: Color(white: 0.95), inkDim: Color(white: 0.64),
        accent: Color(red: 0.04, green: 0.52, blue: 1.0), onAccent: .white,
        secondary: Color(white: 0.60), tertiary: Color(white: 0.50),
        surface: Color(white: 0.16), surfaceTint: Color(red: 0.04, green: 0.52, blue: 1.0).opacity(0.20),
        background: Color(white: 0.11), border: Color(white: 0.28),
        good: Color(red: 0.30, green: 0.82, blue: 0.44),
        bad: Color(red: 1.0, green: 0.33, blue: 0.29))

    // MARK: Paper (warm cream, ink text, terracotta accent)

    static let paper = ColorTheme(
        isLight: true, baseHue: 0.08,
        ink: Color(red: 0.13, green: 0.11, blue: 0.08),
        inkDim: Color(red: 0.42, green: 0.37, blue: 0.30),
        accent: Color(red: 0.71, green: 0.36, blue: 0.13), onAccent: .white,
        secondary: Color(red: 0.50, green: 0.42, blue: 0.32),
        tertiary: Color(red: 0.58, green: 0.50, blue: 0.40),
        surface: Color(red: 0.988, green: 0.976, blue: 0.949),
        surfaceTint: Color(red: 0.71, green: 0.36, blue: 0.13).opacity(0.09),
        background: Color(red: 0.965, green: 0.945, blue: 0.902),
        border: Color(red: 0.85, green: 0.81, blue: 0.73),
        good: Color(red: 0.29, green: 0.47, blue: 0.24),
        bad: Color(red: 0.68, green: 0.22, blue: 0.16))

    // MARK: Mono (true dark, grayscale)

    static let monoDark = ColorTheme(
        isLight: false, baseHue: 0,
        ink: Color(white: 0.96), inkDim: Color(white: 0.62),
        accent: Color(white: 0.88), onAccent: .black,
        secondary: Color(white: 0.70), tertiary: Color(white: 0.58),
        surface: Color(white: 0.15), surfaceTint: Color.white.opacity(0.10),
        background: Color(white: 0.09), border: Color(white: 0.30),
        good: Color(white: 0.82), bad: Color(white: 0.58))

    // MARK: Sand (pitch black canvas, warm amber accent)

    static let sand = ColorTheme(
        isLight: false, baseHue: 0.10,
        ink: Color(white: 0.98), inkDim: Color(white: 0.66),
        accent: Color(red: 0.90, green: 0.72, blue: 0.42), onAccent: .black,
        secondary: Color(white: 0.72), tertiary: Color(white: 0.58),
        surface: Color(white: 0.09),
        surfaceTint: Color(red: 0.90, green: 0.72, blue: 0.42).opacity(0.14),
        background: Color(white: 0.03), border: Color(white: 0.22),
        good: Color(red: 0.55, green: 0.78, blue: 0.52),
        bad: Color(red: 0.86, green: 0.45, blue: 0.38))
}
