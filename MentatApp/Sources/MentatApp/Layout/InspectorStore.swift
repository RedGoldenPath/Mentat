import SwiftUI

/// The right-hand Inspector's tabs (artifacts · citations · source · files ·
/// context). Artifacts are not wired yet, so the visible four are the ones with
/// live data.
enum InspectorTab: String, CaseIterable, Identifiable, Sendable {
    case artifacts, citations, source, files, context

    var id: String { rawValue }
    var title: String {
        switch self {
        case .artifacts: return "Artifacts"
        case .citations: return "Citations"
        case .source: return "Source"
        case .files: return "Files"
        case .context: return "Context"
        }
    }
    var symbol: String {
        switch self {
        case .artifacts: return "curlybraces"
        case .citations: return "quote.opening"
        case .source: return "text.book.closed"
        case .files: return "paperclip"
        case .context: return "gauge.with.dots.needle.33percent"
        }
    }
}

/// Observable, persisted state for the Inspector pane. Part of the layout layer
/// (not the engine), so the shell can be rearranged without touching the brain.
@MainActor
@Observable
final class InspectorStore {
    var visible: Bool { didSet { UserDefaults.standard.set(visible, forKey: "inspectorVisible") } }
    var tab: InspectorTab { didSet { UserDefaults.standard.set(tab.rawValue, forKey: "inspectorTab") } }
    var width: CGFloat { didSet { UserDefaults.standard.set(Double(width), forKey: "inspectorWidth") } }

    /// The answer the Inspector is pinned to. `nil` means "follow the newest
    /// answer" — so the pane is always populated without an explicit pick.
    private(set) var focusedAnswerID: UUID?

    init() {
        let d = UserDefaults.standard
        visible = d.bool(forKey: "inspectorVisible")
        tab = InspectorTab(rawValue: d.string(forKey: "inspectorTab") ?? "") ?? .citations
        let w = d.double(forKey: "inspectorWidth")
        width = w >= 280 ? CGFloat(w) : 340
    }

    func toggle() { visible.toggle() }

    /// Pin the Inspector to an answer (clicking an answer) and reveal the pane.
    func focus(_ answerID: UUID) {
        focusedAnswerID = answerID
        visible = true
    }

    /// Drop the pin so the Inspector follows the newest answer again.
    func clearFocus() { focusedAnswerID = nil }

    /// The answer the Inspector should show: the pinned one if it still exists
    /// and is an answer, otherwise the **most current** answer. Pure, so it can
    /// be tested without the view tree.
    static func focusedAnswer(in messages: [ChatMessage], focused: UUID?) -> ChatMessage? {
        if let focused,
           let hit = messages.first(where: { $0.id == focused }), hit.role == .assistant {
            return hit
        }
        return messages.last { $0.role == .assistant }
    }
}
