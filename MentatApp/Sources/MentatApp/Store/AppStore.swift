import SwiftUI

/// The pure reducer for interface actions: state in, state out, and an `Effect`
/// describing the one side exit. Kept free of I/O so it can be tested exactly.
enum UIReducer {
    struct State: Equatable {
        var sidebarVisible = true
        var appearanceRaw = AppTheme.fallback.rawValue
    }

    enum Effect: Equatable {
        case newConversation
        case inspector, grid, debug
        case none
    }

    static func reduce(_ state: inout State, _ action: UIAction) -> Effect {
        switch action {
        case .toggleSidebar:
            state.sidebarVisible.toggle()
            return .none
        case .cycleAppearance:
            state.appearanceRaw = (AppTheme(rawValue: state.appearanceRaw) ?? .fallback).next.rawValue
            return .none
        case .newConversation:
            return .newConversation
        case .toggleInspector:
            return .inspector
        case .toggleGrid:
            return .grid
        case .toggleDebug:
            return .debug
        }
    }
}

/// The interface's single enclosure and one bus. UI actions flow through `send`;
/// the reducer computes the next interface state and names any effect; the store
/// is the only place those effects run. Data services (`Engine`, `DesignStore`,
/// `InspectorStore`) stay effect providers — the strangler path toward one state.
@Observable
@MainActor
final class AppStore {
    var state: UIReducer.State { didSet { persist() } }
    private(set) var lastEffect: UIReducer.Effect?

    let engine: Engine
    let design: DesignStore
    let inspector: InspectorStore

    init(engine: Engine, design: DesignStore, inspector: InspectorStore) {
        self.engine = engine
        self.design = design
        self.inspector = inspector
        var s = UIReducer.State()
        if let v = UserDefaults.standard.object(forKey: "sidebarVisible") as? Bool { s.sidebarVisible = v }
        if let raw = UserDefaults.standard.string(forKey: "appearance") { s.appearanceRaw = raw }
        self.state = s
    }

    var appearance: AppTheme { AppTheme(rawValue: state.appearanceRaw) ?? .fallback }

    func send(_ action: UIAction) {
        let effect = UIReducer.reduce(&state, action)
        lastEffect = effect
        run(effect)
    }

    private func run(_ effect: UIReducer.Effect) {
        switch effect {
        case .newConversation:
            Task { await engine.newConversation() }
        case .inspector:
            withAnimation(Anim.snappy) { inspector.toggle() }
        case .grid:
            design.tokens.inspector.showGrid.toggle()
        case .debug:
            withAnimation(Anim.snappy) { engine.debugMode.toggle() }
        case .none:
            break
        }
    }

    private func persist() {
        UserDefaults.standard.set(state.sidebarVisible, forKey: "sidebarVisible")
        UserDefaults.standard.set(state.appearanceRaw, forKey: "appearance")
    }
}
