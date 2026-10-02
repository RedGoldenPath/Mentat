import AppKit
import CoreImage
import CoreText
import Foundation
import Observation
import SwiftUI

// The app's engine facade: state, the live transcript, colour/theme resolution,
// and the typed routes onto the Python brain (via MentatClient/EngineProcess).
// Split out of the old monolith.

@MainActor @Observable final class Engine {
    static let shared = Engine()

    /// Version history: a stamp of the running build — when the executable was
    /// last rebuilt plus the source revision. Surfaced in the UI so a past chat
    /// can be dated against the code that produced it (don't re-report errors
    /// that predate the current build).
    let buildStamp: String = Engine.computeBuildStamp()
    /// When this app instance launched — the "as of" time for anything above.
    let launchedAt: Date = Date()

    private static func computeBuildStamp() -> String {
        var parts: [String] = []
        if let exe = Bundle.main.executableURL,
            let attrs = try? FileManager.default.attributesOfItem(atPath: exe.path),
            let date = attrs[.modificationDate] as? Date
        {
            let df = DateFormatter()
            df.dateFormat = "MMM d HH:mm"
            parts.append(df.string(from: date))
        }
        let repo = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Everything/mentat/app")
        if let hash = gitShortHash(repo) { parts.append(hash) }
        return parts.isEmpty ? "dev" : parts.joined(separator: " · ")
    }

    private static func gitShortHash(_ repo: URL) -> String? {
        let head = repo.appendingPathComponent(".git/HEAD")
        guard
            let s = try? String(contentsOf: head, encoding: .utf8)
                .trimmingCharacters(in: .whitespacesAndNewlines)
        else { return nil }
        if s.hasPrefix("ref: ") {
            let ref = String(s.dropFirst(5))
            if let h = try? String(
                contentsOf: repo.appendingPathComponent(".git/\(ref)"),
                encoding: .utf8)
            {
                return String(h.trimmingCharacters(in: .whitespacesAndNewlines).prefix(7))
            }
        }
        return String(s.prefix(7))
    }

    var messages: [ChatMessage] = []
    var busy = false
    /// Files staged in the composer (drag-and-drop / paperclip), sent with the next message.
    var pendingAttachments: [ChatAttachment] = []
    /// Inline message editor (ChatGPT-style): the message being edited + its draft.
    var editingID: UUID?
    var editingText: String = ""
    var online = false
    var status = "starting…"
    var model = ""
    var conversations: [Conversation] = []
    /// Indexed books for the Library shelf.
    var libraryBooks: [LibraryBook] = []
    /// Extracted content of the item picked in Library mode (kept apart from
    /// the live chat transcript).
    var libraryDoc: [DocBlock] = []
    var libraryDocId: String = ""
    /// The active conversation thread. Persisted so quitting/reopening the app
    /// continues the same thread (OpenAI Conversations-object semantics).
    var currentConv: String = UserDefaults.standard.string(forKey: "currentConversation") ?? "" {
        didSet { UserDefaults.standard.set(currentConv, forKey: "currentConversation") }
    }
    /// A message the transcript should bring to the centre of the viewport
    /// (set when a reader pages through an answer, so the page transition can't
    /// drift it out of view). Cleared once honoured.
    var centerRequest: UUID?
    /// The message the reader last clicked. While it is set, the left/right
    /// arrow keys turn that answer's pages instead of scrolling.
    var selectedMessage: UUID?
    /// How many pages each answer currently renders, so the arrow keys only act
    /// when there is somewhere to turn to.
    var pageCounts: [UUID: Int] = [:]
    /// One-shot page-turn request consumed by the matching `PagedText`.
    var pageTurn: PageTurn?
    /// The source reader: a citation resolved to its verbatim passage. Non-nil
    /// while the reader screen is open.
    var readerSource: PassageSource?
    var readerLoading = false
    var readerFailed = false
    var settingsSpec: [SettingSpec] = []
    var settingsValues: [String: Any] = [:]
    var settingsOptions: [String: [String]] = [:]
    /// The surface-first look. Colour is resolved from this (and light/dark), not
    /// sampled from a photo — the single colour authority for content + chrome.
    var surfaceLook: SurfaceLook = .sand { didSet { rebuildLookTheme() } }
    /// Semantic text colours (quote/heading/link/citation/number) for the look.
    private(set) var textInk: TextInk = TextInk.look(.sand, isDark: true)
    /// The resolved theme every surface + ink role reads from.
    var colorTheme: ColorTheme = .placeholder
    /// Tinted (colour-forward) or clear (clarity-forward) Liquid Glass.
    var glassStyle: GlassStyle =
        GlassStyle(rawValue: UserDefaults.standard.string(forKey: "glassStyle") ?? "") ?? .tinted
    var contentSize: CGSize = .zero
    /// The window's top safe-area inset (the titlebar / traffic-light band).
    /// The window uses `.hiddenTitleBar`, so the grid must start below this or
    /// the masthead clips into the titlebar (Apple HIG *Layout — safe areas*).
    var topInset: CGFloat = 0
    /// Size of the whole window (RootView), so overlays can show how the page
    /// layer sits inside it when the sidebar is open.
    var windowSize: CGSize = .zero
    /// Hidden power-user panel, revealed by typing `/debug`. Session-only, so
    /// the niche mechanics are never in the way unless asked for.
    var debugMode = UserDefaults.standard.bool(forKey: "debugMode") {
        didSet { UserDefaults.standard.set(debugMode, forKey: "debugMode") }
    }

    func isLight(_ r: BgRegion) -> Bool { colorTheme.isLight }
    /// The look's stained-glass surface tint, by role.
    func tint(_ r: BgRegion) -> Color { colorTheme.surfaceTint }

    /// Semantic text palette. The look owns ink, so every region resolves to the
    /// same roles — content sits on a solid surface, never on a photo.
    func textColors(_ r: BgRegion) -> (primary: Color, secondary: Color) {
        (colorTheme.ink, colorTheme.inkDim)
    }

    /// One ink for a region (the look's ink). Region-adaptive sampling is retired
    /// — the seam stays so callers have a single place to resolve ink.
    func adaptiveInk(_ region: BgRegion = .center) -> Color { colorTheme.ink }

    /// UI accent: the look's accent. One focal colour, by role.
    func accentColor(_ r: BgRegion = .left) -> Color { colorTheme.accent }

    func text(_ r: BgRegion) -> Color { textColors(r).primary }
    func dim(_ r: BgRegion) -> Color { textColors(r).secondary }

    // MARK: wordmark ink

    /// One consistent ink for the whole wordmark, resolved from the look so the
    /// word can never come out patchwork.
    func titleInk() -> Color { colorTheme.ink }

    /// Comfortable reading measure: the width of `chars` average characters
    /// (books aim for ~45–75 characters per line).
    func measureWidth(chars: Int = 66, fontSize: CGFloat = 13) -> CGFloat {
        let sample = "abcdefghijklmnopqrstuvwxyz "
        let w =
            (sample as NSString).size(
                withAttributes: [.font: NSFont.systemFont(ofSize: fontSize)]).width
            / CGFloat(sample.count)
        return CGFloat(chars) * w
    }

    /// Width the text actually needs when wrapped at `maxWidth` — lets a bubble
    /// hug its content instead of stretching across the frame.
    func naturalWidth(_ text: String, maxWidth: CGFloat, fontSize: CGFloat = 13) -> CGFloat {
        guard !text.isEmpty else { return 0 }
        let rect = (text as NSString).boundingRect(
            with: CGSize(width: maxWidth, height: .greatestFiniteMagnitude),
            options: [.usesLineFragmentOrigin, .usesFontLeading],
            attributes: [.font: NSFont.systemFont(ofSize: fontSize)])
        return min(maxWidth, ceil(rect.width))
    }

    /// Stable legibility backing: strongest where the region is mid-toned
    /// (worst contrast for text). Region-based, so the glass never wavers.
    func scrimOpacity(_ r: BgRegion) -> Double {
        // Stained glass: one consistent plate from the theme, so the material
        // reads as a single surface rather than varying per photo region.
        colorTheme.isLight ? 0.42 : 0.58
    }

    private let engineProcess = EngineProcess.default()
    private let client = MentatClient.makeDefault()
    private var startTask: Task<Void, Never>?
    private var askTask: Task<Void, Never>?

    /// Bring the app-owned engine up, de-duplicating concurrent callers.
    func ensureEngine() async {
        if client.isFixture {
            apply(EngineHealth(online: true, model: "fixture"))
            return
        }
        if let existing = startTask {
            await existing.value
            return
        }
        let task = Task { await self.launchEngine() }
        startTask = task
        await task.value
        startTask = nil
    }

    private func launchEngine() async {
        apply(await engineProcess.ensureRunning())
    }

    func checkHealth() async {
        if client.isFixture {
            apply(EngineHealth(online: true, model: "fixture"))
            return
        }
        apply(await engineProcess.health())
    }

    private func apply(_ h: EngineHealth) {
        online = h.online
        model = h.model
        status = h.online ? "engine ready" : "engine offline — run MentatApp/run.sh"
    }

    func send(_ raw: String) {
        let q = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !q.isEmpty else { return }
        if q.hasPrefix("/") {
            runSlash(q)
            return
        }
        let atts = pendingAttachments
        pendingAttachments = []
        askTask = Task { await ask(q, attachments: atts) }
    }

    // MARK: attachments (drag-and-drop / paperclip)

    func addAttachment(_ url: URL) {
        guard pendingAttachments.count < 5 else { return }
        if pendingAttachments.contains(where: { $0.path == url.path }) { return }
        let attrs = try? FileManager.default.attributesOfItem(atPath: url.path)
        let size = (attrs?[.size] as? NSNumber)?.intValue ?? 0
        pendingAttachments.append(
            ChatAttachment(name: url.lastPathComponent, path: url.path, bytes: size))
    }

    func removeAttachment(_ id: UUID) {
        pendingAttachments.removeAll { $0.id == id }
    }

    func clearAttachments() { pendingAttachments.removeAll() }

    func ask(_ raw: String) async { await ask(raw, attachments: []) }

    func ask(_ raw: String, attachments: [ChatAttachment]) async {
        let q = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !q.isEmpty, !busy else { return }
        busy = true
        messages.append(ChatMessage(role: .user, text: q,
                                    attachmentNames: attachments.map { $0.name }))
        messages.append(
            ChatMessage(
                role: .assistant, streaming: true, progress: "thinking…", pendingQuestion: q))
        let idx = messages.count - 1
        // Pin the answer to *this* message id: if the transcript is reset or
        // switched mid-stream, a stale index can point at a brand-new message
        // and the old answer would bleed into the new conversation.
        let mid = messages[idx].id
        defer {
            busy = false
            if idx < messages.count, messages[idx].id == mid { messages[idx].streaming = false }
        }
        let received = await stream(q, at: idx, id: mid, attachments: attachments)
        if Task.isCancelled {
            if idx < messages.count, messages[idx].id == mid, messages[idx].text.isEmpty {
                messages[idx].text = "_[stopped]_"
            }
            return
        }
        if !received { await askOnce(q, at: idx, id: mid, attachments: attachments) }
    }

    func stop() {
        askTask?.cancel()
        // mark the *actual* streaming message (not just the last one — a system
        // row or a new turn could have landed after it)
        if let i = messages.lastIndex(where: { $0.streaming }) {
            if messages[i].text.isEmpty { messages[i].text = "_[stopped]_" }
            messages[i].streaming = false
        }
        busy = false
    }

    /// Ask the transcript to centre a message in the viewport, and make it the
    /// one the arrow keys page through.
    func center(_ id: UUID) {
        selectedMessage = id
        centerRequest = id
    }

    /// Remember how many pages an answer lays out to (reported by `PagedText`).
    func setPageCount(_ id: UUID, _ n: Int) {
        if pageCounts[id] != n { pageCounts[id] = n }
    }

    // MARK: source reader

    @ObservationIgnored private var readerTask: Task<Void, Never>?

    /// Open the reader at the passage behind a citation. `hint` is the answer
    /// text, used by the engine to disambiguate same-chapter passages via the
    /// words the answer actually quoted.
    func openSource(_ c: Citation, hint: String) {
        readerLoading = true
        readerFailed = false
        readerSource = nil
        readerTask?.cancel()
        readerTask = Task { [weak self] in
            guard let self else { return }
            let result = try? await self.client.passage(
                book: c.book, loc: c.loc, hint: hint)
            guard !Task.isCancelled else { return }
            self.readerLoading = false
            if let result, result.found {
                self.readerSource = result
            } else {
                self.readerFailed = true
            }
        }
    }

    func closeSource() {
        readerTask?.cancel()
        readerLoading = false
        readerFailed = false
        readerSource = nil
    }

    var sourceReaderOpen: Bool { readerSource != nil || readerLoading || readerFailed }

    /// The clicked answer can actually be paged — so arrow keys should page it
    /// rather than scroll the transcript.
    var selectedCanTurn: Bool {
        guard let id = selectedMessage else { return false }
        return (pageCounts[id] ?? 1) > 1
    }

    /// Turn the clicked answer by `delta` pages (driven by the arrow keys).
    func turnPage(_ delta: Int) {
        guard let id = selectedMessage else { return }
        pageTurn = PageTurn(id: id, delta: delta, token: (pageTurn?.token ?? 0) + 1)
    }

    private func stream(_ q: String, at idx: Int, id mid: UUID,
                        attachments: [ChatAttachment] = []) async -> Bool {
        var received = false
        var lastFlush = Date.distantPast
        var pending = ""
        do {
            for try await ev in client.streamEvents(question: q, conversation: currentConv,
                                                     attachments: attachments) {
                if Task.isCancelled { break }
                // The transcript can be reset or switched mid-stream (/clear,
                // New Conversation, history). Stop writing rather than index a
                // message array that shrank — or was replaced — underneath us.
                guard let m = liveMessage(idx, mid) else { return received }
                received = true
                if ev.t == "chunk" {
                    // coalesce tokens; flush at most ~20×/s (big GPU/CPU saving)
                    pending += ev.v ?? ""
                    let now = Date()
                    if now.timeIntervalSince(lastFlush) >= 0.05 {
                        m.text += pending
                        pending = ""
                        lastFlush = now
                        Perf.count("stream.flush")
                    }
                    continue
                }
                if !pending.isEmpty {
                    m.text += pending
                    pending = ""
                }
                apply(ev, to: m)
            }
            if !pending.isEmpty, let m = liveMessage(idx, mid) { m.text += pending }
        } catch {
            return received
        }
        return received
    }

    /// The message at `idx`, iff it is still the one we began streaming into.
    /// Returning the object (not the array slot) keeps token writes off the
    /// transcript array, so only this row re-renders while an answer streams.
    private func liveMessage(_ idx: Int, _ mid: UUID) -> ChatMessage? {
        guard idx < messages.count, messages[idx].id == mid else { return nil }
        return messages[idx]
    }

    private func apply(_ ev: StreamEvent, to m: ChatMessage) {
        switch ev.t {
        case "progress":
            if let v = ev.v, !v.isEmpty { m.progress = v }
        case "think":
            m.reasoning += ev.v ?? ""
        case "chunk":
            m.text += ev.v ?? ""
            m.progress = ""
        case "done":
            if let a = ev.answer, !a.isEmpty { m.text = TextStyle.clean(a) }
            m.citations = ev.citations ?? []
            m.ungrounded = ev.ungrounded ?? 0
            m.meta = ev.meta
            if let md = ev.model, !md.isEmpty {
                m.model = md
                model = md
            }
            // adopt the thread id so the next turn continues this conversation
            if let c = ev.conversation, !c.isEmpty { currentConv = c }
            m.progress = ""
        case "error":
            m.text = "Error: \(ev.v ?? "unknown")"
            m.failed = true
            m.progress = ""
        default:
            break
        }
    }

    private func askOnce(_ q: String, at idx: Int, id mid: UUID,
                         attachments: [ChatAttachment] = []) async {
        do {
            let res = try await client.ask(question: q, conversation: currentConv,
                                           attachments: attachments)
            guard let m = liveMessage(idx, mid) else { return }
            if let ans = res.answer, !ans.isEmpty {
                m.text = TextStyle.clean(ans)
            } else {
                m.text = res.error ?? "(no answer)"
            }
            m.citations = res.citations ?? []
            m.ungrounded = res.ungrounded ?? 0
            m.meta = res.meta
            if let md = res.model, !md.isEmpty {
                m.model = md
                model = md
            }
            if let c = res.conversation, !c.isEmpty { currentConv = c }
        } catch {
            guard let m = liveMessage(idx, mid) else { return }
            m.text = "Error: \(error.localizedDescription)"
            m.failed = true
        }
    }

    private func runSlash(_ line: String) {
        let body = line.dropFirst()
        let parts = body.split(separator: " ", maxSplits: 1, omittingEmptySubsequences: false)
        let cmd = parts.first.map(String.init) ?? ""
        let arg = parts.count > 1 ? String(parts[1]).trimmingCharacters(in: .whitespaces) : ""
        if cmd == "clear" {
            askTask?.cancel()
            busy = false
            messages.removeAll()
            resetTranscriptState()
            Task { await newConversation() }
            return
        }
        messages.append(ChatMessage(role: .user, text: line))
        Task { await runCommand(cmd, arg) }
    }

    func runCommand(_ cmd: String, _ arg: String) async {
        // App-side generative commands: render a scene inline, no brain needed.
        if cmd == "scene" || cmd == "chart" { appendScene(arg); return }
        busy = true
        defer { busy = false }
        do {
            let res = try await client.command(cmd, arg)
            messages.append(
                ChatMessage(
                    role: .system,
                    text: res.text ?? "no output",
                    failed: res.ok == false))
            if cmd == "status" || cmd == "index" { await loadConversations() }
        } catch {
            messages.append(
                ChatMessage(
                    role: .system, text: "/\(cmd) failed: \(error.localizedDescription)",
                    failed: true))
        }
    }

    func loadSettings() async {
        guard let data = await client.settingsData(),
            let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return }
        if let specArr = obj["spec"] as? [[String: Any]] {
            settingsSpec = specArr.compactMap { d in
                guard let k = d["key"] as? String else { return nil }
                return SettingSpec(
                    key: k, section: d["section"] as? String, help: d["help"] as? String)
            }
        }
        settingsValues = obj["values"] as? [String: Any] ?? [:]
        settingsOptions = obj["options"] as? [String: [String]] ?? [:]
    }

    func setSetting(_ key: String, _ value: Any) async {
        guard let body = try? JSONSerialization.data(withJSONObject: ["key": key, "value": value])
        else { return }
        await client.setSetting(body: body)
        await loadSettings()
    }

    static let demoSceneJSON = """
    {"title":"Indexed library","elements":[
      {"kind":"kpi","kpi":{"label":"Chunks indexed","value":"8,214","delta":"+1.2% this week","deltaUp":true}},
      {"kind":"chart","chart":{"style":"bar","title":"Chunks per work","series":[{"label":"Kojeve","value":9},{"label":"Hegel","value":6},{"label":"Dune","value":4},{"label":"Notes","value":7}]}},
      {"kind":"table","table":{"columns":["Work","Chunks","Words"],"rows":[["Kojeve","932","120k"],["Hegel","611","88k"],["Dune","404","61k"]]}}
    ]}
    """

    /// Append a model-authored `scene` block so the generative UI path is
    /// visible (from `/scene`, or the debug demo). Empty `json` uses the demo.
    func appendScene(_ json: String = "") {
        let body = json.trimmingCharacters(in: .whitespacesAndNewlines)
        messages.append(ChatMessage(
            role: .assistant,
            text: "Here is a generated view.\n\n```scene\n\(body.isEmpty ? Self.demoSceneJSON : body)\n```"))
    }

    func appendDemoScene() { appendScene() }

    /// Debug affordance: a markdown answer that exercises the semantic text
    /// colours (heading · quote · link · number · citation).
    func appendDemoMarkdown() {
        messages.append(ChatMessage(
            role: .assistant,
            text: """
            # On the creditor oligarchy

            > "The great monopoly in this country is the money monopoly."
            > — Woodrow Wilson

            You can read the primary text at https://example.com/woodrow against the
            Federal Reserve Act itself, and compare 1859 with 1913.

            **Bold** and *italic* still read; and a citation (Kojeve · Introduction).
            """))
    }

    func loadConversations() async {
        guard let list = try? await client.conversations() else { return }
        conversations = list.reversed()
    }

    func openConversation(_ id: String) async {
        askTask?.cancel()
        busy = false
        await client.openConversation(id: id)
        currentConv = id
        messages.removeAll()
        resetTranscriptState()
        guard let turns = try? await client.conversation(id: id) else { return }
        for t in turns {
            let q = t.question ?? ""
            let a = t.answer ?? ""
            if !q.isEmpty { messages.append(ChatMessage(role: .user, text: q, pendingQuestion: q)) }
            if !a.isEmpty {
                let m = ChatMessage(role: .assistant, text: TextStyle.clean(a))
                m.model = t.model ?? ""
                m.citations = extractCitations(a)
                messages.append(m)
            }
        }
    }

    /// Fetch the indexed book list for the Library shelf.
    func loadBooks() async {
        guard let list = try? await client.books() else { return }
        libraryBooks = list
    }

    /// Fetch a past conversation's content into `libraryDoc` (Library mode),
    /// without touching the current chat transcript.
    func loadLibraryDoc(_ id: String) async {
        libraryDocId = id
        libraryDoc = []
        guard let turns = try? await client.conversation(id: id) else { return }
        var out: [DocBlock] = []
        for t in turns {
            let q = t.question ?? ""
            let a = t.answer ?? ""
            if !q.isEmpty { out.append(DocBlock(label: "Q", text: q)) }
            if !a.isEmpty { out.append(DocBlock(label: "A", text: TextStyle.clean(a))) }
        }
        libraryDoc = out
    }

    /// Fetch an indexed book's extracted content (summary, concepts, excerpts).
    func loadLibraryBook(_ id: String) async {
        libraryDocId = "book:\(id)"
        libraryDoc = []
        guard let book = try? await client.book(id: id) else { return }
        var out: [DocBlock] = []
        if let s = book.summary, !s.isEmpty { out.append(DocBlock(label: "Summary", text: s)) }
        if let c = book.concepts, !c.isEmpty {
            out.append(
                DocBlock(label: "Concepts", text: c.map { "• \($0)" }.joined(separator: "\n")))
        }
        for e in book.excerpts ?? [] {
            let concept = e.concept ?? ""
            let text = e.excerpt ?? e.text ?? ""
            if !text.isEmpty {
                out.append(DocBlock(label: concept.isEmpty ? "Excerpt" : concept, text: text))
            }
        }
        libraryDoc = out
    }

    /// Drop per-transcript paging/selection state when the messages are reset, so
    /// stale page counts and a stale selected answer can't linger.
    private func resetTranscriptState() {
        pageCounts.removeAll()
        selectedMessage = nil
        pageTurn = nil
        centerRequest = nil
    }

    func newConversation() async {
        askTask?.cancel()
        busy = false
        currentConv = await client.newConversation() ?? ""
        messages.removeAll()
        resetTranscriptState()
        await loadConversations()
    }

    func renameConversation(_ id: String, _ title: String) async {
        await client.renameConversation(id: id, title: title)
        await loadConversations()
    }

    // MARK: message edit / delete / regenerate
    // The *rules* (what to forget, how the thread shifts) live in the engine
    // (store.truncate_conversation / delete_turn). The app only names the
    // operation and then re-projects the transcript from /conversation.

    /// The 0-based turn this message belongs to = user messages before it.
    func turnIndex(for id: UUID) -> Int? {
        guard let i = messages.firstIndex(where: { $0.id == id }) else { return nil }
        return messages[..<i].filter { $0.role == .user }.count
    }

    func beginEdit(_ id: UUID) {
        guard let m = messages.first(where: { $0.id == id }) else { return }
        editingID = id
        editingText = m.text
    }

    func cancelEdit() {
        editingID = nil
        editingText = ""
    }

    /// Replace a user message and re-ask from there (everything after is forgotten).
    func editMessage(_ id: UUID, to newText: String) async {
        let q = newText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !q.isEmpty, let turn = turnIndex(for: id) else { return }
        stop()
        editingID = nil
        editingText = ""
        await client.truncateConversation(id: currentConv, keep: turn)
        await rebuildTranscript()
        busy = false
        await ask(q)
    }

    /// Delete a user message and its answer (the engine closes the gap).
    func deleteMessage(_ id: UUID) async {
        guard let turn = turnIndex(for: id) else { return }
        stop()
        if editingID == id { cancelEdit() }
        await client.deleteTurn(id: currentConv, index: turn)
        await rebuildTranscript()
    }

    /// Re-ask a question whose answer sits at `id` (assistant row).
    func regenerate(_ id: UUID) async {
        guard let i = messages.firstIndex(where: { $0.id == id }) else { return }
        let priorUser = messages[..<i].last(where: { $0.role == .user })?.text ?? ""
        guard !priorUser.isEmpty else { return }
        let turn = messages[..<i].filter { $0.role == .user }.count - 1
        stop()
        await client.truncateConversation(id: currentConv, keep: max(0, turn))
        await rebuildTranscript()
        busy = false
        await ask(priorUser)
    }

    /// Rebuild the live transcript from the engine's stored turns (the projection).
    private func rebuildTranscript() async {
        guard !currentConv.isEmpty else { return }
        let turns = (try? await client.conversation(id: currentConv)) ?? []
        var rebuilt: [ChatMessage] = []
        for t in turns {
            let q = t.question ?? ""
            let a = t.answer ?? ""
            if !q.isEmpty { rebuilt.append(ChatMessage(role: .user, text: q, pendingQuestion: q)) }
            if !a.isEmpty {
                let m = ChatMessage(role: .assistant, text: TextStyle.clean(a))
                m.model = t.model ?? ""
                m.citations = extractCitations(a)
                rebuilt.append(m)
            }
        }
        messages = rebuilt
        resetTranscriptState()
    }

    func deleteConversation(_ id: String) async {
        if currentConv == id {
            askTask?.cancel()
            busy = false
        }
        await client.deleteConversation(id: id)
        if currentConv == id {
            currentConv = ""
            messages.removeAll()
            resetTranscriptState()
        }
        await loadConversations()
    }

    // MARK: theme (one authority)

    private func appearancePref() -> AppTheme {
        AppTheme(rawValue: UserDefaults.standard.string(forKey: "appearance") ?? "") ?? .fallback
    }

    /// Resolve the whole colour system from the surface look + light/dark choice.
    /// No image sampling: this is what makes the app cohesive and legible by
    /// construction (Material 3 "on-" roles / Apple semantic colours).
    func rebuildLookTheme() {
        let isDark = surfaceLook.isDark(appearance: appearancePref())
        colorTheme = ColorTheme.look(surfaceLook, isDark: isDark)
        textInk = TextInk.look(surfaceLook, isDark: isDark)
    }

    /// Switch appearance (light/dark for the `system` look; fixed for the rest).
    func setAppearance(_ t: AppTheme) {
        UserDefaults.standard.set(t.rawValue, forKey: "appearance")
        rebuildLookTheme()
    }

    /// Choose Tinted or Clear Liquid Glass.
    func setGlassStyle(_ s: GlassStyle) {
        glassStyle = s
        UserDefaults.standard.set(s.rawValue, forKey: "glassStyle")
    }

    private func extractCitations(_ answer: String) -> [Citation] {
        guard
            let re = try? NSRegularExpression(pattern: "\\(([^()\\n]{3,90}) · ([^()\\n]{1,90})\\)")
        else { return [] }
        var seen = Set<String>()
        var out: [Citation] = []
        let ns = answer as NSString
        for m in re.matches(in: answer, range: NSRange(location: 0, length: ns.length)) {
            guard m.numberOfRanges == 3 else { continue }
            let book = ns.substring(with: m.range(at: 1)).trimmingCharacters(in: .whitespaces)
            let loc = ns.substring(with: m.range(at: 2)).trimmingCharacters(in: .whitespaces)
            let key = "\(book.lowercased())·\(loc.lowercased())"
            if seen.insert(key).inserted { out.append(Citation(book: book, loc: loc)) }
        }
        return out
    }
}
