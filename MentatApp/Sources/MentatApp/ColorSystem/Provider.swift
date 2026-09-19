import SwiftUI

/// The single authority every UI colour resolves through: one contrast-enforced
/// theme derived from the current artwork. Provided once at the root.
private struct ColorThemeKey: EnvironmentKey {
    static let defaultValue = ColorTheme.placeholder
}

extension EnvironmentValues {
    var colorTheme: ColorTheme {
        get { self[ColorThemeKey.self] }
        set { self[ColorThemeKey.self] = newValue }
    }
}
