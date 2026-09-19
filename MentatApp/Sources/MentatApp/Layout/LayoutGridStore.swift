import Foundation
import Observation

/// Owns the live `LayoutGrid`, persisted to UserDefaults and kept in sync with
/// the legacy grid `@AppStorage` keys so the existing feather + numeric inspector
/// keep working while the armature becomes the authority.
@Observable final class LayoutGridStore {
    private static let key = "layoutGrid"

    var grid: LayoutGrid {
        didSet { persist() }
    }

    init(defaults: UserDefaults = .standard) {
        if let data = defaults.data(forKey: Self.key),
            let decoded = try? JSONDecoder().decode(LayoutGrid.self, from: data)
        {
            grid = decoded
        } else {
            grid = LayoutGrid(legacyDefaults: defaults)
        }
    }

    // MARK: guides

    func addGuide(_ axis: GuideAxis, at position: CGFloat) {
        guard position.isFinite else { return }
        grid.guides.append(LayoutGuide(axis: axis, position: position))
    }
    func moveGuide(id: UUID, to position: CGFloat) {
        guard position.isFinite, let i = grid.guides.firstIndex(where: { $0.id == id }) else {
            return
        }
        grid.guides[i].position = position
    }
    func removeGuide(id: UUID) { grid.guides.removeAll { $0.id == id } }
    func clearGuides() { grid.guides.removeAll() }

    // MARK: presets

    func apply(_ preset: LayoutGrid.Preset) { grid = preset.grid }

    /// Put the armature back to the built-in default.
    func reset() { grid = .default }

    private func persist() {
        if let data = try? JSONEncoder().encode(grid) {
            UserDefaults.standard.set(data, forKey: Self.key)
        }
        grid.writeLegacyDefaults()
    }
}

extension LayoutGrid {
    /// Build from the legacy grid settings, so an existing install keeps its
    /// tuned feather values on first run.
    init(legacyDefaults d: UserDefaults) {
        self.init()
        if d.object(forKey: "gridCols") != nil { columns = max(1, d.integer(forKey: "gridCols")) }
        if d.object(forKey: "gridGutter") != nil {
            gutter = CGFloat(d.double(forKey: "gridGutter"))
        }
        if d.object(forKey: "gridMargin") != nil {
            margins = Margins(CGFloat(d.double(forKey: "gridMargin")))
        }
        if d.object(forKey: "gridBaseline") != nil {
            baseline = CGFloat(d.double(forKey: "gridBaseline"))
        }
        if d.object(forKey: "gridRows") != nil { rows = max(1, d.integer(forKey: "gridRows")) }
    }

    /// Mirror the armature back into the legacy keys the feather + inspector read.
    func writeLegacyDefaults(_ d: UserDefaults = .standard) {
        d.set(columns, forKey: "gridCols")
        d.set(Double(gutter), forKey: "gridGutter")
        d.set(Double(margins.leading), forKey: "gridMargin")
        d.set(Double(baseline), forKey: "gridBaseline")
        d.set(rows, forKey: "gridRows")
    }
}
