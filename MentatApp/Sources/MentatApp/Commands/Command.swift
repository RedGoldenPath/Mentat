import SwiftUI

/// A UI-side action (as opposed to a server slash command). The shell resolves
/// these through the `\.runUIAction` environment closure, so the registry stays
/// free of engine/view references.
enum UIAction: String, Sendable {
    case newConversation
    case toggleInspector
    case toggleSidebar
    case cycleAppearance
    case toggleGrid
    case toggleDebug
}

/// One command definition, shared by every surface: the `/` menu, the ⌘K palette,
/// the debug tool rail, and the menu bar. Add a command here and it appears
/// everywhere.
struct Command: Identifiable {
    enum Kind {
        case slash(String)
        case ui(UIAction)
    }

    enum Section: String, CaseIterable, Identifiable {
        case conversation, knowledge, view, debug
        var id: String { rawValue }
        var title: String {
            switch self {
            case .conversation: return "Conversation"
            case .knowledge: return "Knowledge"
            case .view: return "View"
            case .debug: return "Debug"
            }
        }
    }

    let id: String
    let title: String
    let help: String
    let systemImage: String
    let kind: Kind
    let section: Section
    var shortcut: String? = nil
    var debugOnly: Bool = false

    var slash: String? {
        if case let .slash(s) = kind { return s } else { return nil }
    }
    var isSlash: Bool { slash != nil }
}

/// The single catalogue.
enum CommandRegistry {
    static func all(debug: Bool) -> [Command] {
        debug ? everything : everything.filter { !$0.debugOnly }
    }

    static let everything: [Command] = [
        // Conversation
        cmd("new", "New conversation", "start a fresh thread",
            "square.and.pencil", .ui(.newConversation), .conversation, "⌘N"),
        cmd("clear", "Clear", "start a new conversation",
            "trash", .slash("clear"), .conversation),
        cmd("help", "Help", "list every command",
            "questionmark.circle", .slash("help"), .conversation),
        // Knowledge
        cmd("status", "Status", "what is indexed / pending",
            "info.circle", .slash("status"), .knowledge),
        cmd("search", "Search", "exact full-text search",
            "magnifyingglass", .slash("search"), .knowledge),
        cmd("index", "Index", "index new or changed files",
            "square.stack.3d.up", .slash("index"), .knowledge, nil, true),
        cmd("graph", "Graph", "entity co-occurrence",
            "point.3.connected.trianglepath.dotted", .slash("graph"), .knowledge, nil, true),
        cmd("freq", "Frequency", "exact occurrence count",
            "number", .slash("freq"), .knowledge, nil, true),
        cmd("inventory", "Inventory", "chunks / chapters / words per work",
            "list.bullet.rectangle", .slash("inventory"), .knowledge, nil, true),
        cmd("stats", "Stats", "research diary: questions, spend",
            "chart.bar", .slash("stats"), .knowledge, nil, true),
        cmd("remember", "Remember", "save a fact to permanent memory",
            "brain", .slash("remember"), .knowledge, nil, true),
        // View
        cmd("settings", "Settings", "open settings",
            "slider.horizontal.3", .slash("settings"), .view),
        cmd("inspector", "Inspector", "toggle the right-hand inspector",
            "wrench.and.screwdriver", .ui(.toggleInspector), .view, "⌘I"),
        cmd("scene", "Render scene", "render a JSON scene as UI",
            "chart.xyaxis.line", .slash("scene"), .view),
        cmd("chart", "Chart", "quick generated chart",
            "chart.bar.fill", .slash("chart"), .view),
        cmd("history", "History rail", "show or hide the history rail",
            "sidebar.left", .ui(.toggleSidebar), .view),
        cmd("appearance", "Appearance", "switch light / dark",
            "circle.lefthalf.filled", .ui(.cycleAppearance), .view),
        cmd("grid", "Layout grid", "toggle the armature overlay",
            "grid", .ui(.toggleGrid), .view, nil, true),
        // Debug
        cmd("debug", "Debug panel", "reveal the debug panel",
            "ladybug", .ui(.toggleDebug), .debug, "⇧⌘D", true),
        cmd("health", "Health", "run the subsystem health check",
            "heart.text.square", .slash("health"), .debug, nil, true),
        cmd("verify", "Verify", "run the verification suite",
            "checkmark.seal", .slash("verify"), .debug, nil, true),
        cmd("served", "Served", "which model served the last answer",
            "cpu", .slash("served"), .debug, nil, true),
        cmd("heal", "Heal", "self-repair",
            "bandage", .slash("heal"), .debug, nil, true),
    ]

    private static func cmd(
        _ id: String, _ title: String, _ help: String, _ symbol: String,
        _ kind: Command.Kind, _ section: Command.Section,
        _ shortcut: String? = nil, _ debugOnly: Bool = false
    ) -> Command {
        Command(id: id, title: title, help: help, systemImage: symbol,
                kind: kind, section: section, shortcut: shortcut, debugOnly: debugOnly)
    }
}

// MARK: - UI action environment

private struct RunUIActionKey: EnvironmentKey {
    nonisolated(unsafe) static let defaultValue: (UIAction) -> Void = { _ in }
}

extension EnvironmentValues {
    var runUIAction: (UIAction) -> Void {
        get { self[RunUIActionKey.self] }
        set { self[RunUIActionKey.self] = newValue }
    }
}
