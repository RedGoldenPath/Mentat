import Foundation
import Observation

/// Owns the live `DesignTokens`, persisted to UserDefaults and mirrored into
/// `DesignTokens.current` so the static design helpers see edits immediately.
@Observable final class DesignStore {
    private static let key = "designTokens"

    var tokens: DesignTokens {
        didSet {
            DesignTokens.current = tokens
            persist()
        }
    }

    init(defaults: UserDefaults = .standard) {
        if let data = defaults.data(forKey: Self.key),
            let decoded = try? JSONDecoder().decode(DesignTokens.self, from: data)
        {
            tokens = decoded
        } else {
            tokens = DesignStore.seeded(from: defaults)
        }
        DesignTokens.current = tokens
    }

    /// First run: carry over the legacy loose `@AppStorage` settings so nothing
    /// is lost when they move into tokens.
    private static func seeded(from d: UserDefaults) -> DesignTokens {
        var t = DesignTokens.default
        if d.object(forKey: "showGrid") != nil { t.inspector.showGrid = d.bool(forKey: "showGrid") }
        if d.object(forKey: "gridLines") != nil {
            t.inspector.showLines = d.bool(forKey: "gridLines")
        }
        if d.object(forKey: "gridLineOpacity") != nil {
            t.inspector.lineOpacity = d.double(forKey: "gridLineOpacity")
        }
        if d.object(forKey: "gridLineBand") != nil {
            t.inspector.lineBand = d.double(forKey: "gridLineBand")
        }
        if d.object(forKey: "gridLineFeather") != nil {
            t.inspector.lineFeather = d.double(forKey: "gridLineFeather")
        }
        if d.object(forKey: "gridNumbers") != nil {
            t.inspector.numbers = d.bool(forKey: "gridNumbers")
        }
        if d.object(forKey: "gridScope") != nil {
            t.inspector.scope = d.string(forKey: "gridScope") ?? "both"
        }
        if d.object(forKey: "headerHeight") != nil {
            t.inspector.headerHeight = d.double(forKey: "headerHeight")
        }
        return t
    }

    func reset() { tokens = .default }

    private func persist() {
        if let data = try? JSONEncoder().encode(tokens) {
            UserDefaults.standard.set(data, forKey: Self.key)
        }
    }
}
