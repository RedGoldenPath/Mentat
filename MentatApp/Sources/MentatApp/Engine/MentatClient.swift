import Foundation

// MARK: - Route payloads

struct ConversationsResponse: Decodable { let conversations: [Conversation] }
struct ConversationResponse: Decodable { let turns: [Turn] }
struct BooksResponse: Decodable { let books: [LibraryBook] }

/// One saved turn of a conversation.
struct Turn: Decodable {
    let question: String?
    let answer: String?
    let model: String?
}

/// Extracted excerpt of an indexed book.
struct BookExcerpt: Decodable {
    let concept: String?
    let excerpt: String?
    let text: String?
}

struct BookDetail: Decodable {
    let summary: String?
    let concepts: [String]?
    let excerpts: [BookExcerpt]?
}

/// Result of a `/command` (an engine slash-command).
struct CommandResult: Decodable {
    let ok: Bool?
    let text: String?
}

/// Response of `/conversation/new`: the id of the freshly minted thread.
struct NewConversationResponse: Decodable { let id: String? }

// MARK: - Client

/// Typed HTTP client for the local engine. One place owns the routes, methods,
/// headers, and decoding, so `Engine` never hand-builds a request.
///
/// Set `isFixture` (via `MENTAT_FIXTURE=1`) to serve canned data and a canned
/// stream instead of touching the engine — so UI smoke tests are free and
/// instant, with no model calls.
struct MentatClient: Sendable {
    var baseURL: URL
    var session: URLSession = .shared
    var isFixture: Bool = false

    static let `default` = MentatClient(baseURL: EngineProcess.baseURL)
    static let fixture = MentatClient(baseURL: EngineProcess.baseURL, isFixture: true)

    /// The client the app should use: fixtures when `MENTAT_FIXTURE=1`.
    static func makeDefault() -> MentatClient {
        ProcessInfo.processInfo.environment["MENTAT_FIXTURE"] == "1" ? .fixture : .default
    }

    private func url(_ path: String, query: [URLQueryItem] = []) -> URL {
        var components = URLComponents(
            url: baseURL.appendingPathComponent(path),
            resolvingAgainstBaseURL: false)!
        if !query.isEmpty { components.queryItems = query }
        return components.url ?? baseURL
    }

    private func get<T: Decodable>(
        _ path: String, query: [URLQueryItem] = [],
        as type: T.Type
    ) async throws -> T {
        let (data, _) = try await session.data(from: url(path, query: query))
        return try JSONDecoder().decode(T.self, from: data)
    }

    @discardableResult
    private func post<T: Decodable>(_ path: String, body: [String: Any]) async throws -> T {
        var req = URLRequest(url: url(path))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, _) = try await session.data(for: req)
        return try JSONDecoder().decode(T.self, from: data)
    }

    private func postVoid(_ path: String, body: [String: Any] = [:]) async {
        var req = URLRequest(url: url(path))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(withJSONObject: body)
        _ = try? await session.data(for: req)
    }

    // MARK: conversations

    func conversations() async throws -> [Conversation] {
        if isFixture { return Fixtures.conversations }
        return try await get("conversations", as: ConversationsResponse.self).conversations
    }

    func conversation(id: String) async throws -> [Turn] {
        if isFixture { return Fixtures.turns }
        return try await get(
            "conversation", query: [URLQueryItem(name: "id", value: id)],
            as: ConversationResponse.self
        ).turns
    }

    func openConversation(id: String) async {
        if !isFixture { await postVoid("conversation/open", body: ["id": id]) }
    }
    func newConversation() async -> String? {
        if isFixture { return nil }
        let r: NewConversationResponse? = try? await post("conversation/new", body: [:])
        return r?.id
    }
    func renameConversation(id: String, title: String) async {
        if !isFixture { await postVoid("conversation/rename", body: ["id": id, "title": title]) }
    }
    func truncateConversation(id: String, keep: Int) async {
        if !isFixture { await postVoid("conversation/truncate", body: ["conversation": id, "keep": keep]) }
    }
    func deleteTurn(id: String, index: Int) async {
        if !isFixture { await postVoid("conversation/delete_turn", body: ["conversation": id, "index": index]) }
    }
    func deleteConversation(id: String) async {
        if !isFixture { await postVoid("conversation/delete", body: ["id": id]) }
    }

    // MARK: library

    func books() async throws -> [LibraryBook] {
        if isFixture { return Fixtures.books }
        return try await get("books", as: BooksResponse.self).books
    }

    func book(id: String) async throws -> BookDetail {
        if isFixture { return Fixtures.book }
        return try await get(
            "book", query: [URLQueryItem(name: "id", value: id)], as: BookDetail.self)
    }

    // MARK: ask / command

    func ask(question: String, conversation: String = "",
             attachments: [ChatAttachment] = []) async throws -> AskResponse {
        if isFixture { return Fixtures.ask }
        return try await post("ask", body: [
            "question": question, "conversation": conversation,
            "attachments": attachments.map { ["path": $0.path, "name": $0.name] },
        ])
    }

    /// Resolve a citation back to its verbatim source window for the reader.
    func passage(book: String, loc: String, hint: String) async throws -> PassageSource {
        if isFixture { return Fixtures.passage }
        return try await get(
            "passage",
            query: [
                URLQueryItem(name: "book", value: book),
                URLQueryItem(name: "loc", value: loc),
                URLQueryItem(name: "hint", value: String(hint.prefix(2000))),
            ], as: PassageSource.self)
    }

    func command(_ cmd: String, _ arg: String) async throws -> CommandResult {
        if isFixture { return Fixtures.command }
        return try await post("command", body: ["cmd": cmd, "arg": arg])
    }

    // MARK: settings (values are dynamic, so the payload stays raw JSON)

    func settingsData() async -> Data? {
        if isFixture { return Fixtures.settingsJSON }
        return try? await session.data(from: url("settings")).0
    }

    func setSetting(body: Data) async {
        guard !isFixture else { return }
        var req = URLRequest(url: url("settings"))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = body
        _ = try? await session.data(for: req)
    }

    // MARK: streaming

    /// The `/ask/stream` line protocol as a typed event stream. Cancelling the
    /// consumer cancels the underlying request.
    func streamEvents(question: String, conversation: String = "",
                      attachments: [ChatAttachment] = []) -> AsyncThrowingStream<StreamEvent, Error> {
        if isFixture { return Fixtures.stream(question: question) }
        return AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    var req = URLRequest(url: url("ask/stream"))
                    req.httpMethod = "POST"
                    req.setValue("application/json", forHTTPHeaderField: "Content-Type")
                    req.httpBody = try JSONSerialization.data(
                        withJSONObject: [
                            "question": question, "conversation": conversation,
                            "attachments": attachments.map { ["path": $0.path, "name": $0.name] },
                        ])
                    req.timeoutInterval = 1800
                    let (bytes, response) = try await session.bytes(for: req)
                    guard (response as? HTTPURLResponse)?.statusCode == 200 else {
                        continuation.finish()
                        return
                    }
                    let decoder = JSONDecoder()
                    for try await line in bytes.lines {
                        if Task.isCancelled { break }
                        guard !line.isEmpty, let data = line.data(using: .utf8) else { continue }
                        if let ev = try? decoder.decode(StreamEvent.self, from: data) {
                            continuation.yield(ev)
                        }
                    }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }
}

// MARK: - Fixtures

/// Canned engine responses for `MENTAT_FIXTURE=1`. Keeps UI work testable
/// without a running engine and without spending a cent on model calls.
enum Fixtures {
    static let conversations: [Conversation] = [
        Conversation(
            conv: "fixture-1", count: 4, last_ts: "2026-01-01T00:00:00Z",
            summary: "Fixture conversation about dunes",
            question: "What did Paul see in the desert?"),
        Conversation(
            conv: "fixture-2", count: 2, last_ts: "2025-12-31T00:00:00Z",
            summary: "Fixture conversation about fear",
            question: "What is the Litany against Fear?"),
    ]

    static let turns: [Turn] = [
        Turn(
            question: "What did Paul see in the desert?",
            answer: "He saw the deep desert and the Fremen. (Dune · Chapter 3)",
            model: "fixture"),
        Turn(
            question: "What is the Litany against Fear?",
            answer: "I must not fear. Fear is the mind-killer. (Dune · Chapter 1)",
            model: "fixture"),
    ]

    static let books: [LibraryBook] = [
        LibraryBook(
            id: "dune", title: "Dune", series: "Dune",
            summary: "Fixture book.", concepts: ["fear", "spice"]),
        LibraryBook(
            id: "messiah", title: "Dune Messiah", series: "Dune",
            summary: "Fixture book.", concepts: ["prophecy"]),
    ]

    static let book = BookDetail(
        summary: "A fixture summary for smoke testing the Library shelf.",
        concepts: ["fear", "spice", "Fremen"],
        excerpts: [
            BookExcerpt(
                concept: "fear",
                excerpt: "I must not fear. Fear is the mind-killer.",
                text: nil)
        ]
    )

    static let ask = AskResponse(
        status: "ok",
        answer: "A fixture answer. (Dune · Chapter 1)",
        error: nil,
        citations: [Citation(book: "Dune", loc: "Chapter 1")],
        ungrounded: 0,
        model: "fixture",
        conversation: nil,
        meta: AnswerMeta(
            kind: "quotes", t_thinking: 0.1,
            t_content: 0.2, tokens_in: 10,
            tokens_out: 20, cost_usd: 0))

    static let command = CommandResult(ok: true, text: "fixture command output")

    static let passage = PassageSource(
        book: "Dune",
        loc: "Chapter 1",
        quote: "A beginning is the time for taking the most delicate care.",
        text: """
            A beginning is the time for taking the most delicate care that the \
            balances are correct.

            To attempt an understanding of Muad'Dib without understanding his \
            mortal enemies is to attempt to understand a famous forest without \
            understanding its wolves.
            """,
        error: nil)

    static let settingsJSON: Data? = try? JSONSerialization.data(
        withJSONObject: [
            "spec": [
                ["key": "model", "section": "Everyday", "help": "Fixture model."],
                ["key": "voice", "section": "Everyday", "help": "Fixture voice."],
                ["key": "thinking", "section": "Everyday", "help": "Fixture thinking toggle."],
            ],
            "values": ["model": "fixture", "voice": "default", "thinking": true],
            "options": ["model": ["fixture", "deepseek-flash"], "voice": ["default"]],
        ] as [String: Any])

    /// A short canned stream: streams word-by-word, then a `done` event.
    static func stream(question: String) -> AsyncThrowingStream<StreamEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                let answer =
                    "This is a fixture answer streamed locally, so smoke tests cost nothing. (Dune · Chapter 1)"
                for piece in answer.split(separator: " ") {
                    if Task.isCancelled {
                        continuation.finish()
                        return
                    }
                    continuation.yield(
                        StreamEvent(
                            t: "chunk", v: "\(piece) ", answer: nil,
                            citations: nil, ungrounded: nil, model: nil,
                            status: nil, conversation: nil, meta: nil))
                    try? await Task.sleep(nanoseconds: 12_000_000)
                }
                continuation.yield(
                    StreamEvent(
                        t: "done", v: nil, answer: answer,
                        citations: [Citation(book: "Dune", loc: "Chapter 1")],
                        ungrounded: 0, model: "fixture", status: "ok",
                        conversation: nil,
                        meta: AnswerMeta(
                            kind: "quotes", t_thinking: 0.1,
                            t_content: 0.2, tokens_in: 10,
                            tokens_out: 20, cost_usd: 0)))
                continuation.finish()
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }
}
