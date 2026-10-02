import SwiftUI

/// A named-slot system, after DeepSeek Harness (`dsh-client-ui-slots`): four
/// composition kinds, declaration discipline, and reversible registrations.
///
/// - `single`  — at most one occupant (the last registration wins)
/// - `list`    — ordered entries
/// - `keyed`   — dispatch by a key
/// - `chain`   — entries elect themselves (ascending priority; first wins)
@Observable
final class SlotRegistry {
    enum Key: String, CaseIterable {
        case railHeader, railRowActions
        case toolbarLeading, toolbarTrailing
        case messageActions, messageAccessory
        case composerLeading, composerTrailing
        case inspectorTabs, inspectorContent
        case menuItems
        case settingsSections
        case developerPanels
        case statusTrailing
    }

    enum Kind: String, Sendable { case single, list, keyed, chain }

    private struct Entry {
        let id = UUID()
        var priority = 0
        var key: String?
        var elected = true
        let view: () -> AnyView
    }

    private struct Slot {
        var kind: Kind
        var entries: [Entry] = []
        var declared = false
    }

    private var slots: [Key: Slot] = [:]
    /// Registrations that arrived before their slot was declared (dsh throws;
    /// we record them so the Developer scene can surface the lapse).
    private(set) var undeclared: [Key] = []

    // MARK: declaration

    /// Declaring a slot claims it and fixes its kind. Re-declaring with a
    /// different kind is ignored (the first declaration is authoritative).
    func declare(_ key: Key, as kind: Kind = .list) {
        if slots[key] == nil { slots[key] = Slot(kind: kind, declared: true) }
    }

    // MARK: registration

    func register<V: View>(
        _ key: Key,
        kind: Kind? = nil,
        priority: Int = 0,
        id keyValue: String? = nil,
        elected: Bool = true,
        @ViewBuilder _ content: @escaping () -> V
    ) {
        if slots[key] == nil {
            slots[key] = Slot(kind: kind ?? .list)
            undeclared.append(key)
        }
        var slot = slots[key]!
        slot.entries.append(Entry(priority: priority, key: keyValue,
                                  elected: elected, view: { AnyView(content()) }))
        slots[key] = slot
    }

    /// A reversible registration token (dsh: registrations are effects).
    @discardableResult
    func dispose(_ key: Key) -> () -> Void {
        let snapshot = slots[key]
        return { [weak self] in self?.slots[key] = snapshot }
    }

    // MARK: read

    func kind(_ key: Key) -> Kind? { slots[key]?.kind }
    func isEmpty(_ key: Key) -> Bool { (slots[key]?.entries.isEmpty ?? true) }

    func views(_ key: Key) -> [AnyView] {
        guard let slot = slots[key] else { return [] }
        switch slot.kind {
        case .single:
            return slot.entries.suffix(1).map { $0.view() }
        case .list, .keyed:
            return slot.entries.map { $0.view() }
        case .chain:
            return slot.entries
                .filter(\.elected).sorted { $0.priority < $1.priority }
                .prefix(1).map { $0.view() }
        }
    }

    func views(_ key: Key, keyed by: String) -> [AnyView] {
        (slots[key]?.entries ?? []).filter { $0.key == by }.map { $0.view() }
    }
}

private struct SlotRegistryKey: EnvironmentKey {
    nonisolated(unsafe) static let defaultValue = SlotRegistry()
}

extension EnvironmentValues {
    var slots: SlotRegistry {
        get { self[SlotRegistryKey.self] }
        set { self[SlotRegistryKey.self] = newValue }
    }
}

/// Renders everything registered into a slot, in the kind-appropriate order.
struct SlotView: View {
    var key: SlotRegistry.Key
    var keyed: String? = nil
    @Environment(\.slots) private var slots

    var body: some View {
        let list = keyed.map { slots.views(key, keyed: $0) } ?? slots.views(key)
        ForEach(Array(list.enumerated()), id: \.offset) { _, view in view }
    }
}
