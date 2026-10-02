import SwiftUI

/// A named look. Because the whole colour system resolves from `SurfaceLook`
/// (`ColorTheme.look`), one selection restyles every surface + ink at once —
/// cohesion is structural, not a pile of overrides.
struct DesignPreset: Identifiable, Equatable {
    let look: SurfaceLook

    init(_ look: SurfaceLook) { self.look = look }

    var id: String { look.rawValue }
    var name: String { look.label }
    var blurb: String { look.blurb }
    var symbol: String { look.symbol }

    func apply(to d: inout DesignTokens) { d.look = look }

    static let all: [DesignPreset] = SurfaceLook.allCases.map(DesignPreset.init)

    static func matching(_ d: DesignTokens) -> String? { d.look.rawValue }
}
