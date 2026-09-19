import Foundation

// MARK: - Command catalog

struct CommandItem: Identifiable {
    let cmd: String
    let help: String
    nonisolated var id: String { cmd }

    /// Everyday commands, always offered.
    static let primary: [CommandItem] = [
        .init(cmd: "help", help: "list every command"),
        .init(cmd: "clear", help: "start a new conversation"),
        .init(cmd: "status", help: "what is indexed / pending"),
        .init(cmd: "settings", help: "open settings"),
    ]

    /// Niche mechanics, surfaced only once `/debug` unlocks them.
    static let debug: [CommandItem] = [
        .init(cmd: "health", help: "run the subsystem health check"),
        .init(cmd: "verify", help: "run the verification suite"),
        .init(cmd: "index", help: "index new or changed files"),
        .init(cmd: "search", help: "exact full-text search"),
        .init(cmd: "graph", help: "entity co-occurrence"),
        .init(cmd: "freq", help: "exact occurrence count"),
        .init(cmd: "inventory", help: "per-work chunks/chapters/words"),
        .init(cmd: "stats", help: "research diary: questions, spend"),
        .init(cmd: "served", help: "which model served the last answer"),
        .init(cmd: "history", help: "recent questions"),
        .init(cmd: "remember", help: "save a fact to permanent memory"),
        .init(cmd: "heal", help: "self-repair"),
        .init(cmd: "offline", help: "local-only mode (on/off)"),
        .init(cmd: "model", help: "show/set the answer model"),
        .init(cmd: "voice", help: "show/set the writing voice"),
        .init(cmd: "lens", help: "show/set the persistent lens"),
        .init(cmd: "grid", help: "toggle the layout grid"),
    ]

    static func all(debug: Bool) -> [CommandItem] { primary + (debug ? self.debug : []) }
}
