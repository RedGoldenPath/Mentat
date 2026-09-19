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
    var currentConv: String = ""
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
    var backgrounds: [String] = []
    var backgroundName: String = ""
    var bgIsLight: Bool = false
    var bgLightLeft = false
    var bgLightCenter = false
    var bgLightRight = false
    var bgTint: Color = Color.white.opacity(0.12)
    var bgTintLeft: Color = Color.white.opacity(0.14)
    var bgTintCenter: Color = Color.white.opacity(0.14)
    var bgTintRight: Color = Color.white.opacity(0.14)
    var bgRegionAvg: [NSColor] = []  // [left, center, right]
    var bgTopColor: NSColor = NSColor(white: 0.5, alpha: 1)
    /// The artwork-derived colour palette for the current background — the
    /// global authority every UI colour is resolved through.
    var bgPalette: BackgroundPalette = .placeholder
    var paletteShift: Double = 0
    var paletteStyle: PaletteStyle = .complementary
    /// The OKLCH colour system: the image reduced to perceptual colour, the
    /// user's controls, and the resulting contrast-enforced theme.
    var imagePalette: ImagePalette = .neutral
    var colorControls: ColorControls = .default
    var colorTheme: ColorTheme = .placeholder
    enum InkMode: String, Codable, Sendable { case theme, background }
    /// Whether text ink comes from the theme (matches the palette) or adapts to
    /// the photo behind each region (default). No outlines either way.
    var inkMode: InkMode =
        InkMode(rawValue: UserDefaults.standard.string(forKey: "inkMode") ?? "") ?? .background
    /// Tinted (colour-forward) or clear (clarity-forward) Liquid Glass.
    var glassStyle: GlassStyle =
        GlassStyle(rawValue: UserDefaults.standard.string(forKey: "glassStyle") ?? "") ?? .tinted
    /// When on, the live UI draws from the OKLCH theme instead of the legacy HSB
    /// palette paths. On by default now (the OKLCH look); an explicit off in
    /// prefs reverts to the classic HSB path.
    var useOKLCHTheme: Bool = {
        let d = UserDefaults.standard
        if d.object(forKey: "useOKLCHTheme") == nil { return true }
        return d.bool(forKey: "useOKLCHTheme")
    }()
    /// Normalized y (top-origin) of the calmest band in the photo, so the art
    /// can be panned to sit its least-contrasty region behind the wordmark.
    var bgQuietY: CGFloat = 0.4
    var contentSize: CGSize = .zero
    /// Size of the whole window (RootView), so overlays can show how the page
    /// layer sits inside it when the sidebar is open.
    var windowSize: CGSize = .zero
    /// Hidden power-user panel, revealed by typing `/debug`. Session-only, so
    /// the niche mechanics are never in the way unless asked for.
    var debugMode = UserDefaults.standard.bool(forKey: "debugMode") {
        didSet { UserDefaults.standard.set(debugMode, forKey: "debugMode") }
    }
    private var backgroundsLoaded = false
    /// Size at which the background regions were last sampled, so a drifting
    /// geometry (sidebar animation) doesn't re-run the CI reads on every frame.
    private var lastRegionSize: CGSize = .zero

    func isLight(_ r: BgRegion) -> Bool {
        if useOKLCHTheme { return colorTheme.isLight }
        switch r {
        case .left: return bgLightLeft
        case .center: return bgLightCenter
        case .right: return bgLightRight
        }
    }
    /// Complementary, low-saturation tint drawn from the colour behind a region.
    func tint(_ r: BgRegion) -> Color {
        if useOKLCHTheme { return colorTheme.surfaceTint }
        switch r {
        case .left: return bgTintLeft
        case .center: return bgTintCenter
        case .right: return bgTintRight
        }
    }

    /// Representative colour of the whole artwork (mean of the sampled regions),
    /// for deriving the history rail's analogous tint.
    func artMeanColor() -> NSColor {
        guard !bgRegionAvg.isEmpty else { return NSColor(white: 0.5, alpha: 1) }
        var r: CGFloat = 0
        var g: CGFloat = 0
        var b: CGFloat = 0
        for c in bgRegionAvg {
            let cc = c.usingColorSpace(.deviceRGB) ?? .gray
            r += cc.redComponent
            g += cc.greenComponent
            b += cc.blueComponent
        }
        let n = CGFloat(bgRegionAvg.count)
        return NSColor(red: r / n, green: g / n, blue: b / n, alpha: 1)
    }

    func regionColor(_ r: BgRegion) -> NSColor {
        guard !bgRegionAvg.isEmpty else { return NSColor(white: 0.5, alpha: 1) }
        switch r {
        case .left: return bgRegionAvg[0]
        case .center: return bgRegionAvg[min(1, bgRegionAvg.count - 1)]
        case .right: return bgRegionAvg[bgRegionAvg.count - 1]
        }
    }

    /// Colour-theory text palette for a region. **Luminance first**: value flips
    /// smoothly with how light the art reads (light text on dark, near-black on
    /// light). **Then hue**: when the art is colourful the ink picks up a whisper
    /// of its *contrasting* temperature, so the type reads as a considered colour
    /// rather than flat grey — but at ≤0.10 saturation, so contrast never suffers.
    func textColors(_ r: BgRegion) -> (primary: Color, secondary: Color) {
        if useOKLCHTheme {
            switch inkMode {
            case .theme:
                return (colorTheme.ink, colorTheme.inkDim)
            case .background:
                return adaptiveInk(r)
            }
        }
        let key = regionKey(r)
        if let hit = textColorCache[key] { return hit }
        let ns = regionColor(r)
        let lum = ColorTheory.luminance(ns)
        let t0 = min(1, max(0, (lum - 0.44) / 0.12))
        let t = t0 * t0 * (3 - 2 * t0)
        let value = 1.00 * (1 - t) + 0.03 * t
        // Value comes from the *region's* luminance (contrast); the hue comes from
        // the global palette ink, so one tool owns the type colour.
        let (_, rs, _) = ColorTheory.hsb(ns)
        let (ph, ps, _) = ColorTheory.hsb(bgPalette.ns(.ink))
        let placeholder = bgPalette == .placeholder
        let hue = placeholder ? ColorTheory.contrastingHue(ns) : ph
        let sat = placeholder ? min(0.10, rs * 0.20) : ps
        let primary = Color(hue: hue, saturation: sat, brightness: value)
        let result = (primary, primary.opacity(0.78))
        textColorCache[key] = result
        return result
    }

    /// Region-adaptive ink: pick light/dark from the photo behind the region and
    /// enforce WCAG against it. A whisper of the theme hue; no outline.
    private func adaptiveInk(_ r: BgRegion) -> (Color, Color) {
        let key = regionKey(r) + "|adapt"
        if let hit = textColorCache[key] { return hit }
        let ns = regionColor(r)
        let result = (adaptiveText(ns, dim: false), adaptiveText(ns, dim: true))
        textColorCache[key] = result
        return result
    }

    private func adaptiveText(_ ns: NSColor, dim: Bool) -> Color {
        let target = ColorScience.oklch(ns)
        let appearance =
            AppTheme(rawValue: UserDefaults.standard.string(forKey: "appearance") ?? "")
            ?? .fallback
        let bgLight = BackgroundAnalysis.gradedLuminance(ns, theme: appearance) >= 0.5
        let l = dim ? (bgLight ? 0.42 : 0.80) : (bgLight ? 0.16 : 0.96)
        let ink = ColorScience.enforce(
            ColorScience.OKLCH(l: l, c: 0.02, h: colorTheme.baseHue), on: target, level: .body)
        return Color(nsColor: ColorScience.nsColor(ink))
    }

    /// Memoized `adaptiveText` for the top band — called from several view
    /// bodies every frame, but only changes when the sampled art does.
    private func topInk(dim: Bool) -> Color {
        let key = "\(colorVersion)|topink|\(dim ? 1 : 0)"
        if let hit = textColorCache[key] { return hit.0 }
        let c = adaptiveText(bgTopColor, dim: dim)
        textColorCache[key] = (c, c)
        return c
    }

    /// Title colour: mostly plain black or white for guaranteed contrast
    /// (dark title on light art, light on dark). Only when the artwork behind
    /// is genuinely colourful does it take on a bright *analogous* hue — one that
    /// stays in the art's own warm/cool family — never a muddy mid-tone.
    func titleColor(_ r: BgRegion = .center) -> Color {
        if useOKLCHTheme {
            return inkMode == .theme ? colorTheme.ink : adaptiveInk(r).0
        }
        let ns = regionColor(r)
        let lum = ColorTheory.luminance(ns)
        let (_, s, _) = ColorTheory.hsb(ns)
        let colorful = s > 0.18
        let (ph, ps, _) = ColorTheory.hsb(bgPalette.ns(.analogous))
        let placeholder = bgPalette == .placeholder
        let hue = placeholder ? ColorTheory.adjacentHue(ns) : ph
        let sat = colorful ? min(0.62, max(s * 1.1, placeholder ? 0 : ps)) : 0.0
        let value: CGFloat = lum < 0.5 ? 0.99 : 0.05  // light on dark, dark on light
        return Color(hue: hue, saturation: sat, brightness: value)
    }

    /// The region's colour temperature (warm/cool/neutral) — the hue axis that
    /// decides which side of the wheel the UI leans toward.
    func temperature(_ r: BgRegion) -> ColorTheory.Temperature {
        ColorTheory.temperature(regionColor(r))
    }
    func artTemperature() -> ColorTheory.Temperature {
        ColorTheory.temperature(artMeanColor())
    }

    /// UI accent for a region: from the artwork palette (a saturated tone of the
    /// art's contrasting temperature), so controls pop against a warm photo with
    /// cool accents and vice-versa. Falls back to the brand spice for greyscale.
    func accentColor(_ r: BgRegion = .left) -> Color {
        if useOKLCHTheme { return colorTheme.accent }
        if bgPalette != .placeholder, !bgPalette.isNeutral { return bgPalette.accent }
        let ns = regionColor(r)
        let (_, s, _) = ColorTheory.hsb(ns)
        guard ColorTheory.temperature(ns) != .neutral, s > 0.12 else { return Palette.day.spice }
        return Color(
            hue: ColorTheory.contrastingHue(ns),
            saturation: min(0.72, max(0.42, s)),
            brightness: 0.86)
    }

    /// Title colour for the top band (the wordmark once it rises to R1): plain
    /// high-contrast black or white, with an analogous hue when colourful.
    func topTitleColor() -> Color {
        if useOKLCHTheme {
            return inkMode == .theme ? colorTheme.ink : topInk(dim: false)
        }
        let ns = bgTopColor
        let lum = ColorTheory.luminance(ns)
        let (_, s, _) = ColorTheory.hsb(ns)
        let colorful = s > 0.18
        let hue = ColorTheory.adjacentHue(ns)
        let sat = colorful ? min(0.62, s * 1.1) : 0.0
        let value: CGFloat = lum < 0.5 ? 0.99 : 0.05
        return Color(hue: hue, saturation: sat, brightness: value)
    }

    func text(_ r: BgRegion) -> Color { textColors(r).primary }
    func dim(_ r: BgRegion) -> Color { textColors(r).secondary }

    // MARK: wordmark ink

    /// Size of the artwork as decoded (aspect preserved), so the background can
    /// be panned to put a quiet band behind the title.
    private(set) var bgImageSize: CGSize = .zero

    /// One consistent ink for the whole wordmark: white or near-black, decided
    /// once from the overall brightness of the top band behind it. No per-letter
    /// sampling, so the word can never come out patchwork.
    func titleInk() -> Color {
        guard !bgRegionAvg.isEmpty else { return .primary }
        let theme =
            AppTheme(rawValue: UserDefaults.standard.string(forKey: "appearance") ?? "")
            ?? .fallback
        // Always luminance-based so the wordmark stays legible on any art.
        return BackgroundAnalysis.gradedLuminance(bgTopColor, theme: theme) < 0.5
            ? Color(white: 1.0) : Color(white: 0.06)
    }

    /// High-contrast foreground for the top area (empty state / chrome).
    func topText() -> Color {
        if useOKLCHTheme {
            return inkMode == .theme ? colorTheme.ink : topInk(dim: false)
        }
        return BackgroundAnalysis.luminance(bgTopColor) < 0.5
            ? Color(white: 1.0) : Color(white: 0.03)
    }
    func topTextDim() -> Color {
        if useOKLCHTheme {
            return inkMode == .theme ? colorTheme.inkDim : topInk(dim: true)
        }
        return BackgroundAnalysis.luminance(bgTopColor) < 0.5
            ? Color(white: 0.78) : Color(white: 0.28)
    }

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
        if useOKLCHTheme { return colorTheme.isLight ? 0.42 : 0.58 }
        let key = regionKey(r)
        if let hit = scrimCache[key] { return hit }
        let ns = regionColor(r).usingColorSpace(.deviceRGB) ?? NSColor(white: 0.5, alpha: 1)
        let lum = 0.2126 * ns.redComponent + 0.7152 * ns.greenComponent + 0.0722 * ns.blueComponent
        let midness = 1 - min(1, abs(lum - 0.5) * 2)
        // solid floor guarantees legibility; extra where the photo is mid-toned
        let value = 0.26 + 0.46 * Double(midness)
        scrimCache[key] = value
        return value
    }

    /// Colour math hit by every row render; cached per region and invalidated
    /// whenever the sampled artwork changes.
    @ObservationIgnored private var colorVersion = 0
    @ObservationIgnored private var textColorCache: [String: (Color, Color)] = [:]
    @ObservationIgnored private var scrimCache: [String: Double] = [:]

    private func regionKey(_ r: BgRegion) -> String {
        let tag: String
        switch r {
        case .left: tag = "l"
        case .center: tag = "c"
        case .right: tag = "r"
        }
        return "\(colorVersion)|\(tag)"
    }

    /// Drop cached colour derivations (call when the sampled regions change).
    private func invalidateColorCaches() {
        colorVersion &+= 1
        textColorCache.removeAll()
        scrimCache.removeAll()
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
        askTask = Task { await ask(q) }
    }

    func ask(_ raw: String) async {
        let q = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !q.isEmpty, !busy else { return }
        busy = true
        messages.append(ChatMessage(role: .user, text: q))
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
        let received = await stream(q, at: idx, id: mid)
        if Task.isCancelled {
            if idx < messages.count, messages[idx].id == mid, messages[idx].text.isEmpty {
                messages[idx].text = "_[stopped]_"
            }
            return
        }
        if !received { await askOnce(q, at: idx, id: mid) }
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

    func reAsk(_ id: UUID) {
        guard let i = messages.firstIndex(where: { $0.id == id }) else { return }
        let q = messages[i].pendingQuestion ?? messages[i].text
        askTask?.cancel()
        busy = false
        for m in messages[i...] { pageCounts[m.id] = nil }
        messages.removeSubrange(i...)
        askTask = Task { await ask(q) }
    }

    private func stream(_ q: String, at idx: Int, id mid: UUID) async -> Bool {
        var received = false
        var lastFlush = Date.distantPast
        var pending = ""
        do {
            for try await ev in client.streamEvents(question: q) {
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
            m.progress = ""
        case "error":
            m.text = "Error: \(ev.v ?? "unknown")"
            m.failed = true
            m.progress = ""
        default:
            break
        }
    }

    private func askOnce(_ q: String, at idx: Int, id mid: UUID) async {
        do {
            let res = try await client.ask(question: q)
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
        await client.newConversation()
        currentConv = ""
        messages.removeAll()
        resetTranscriptState()
        await loadConversations()
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

    // MARK: backgrounds

    var bgText: Color { bgIsLight ? Color(red: 0.10, green: 0.08, blue: 0.06) : Color(white: 0.97) }
    var bgTextDim: Color {
        bgIsLight ? Color(red: 0.32, green: 0.26, blue: 0.18) : Color(white: 0.72)
    }

    func loadBackgrounds() {
        guard !backgroundsLoaded else { return }
        backgroundsLoaded = true
        // Cataloguing reads ImageIO metadata for ~130 files; keep it off-main so
        // first paint isn't gated on it.
        Task { [weak self] in
            let names = await Task.detached(priority: .userInitiated) {
                BackgroundAnalysis.catalog()
            }.value
            guard let self else { return }
            self.backgrounds = names
            guard !names.isEmpty else { return }
            let saved = UserDefaults.standard.string(forKey: "background") ?? ""
            // First launch should show the colour system off: alphabetical order
            // would land on whatever `bg-` sorts first, which is often a washed
            // -out photo that reads as grey. Prefer a vivid curated piece.
            let preferred = "bg-curated-aurora-1"
            let fallback = names.contains(preferred) ? preferred : names[0]
            if UserDefaults.standard.bool(forKey: "shuffleBackgrounds"),
                let r = names.randomElement()
            {
                self.selectBackground(r)
            } else {
                self.selectBackground(names.contains(saved) ? saved : fallback)
            }
        }
    }

    func selectBackground(_ name: String) {
        guard !name.isEmpty else { return }
        invalidateColorCaches()
        backgroundName = name
        UserDefaults.standard.set(name, forKey: "background")
        let appearance =
            AppTheme(rawValue: UserDefaults.standard.string(forKey: "appearance") ?? "")
            ?? .fallback
        guard let img = BackgroundAnalysis.thumb(name, max: 512) else { return }
        bgImageSize = img.size
        rebuildPalette(for: name, image: img)
        rebuildColorTheme(for: name, image: img)
        lastRegionSize = .zero
        // The quiet-band scan (36 samples) and the region read run off-main;
        // neither should be able to hitch a background switch.
        scheduleRegionAnalysis(name: name, image: img, appearance: appearance, computeQuiet: true)
    }

    /// Shared pipeline for region sampling: build the source rects off-main from
    /// the visible geometry, read the averages, then publish on the main actor.
    private func scheduleRegionAnalysis(
        name: String, image: NSImage, appearance: AppTheme, computeQuiet: Bool
    ) {
        let key = "thumb|\(name)"
        let content = contentSize
        let imageSize = bgImageSize
        let quietY = bgQuietY
        let box = Unchecked(image)
        regionTask?.cancel()
        regionTask = Task { [weak self] in
            let started = CFAbsoluteTimeGetCurrent()
            let out = await Task.detached(priority: .userInitiated) {
                () -> (CGFloat?, [BackgroundAnalysis.RGB]) in
                let q =
                    computeQuiet
                    ? BackgroundAnalysis.cachedQuietBandY(box.value, key: key, theme: appearance)
                    : nil
                let rects = BackgroundAnalysis.regionRects(
                    content: content, image: imageSize, quietY: q ?? quietY)
                let samples = BackgroundAnalysis.regionAverages(box.value, key: key, rects: rects)
                return (q, samples)
            }.value
            guard let self, !Task.isCancelled else { return }
            if let q = out.0 { self.bgQuietY = q }
            self.applyRegionSamples(out.1, appearance: appearance)
            Perf.record("regions", ms: (CFAbsoluteTimeGetCurrent() - started) * 1000)
        }
    }

    private func applyRegionSamples(_ s: [BackgroundAnalysis.RGB], appearance: AppTheme) {
        guard s.count == 4 else { return }
        let lAvg = s[0].nsColor
        let cAvg = s[1].nsColor
        let rAvg = s[2].nsColor
        bgRegionAvg = [lAvg, cAvg, rAvg]
        bgTopColor = s[3].nsColor
        invalidateColorCaches()
        let light = { (c: NSColor) in BackgroundAnalysis.gradedLuminance(c, theme: appearance) > 0.5
        }
        bgLightLeft = light(lAvg)
        bgLightCenter = light(cAvg)
        bgLightRight = light(rAvg)
        bgTintLeft = BackgroundAnalysis.complementaryTint(from: lAvg, isLight: bgLightLeft)
        bgTintCenter = BackgroundAnalysis.complementaryTint(from: cAvg, isLight: bgLightCenter)
        bgTintRight = BackgroundAnalysis.complementaryTint(from: rAvg, isLight: bgLightRight)
        bgIsLight = bgLightCenter
        bgTint = bgTintCenter
    }

    /// Build the artwork palette for `name` at the current global shift and
    /// palette style. The image analysis (clusters + hue/brightness) is cached
    /// to disk per image, so styles can be re-derived instantly.
    func rebuildPalette(for name: String, image: NSImage? = nil) {
        // When the OKLCH theme is live the legacy HSB palette is never consulted,
        // so skip the extraction entirely.
        if useOKLCHTheme {
            bgPalette = .placeholder
            return
        }
        paletteShift = UserDefaults.standard.double(forKey: "paletteShift")
        paletteStyle =
            PaletteStyle(rawValue: UserDefaults.standard.string(forKey: "paletteStyle") ?? "")
            ?? .complementary
        guard !name.isEmpty else {
            bgPalette = .placeholder
            return
        }
        if let a = analysis(for: name, image: image) {
            let theme =
                AppTheme(rawValue: UserDefaults.standard.string(forKey: "appearance") ?? "")
                ?? .fallback
            let mono = theme == .mono
            let dark = mono || !a.isLight
            bgPalette = PaletteExtractor.palette(
                from: a, style: paletteStyle, dark: dark, monochrome: mono
            )
            .rotated(by: paletteShift)
        } else {
            bgPalette = .placeholder
        }
    }

    /// Build the OKLCH theme for `name`. The pixel sample is taken on the main
    /// thread (cheap), but the quantization runs off-main so a background switch
    /// can't hitch; the theme is published back on the main actor.
    func rebuildColorTheme(for name: String, image: NSImage? = nil) {
        colorControls = currentColorControls()
        guard !name.isEmpty,
            let img = image ?? BackgroundAnalysis.thumb(name, max: 320)
        else {
            imagePalette = .neutral
            colorTheme = .placeholder
            return
        }
        let controls = colorControls
        let box = Unchecked(img)
        analysisTask?.cancel()
        analysisTask = Task { [weak self] in
            let started = CFAbsoluteTimeGetCurrent()
            let palette = await Task.detached(priority: .utility) {
                guard let px = ImageAnalyzer.pixels(box.value, side: 56) else {
                    return ImagePalette.neutral
                }
                return ImageAnalyzer.quantize(px, side: 56)
            }.value
            guard let self, !Task.isCancelled else { return }
            self.imagePalette = palette
            self.colorTheme = ColorResolver.theme(for: palette, controls: controls)
            Perf.record("analyze", ms: (CFAbsoluteTimeGetCurrent() - started) * 1000)
        }
    }

    /// Cached OKLCH analysis for an arbitrary background (the debug picker), so
    /// the debug panel never re-analyzes on every render.
    @ObservationIgnored private var paletteCache: [String: ImagePalette] = [:]
    @ObservationIgnored private var analysisTask: Task<Void, Never>?
    @ObservationIgnored private var regionTask: Task<Void, Never>?
    func palette(for name: String) -> ImagePalette {
        if name.isEmpty { return imagePalette }
        if let hit = paletteCache[name] { return hit }
        guard let img = BackgroundAnalysis.thumb(name, max: 320) else { return .neutral }
        let p = Perf.time("analyze") { ImageAnalyzer.analyze(img) }
        paletteCache[name] = p
        if paletteCache.count > 32 { paletteCache.removeAll() }
        return p
    }

    private func currentColorControls() -> ColorControls {
        let defaults = UserDefaults.standard
        // One-time lift: installs from before the vibrancy pass stored the old
        // 1.0/1.0 defaults, so the raised ceilings were never felt. Nudge only
        // untouched values to the Vivid starting point.
        if !defaults.bool(forKey: "colorVividBumpV1") {
            defaults.set(true, forKey: "colorVividBumpV1")
            if defaults.object(forKey: "colorChroma") == nil
                || defaults.double(forKey: "colorChroma") <= 1.0
            {
                defaults.set(1.4, forKey: "colorChroma")
            }
            if defaults.object(forKey: "colorTintStrength") == nil
                || defaults.double(forKey: "colorTintStrength") <= 1.0
            {
                defaults.set(1.3, forKey: "colorTintStrength")
            }
            if defaults.object(forKey: "colorContrast") == nil {
                defaults.set(1.1, forKey: "colorContrast")
            }
        }
        let appearance =
            AppTheme(rawValue: defaults.string(forKey: "appearance") ?? "") ?? .fallback
        var c = ColorControls.default
        if let raw = defaults.string(forKey: "colorScheme"),
            let scheme = PaletteScheme(rawValue: raw)
        {
            c.scheme = scheme
        }
        c.hueShift = defaults.double(forKey: "colorHueShift")
        if defaults.object(forKey: "colorChroma") != nil {
            c.chroma = defaults.double(forKey: "colorChroma")
        }
        if defaults.object(forKey: "colorContrast") != nil {
            c.contrast = defaults.double(forKey: "colorContrast")
        }
        if defaults.object(forKey: "colorTintStrength") != nil {
            c.tintStrength = defaults.double(forKey: "colorTintStrength")
        }
        if defaults.object(forKey: "colorFollowImage") != nil {
            c.followImage = defaults.bool(forKey: "colorFollowImage")
        }
        c.light = (appearance == .hue)
        c.monochrome = (appearance == .mono)
        return c
    }

    /// Update the OKLCH controls and re-resolve the theme immediately.
    func setColorControls(_ c: ColorControls) {
        let defaults = UserDefaults.standard
        defaults.set(c.scheme.rawValue, forKey: "colorScheme")
        defaults.set(c.hueShift, forKey: "colorHueShift")
        defaults.set(c.chroma, forKey: "colorChroma")
        defaults.set(c.contrast, forKey: "colorContrast")
        defaults.set(c.tintStrength, forKey: "colorTintStrength")
        defaults.set(c.followImage, forKey: "colorFollowImage")
        colorControls = c
        colorTheme = ColorResolver.theme(for: imagePalette, controls: c)
        invalidateColorCaches()
    }

    /// The theme a given scheme would produce for the current image — powers the
    /// palette tool's preview list.
    func previewTheme(for scheme: PaletteScheme) -> ColorTheme {
        var c = colorControls
        c.scheme = scheme
        return ColorResolver.theme(for: imagePalette, controls: c)
    }

    /// Turn the OKLCH theme on/off for the live UI (reversible).
    func setUseOKLCHTheme(_ on: Bool) {
        useOKLCHTheme = on
        UserDefaults.standard.set(on, forKey: "useOKLCHTheme")
        if on, colorTheme == .placeholder { rebuildColorTheme(for: backgroundName) }
        invalidateColorCaches()
    }

    /// Choose whether text ink matches the theme or adapts to the background.
    func setInkMode(_ m: InkMode) {
        inkMode = m
        UserDefaults.standard.set(m.rawValue, forKey: "inkMode")
        invalidateColorCaches()
    }

    /// Choose Tinted or Clear Liquid Glass.
    func setGlassStyle(_ s: GlassStyle) {
        glassStyle = s
        UserDefaults.standard.set(s.rawValue, forKey: "glassStyle")
    }

    /// The palette's colours arranged by *dominance* in the image: a role lands
    /// next to the heaviest cluster it resembles, so the biggest areas of the
    /// photo come first and the neutrals (ink/surface) fall to the end.
    func paletteSwatches(for style: PaletteStyle) -> [Color] {
        let pal = previewPalette(for: style)
        let clusters = storedAnalyses[backgroundName]?.clusters ?? []
        func dominance(_ c: Color) -> Double {
            let ns = NSColor(c)
            var best = 0.0
            for cl in clusters where PaletteAnalyzer.distance(ns, cl.color.nsColor) < 0.30 {
                best = max(best, cl.weight)
            }
            return best
        }
        return PaletteRole.allCases
            .map { (color: pal.color($0), weight: dominance(pal.color($0))) }
            .sorted { $0.weight > $1.weight }
            .map(\.color)
    }

    /// The image's main colours, most dominant first.
    func dominantColors(count: Int = 6) -> [Color] {
        let clusters = (storedAnalyses[backgroundName]?.clusters ?? [])
            .sorted { $0.weight > $1.weight }
        let cs = clusters.prefix(count).map { $0.color.color }
        return cs.isEmpty ? PaletteRole.allCases.map { bgPalette.color($0) } : Array(cs)
    }
    /// The single dominant colour (for backgrounds).
    func mainColor() -> Color { dominantColors(count: 1).first ?? bgPalette.dominant }
    /// The next most common colour (for conversation cards etc.).
    func secondaryColor() -> Color {
        let d = dominantColors(count: 3)
        return d.count > 1 ? d[1] : (d.first ?? bgPalette.secondary)
    }

    /// A UI colour from the Material-style token set (follows the image).
    /// `dark: true` selects the dark-scheme set for always-dark surfaces.
    func token(_ role: TokenRole, dark: Bool = false) -> Color {
        (dark ? bgPalette.tokensDark : bgPalette.tokens).color(role)
    }

    /// The cached analysis of `name`, computing and persisting it on first use.
    func analysis(for name: String, image: NSImage? = nil) -> ImageAnalysis? {
        guard !name.isEmpty else { return nil }
        if let cached = storedAnalyses[name] { return cached }
        guard let img = image ?? BackgroundAnalysis.thumb(name, max: 320) else { return nil }
        let a = PaletteAnalyzer.analyze(img)
        storedAnalyses[name] = a
        PaletteStore.save(storedAnalyses)
        return a
    }

    /// Global retint: rotate every derived hue so the whole UI shifts with the
    /// current background's palette.
    func setPaletteShift(_ degrees: Double) {
        UserDefaults.standard.set(degrees, forKey: "paletteShift")
        rebuildPalette(for: backgroundName)
    }

    /// Choose how the palette is built from the image (complementary, main,
    /// secondary, …). Independent of which image is selected.
    func setPaletteStyle(_ style: PaletteStyle) {
        UserDefaults.standard.set(style.rawValue, forKey: "paletteStyle")
        paletteStyle = style
        rebuildPalette(for: backgroundName)
    }

    /// The palette a given style would produce for the current image — used to
    /// show a ready-made example before the user commits to it.
    func previewPalette(for style: PaletteStyle) -> BackgroundPalette {
        guard let a = storedAnalyses[backgroundName] else { return bgPalette }
        let theme =
            AppTheme(rawValue: UserDefaults.standard.string(forKey: "appearance") ?? "")
            ?? .fallback
        let mono = theme == .mono
        return PaletteExtractor.palette(
            from: a, style: style, dark: mono || !a.isLight, monochrome: mono
        )
        .rotated(by: paletteShift)
    }

    func shufflePaletteStyle() {
        guard let next = PaletteStyle.allCases.filter({ $0 != paletteStyle }).randomElement() else {
            return
        }
        setPaletteStyle(next)
    }

    private var storedAnalyses: [String: ImageAnalysis] = PaletteStore.load()

    /// Recompute the per-region appearance from the part of the artwork that is
    /// *actually visible* — accounting for the aspect-fill crop and the quiet-band
    /// pan — so adaptive text always contrasts what is truly behind it, whatever
    /// the window size or focus state.
    func refreshBackgroundRegions(force: Bool = false) {
        // Skip unless the visible size really changed — the sidebar animation
        // fires a geometry update every frame, and each refresh is several CI
        // reads. `force` is used when the background/theme itself changes.
        if !force,
            abs(contentSize.width - lastRegionSize.width) < 8,
            abs(contentSize.height - lastRegionSize.height) < 8
        {
            return
        }
        lastRegionSize = contentSize
        guard !backgroundName.isEmpty,
            let img = BackgroundAnalysis.thumb(backgroundName, max: 512)
        else { return }
        let appearance =
            AppTheme(rawValue: UserDefaults.standard.string(forKey: "appearance") ?? "")
            ?? .fallback
        scheduleRegionAnalysis(
            name: backgroundName, image: img, appearance: appearance, computeQuiet: false)
    }

    /// The global ink tool: pure white or near-black for text sitting over the
    /// artwork behind `region`, from the graded appearance. Every adaptive text
    /// surface should route through here so the choice is consistent.
    func adaptiveInk(_ region: BgRegion = .center) -> Color {
        guard !bgRegionAvg.isEmpty else { return .primary }
        let appearance =
            AppTheme(rawValue: UserDefaults.standard.string(forKey: "appearance") ?? "")
            ?? .fallback
        return BackgroundAnalysis.gradedLuminance(regionColor(region), theme: appearance) < 0.5
            ? Color(white: 1.0) : Color(white: 0.04)
    }

    func shuffleBackground() {
        guard backgrounds.count > 1 else { return }
        if let pick = backgrounds.filter({ $0 != backgroundName }).randomElement() {
            selectBackground(pick)
        }
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
