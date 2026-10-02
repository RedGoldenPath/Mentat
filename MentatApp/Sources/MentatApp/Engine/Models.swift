import Foundation
import Observation

// MARK: - Wire + chat models

/// A citation returned by the engine: a book and a location within it.
struct Citation: Decodable, Hashable, Identifiable {
    let book: String
    let loc: String
    var id: String { "\(book)·\(loc)" }
}

/// Timing/token telemetry that accompanies an answer.
struct AnswerMeta: Decodable {
    let kind: String?
    let t_thinking: Double?
    let t_content: Double?
    let tokens_in: Int?
    let tokens_out: Int?
    let cost_usd: Double?
    /// Provider prefix-cache telemetry (deepseek/openrouter).
    var cache_hit_tokens: Int? = nil
    var cache_miss_tokens: Int? = nil
    /// Why this model was chosen (routing reason).
    var route_reason: String? = nil
}

/// Non-streaming `/ask` response.
struct AskResponse: Decodable {
    let status: String?
    let answer: String?
    let error: String?
    let citations: [Citation]?
    let ungrounded: Int?
    let model: String?
    let conversation: String?
    let meta: AnswerMeta?
}

/// One event on the `/ask/stream` line protocol.
struct StreamEvent: Decodable {
    let t: String
    let v: String?
    let answer: String?
    let citations: [Citation]?
    let ungrounded: Int?
    let model: String?
    let status: String?
    let conversation: String?
    let meta: AnswerMeta?
}

/// A saved conversation as listed by `/conversations`.
struct Conversation: Decodable, Identifiable {
    let conv: String
    let count: Int
    let last_ts: String
    let summary: String?
    let question: String?
    var id: String { conv }
    var label: String {
        let s = (summary?.isEmpty == false ? summary : question) ?? ""
        return s.isEmpty ? "(untitled)" : s
    }
}

/// An indexed book from the library manifest.
struct LibraryBook: Decodable, Identifiable {
    let id: String
    let title: String
    let series: String?
    let summary: String?
    let concepts: [String]?
}

/// A citation resolved back to its verbatim source window (GET /passage).
struct PassageSource: Decodable, Equatable {
    var book: String?
    var loc: String?
    /// The passage's own sentence(s), shown as the focal quote card.
    var quote: String?
    /// A generous verbatim window from the book, paginated in the reader.
    var text: String?
    var error: String?
    var found: Bool { error == nil && !(text ?? "").isEmpty }
}

/// One block of extracted text shown in the Library's right-hand panel.
struct DocBlock: Identifiable {
    let id = UUID()
    let label: String
    let text: String
}

/// A settings entry from the engine's spec.
struct SettingSpec: Decodable, Identifiable {
    let key: String
    let section: String?
    let help: String?
    var id: String { key }
    /// The only knobs shown in the everyday Settings panel; everything else is
    /// niche and lives behind `/debug`.
    static let primaryKeys: Set<String> = ["model", "voice", "thinking"]
}

/// A file the reader attached to a message (drag-and-drop / paperclip).
struct ChatAttachment: Identifiable, Hashable {
    let id = UUID()
    let name: String
    let path: String
    let bytes: Int
    var label: String {
        bytes > 0
            ? "\(name) · \(ByteCountFormatter.string(fromByteCount: Int64(bytes), countStyle: .file))"
            : name
    }
}

enum ChatRole { case user, assistant, system }

/// One row of the live transcript. A reference type + `@Observable`, so appending
/// tokens to the in-flight answer mutates only *that* row — the transcript array
/// is untouched and the rest of the conversation does not re-render. (With a
/// value type, every token re-evaluated the whole transcript.)
@Observable final class ChatMessage: Identifiable {
    let id = UUID()
    var role: ChatRole
    var text: String
    var reasoning: String
    var citations: [Citation]
    var ungrounded: Int
    var model: String
    var meta: AnswerMeta?
    var streaming: Bool
    var progress: String
    var failed: Bool
    var pendingQuestion: String?
    var attachmentNames: [String]

    init(
        role: ChatRole,
        text: String = "",
        reasoning: String = "",
        citations: [Citation] = [],
        ungrounded: Int = 0,
        model: String = "",
        meta: AnswerMeta? = nil,
        streaming: Bool = false,
        progress: String = "",
        failed: Bool = false,
        pendingQuestion: String? = nil,
        attachmentNames: [String] = []
    ) {
        self.role = role
        self.text = text
        self.reasoning = reasoning
        self.citations = citations
        self.ungrounded = ungrounded
        self.model = model
        self.meta = meta
        self.streaming = streaming
        self.progress = progress
        self.failed = failed
        self.pendingQuestion = pendingQuestion
        self.attachmentNames = attachmentNames
    }
}

/// A one-shot request to turn the clicked answer by `delta` pages. `token`
/// makes repeats distinct so the target view's `onChange` always fires.
struct PageTurn: Equatable {
    let id: UUID
    let delta: Int
    let token: Int
}
