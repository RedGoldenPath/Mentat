import Foundation

/// How the accent / secondary / tertiary hues relate to the image's base hue.
/// OKLCH-native (rotations on the colour wheel), plus a `fromImage` option that
/// samples the photo's own dominant clusters.
enum PaletteScheme: String, CaseIterable, Codable, Identifiable, Sendable {
    case primary, monochrome, analogous, secondary, tertiary, complementary, split, triadic,
        fromImage

    var id: String { rawValue }

    var label: String {
        switch self {
        case .primary: return "Primary"
        case .monochrome: return "Monochrome"
        case .analogous: return "Analogous"
        case .secondary: return "Secondary"
        case .tertiary: return "Tertiary"
        case .complementary: return "Complementary"
        case .split: return "Split"
        case .triadic: return "Triadic"
        case .fromImage: return "From image"
        }
    }

    /// Hue rotations (degrees) for the accent / secondary / tertiary roles,
    /// applied to the image's base hue. `primary` and `monochrome` keep one hue
    /// and separate the roles by lightness/chroma instead.
    var accentOffset: Double {
        switch self {
        case .primary, .monochrome, .fromImage: return 0
        case .analogous: return 30
        case .secondary: return 60
        case .tertiary: return 120
        case .complementary: return 180
        case .split: return 150
        case .triadic: return 120
        }
    }
    var secondaryOffset: Double {
        switch self {
        case .primary, .monochrome, .fromImage: return 0
        case .analogous: return -30
        case .secondary: return 60
        case .tertiary: return 120
        case .complementary: return 160
        case .split: return -150
        case .triadic: return 240
        }
    }
    var tertiaryOffset: Double {
        switch self {
        case .primary, .monochrome, .fromImage: return 0
        case .analogous: return 60
        case .secondary: return 120
        case .tertiary: return 240
        case .complementary: return 200
        case .split: return 180
        case .triadic: return 60
        }
    }
}
