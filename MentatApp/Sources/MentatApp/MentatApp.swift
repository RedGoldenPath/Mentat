import SwiftUI
import AppKit
import CoreImage
import CoreText
import Observation
import UniformTypeIdentifiers

// MARK: - Wire models
// Wire + chat models (Citation, AnswerMeta, AskResponse, StreamEvent,
// Conversation, LibraryBook, DocBlock, SettingSpec, ChatRole, ChatMessage,
// PageTurn) now live in Engine/Models.swift.

// SettingSpec + ChatRole moved to Engine/Models.swift.

/// Reports the natural height of the open menu panel so the popup can hug it.
private struct MenuHeightKey: PreferenceKey {
    static let defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = max(value, nextValue())
    }
}

/// Slides a view down into place while fading it in.
private struct DropIn: ViewModifier {
    let dy: CGFloat
    let opacity: Double
    func body(content: Content) -> some View {
        content.offset(y: dy).opacity(opacity)
    }
}

extension AnyTransition {
    static var dropIn: AnyTransition {
        .asymmetric(
            insertion: .modifier(active: DropIn(dy: -22, opacity: 0),
                                 identity: DropIn(dy: 0, opacity: 1)),
            removal: .modifier(active: DropIn(dy: -10, opacity: 0),
                               identity: DropIn(dy: 0, opacity: 1)))
    }
}

/// Which part of the background a view sits over (for adaptive text colour).
enum BgRegion { case left, center, right }

// ChatMessage moved to Engine/Models.swift.

// PageTurn moved to Engine/Models.swift.

// Controls moved to DesignSystem/Controls.swift (availability gates dropped).

// Glass surfaces moved to DesignSystem/Glass.swift (availability gates dropped).

struct HideWindowToolbar: ViewModifier {
    func body(content: Content) -> some View {
        content.toolbarVisibility(.hidden, for: .windowToolbar)
    }
}

struct ScrollEdgeEffect: ViewModifier {
    func body(content: Content) -> some View {
        content
            .scrollEdgeEffectStyle(.soft, for: .top)
            .scrollEdgeEffectStyle(.soft, for: .bottom)
    }
}

// MARK: - Engine

@MainActor
// Engine moved to Engine/Engine.swift.

// Command catalog moved to Commands/Command.swift (the one registry).

// Typography (TextStyle / TextLayout) lives in DesignSystem/Typography.swift.


// Reader (TappableTextView/BookTextView/ArrowKeyMonitor/BookText/PagedText)
// moved to Screens/Reader/Reader.swift.


/// A single-line, floating dropdown (glass) that reveals its content.
struct DropdownRow<Content: View>: View {
    let title: String
    let count: Int?
    let tint: Color
    @ViewBuilder var content: () -> Content
    @State private var open = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Button {
                withAnimation(Anim.snappy) { open.toggle() }
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: "chevron.right")
                        .font(.system(size: TypeScale.micro, weight: .bold))
                        .rotationEffect(.degrees(open ? 90 : 0))
                    Text(count.map { "\(title) · \($0)" } ?? title)
                        .font(.system(size: TypeScale.body, weight: .medium))
                }
                .foregroundStyle(tint)
                .padding(.horizontal, 10).padding(.vertical, 5)
                .liquid(corner: 12, interactive: true)
            }
            .buttonStyle(.plain)
            if open { content() }
        }
    }
}

// MARK: - Message row

struct MessageRow: View {
    let message: ChatMessage
    var engine: Engine
    @AppStorage("gridCols") private var gridCols = 9
    @AppStorage("gridGutter") private var gridGutter = 16.0
    @AppStorage("gridMargin") private var gridMargin = 20.0
    @Environment(\.palette) private var pal
    @Environment(\.design) private var design
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(InspectorStore.self) private var inspectorStore: InspectorStore?
    @State private var lastCount = 0
    @State private var bubbleAnim: Animation = Anim.smooth
    @State private var hover = false
    @FocusState private var editFocused: Bool
    /// Content ink comes from the surface palette's on-roles — legible by
    /// construction. (The image-driven `Legibility` resolver is now reserved for
    /// the optional artwork accent behind the sidebar / hero.)
    private func bubbleInk(_ r: BgRegion) -> Color { pal.text }
    private func bubbleDim(_ r: BgRegion) -> Color { pal.textDim }

    private func trackText(_ text: String) {
        let delta = abs(text.count - lastCount)
        lastCount = text.count
        bubbleAnim = Anim.bubble(delta)
    }

    /// Header band that lives *inside* each bubble: role name + glyph, ruled off
    /// from the body by a hairline, so the body reads as its own section rather
    /// than raw padding. Natural width, so a hugging bubble stays hugged.
    private func roleHeader(
        _ name: String, symbol: String, region: BgRegion, active: Bool = false
    ) -> some View {
        HStack(spacing: 6) {
            Image(systemName: symbol)
                .font(.system(size: TypeScale.micro, weight: .bold))
                // Apple's "working" cue: the glyph breathes while the answer
                // streams, so the bubble feels alive without a spinner.
                .symbolEffect(.pulse, options: .repeating, isActive: active)
            Text(name).font(.system(size: TypeScale.caption, weight: .semibold)).tracking(0.7)
        }
        .foregroundStyle(bubbleDim(region))
    }

    /// Strip inline markdown markers for the cheap streaming preview; the
    /// finished answer gets the full attributed treatment.
    private func streamingPreview(_ s: String) -> String {
        s.replacingOccurrences(of: "*", with: "")
         .replacingOccurrences(of: "^", with: "")
         .replacingOccurrences(of: "`", with: "")
    }

    var body: some View {
        switch message.role {
        case .user: user
        case .assistant: assistant
        case .system: system
        }
    }

    private var user: some View {
        HStack {
            Spacer(minLength: 0)
            VStack(alignment: .trailing, spacing: 0) {
                roleHeader("you", symbol: "person.fill", region: .right)
                if !message.attachmentNames.isEmpty {
                    VStack(alignment: .trailing, spacing: 2) {
                        ForEach(message.attachmentNames, id: \.self) { n in
                            HStack(spacing: 4) {
                                Image(systemName: "doc.text")
                                Text(n).lineLimit(1)
                            }
                            .font(.system(size: TypeScale.meta))
                            .foregroundStyle(bubbleDim(.right))
                        }
                    }
                    .padding(.top, 6)
                }
                if engine.editingID == message.id {
                    editField
                        .padding(.top, design.composition.roleHeaderTop)
                } else {
                    BookText(text: message.text,
                             color: bubbleInk(.right).opacity(0.92),
                             ink: engine.textInk,
                             onTap: { engine.center(message.id) })
                        .padding(.top, design.composition.roleHeaderTop)
                    messageActions(isUser: true)
                        .padding(.top, 11)
                        .opacity(hover ? 1 : 0)
                }
            }
            .padding(.horizontal, design.composition.bubblePaddingH)
            .padding(.top, design.composition.bubblePaddingTop)
            .padding(.bottom, design.composition.bubblePaddingBottom)
            // a lighter, region-tinted backing so the reader's own words read as
            // a distinct, brighter note against the darker "mentat" answers
            // a subtle raised surface — the reader's own note, not a card
            .background {
                RoundedRectangle(cornerRadius: design.composition.bubbleCorner, style: .continuous)
                    .fill(pal.bg2.opacity(pal.isDark ? 0.85 : 0.75))
            }
            .onTapGesture { engine.center(message.id) }
            .onHover { hover = $0 }
            .accessibilityElement(children: .contain)
            Spacer(minLength: 0)
        }
        .animation(reduceMotion ? nil : bubbleAnim, value: message.text)
        .onAppear { lastCount = message.text.count }
        .onChange(of: message.text) { _, t in trackText(t) }
    }

    /// Hover-revealed per-message actions. User messages can be edited/deleted
    /// (deleting removes the answer too); the bot's turns can only be regenerated
    /// or copied — matching ChatGPT/DeepSeek/Claude, and avoiding turn-index drift.
    private func messageActions(isUser: Bool) -> some View {
        HStack(spacing: 8) {
            if isUser {
                ActionButton(system: "pencil", help: "Edit") { engine.beginEdit(message.id) }
                ActionButton(system: "doc.on.doc", help: "Copy") { copyToPasteboard(message.text) }
                ActionButton(system: "trash", help: "Delete") {
                    Task { await engine.deleteMessage(message.id) }
                }
            } else {
                ActionButton(system: "arrow.clockwise", help: "Regenerate") {
                    Task { await engine.regenerate(message.id) }
                }
                ActionButton(system: "doc.on.doc", help: "Copy") { copyToPasteboard(message.text) }
            }
        }
    }

    /// Inline editor shown while a user message is being edited (ChatGPT-style).
    private var editField: some View {
        let binding = Binding(get: { engine.editingText }, set: { engine.editingText = $0 })
        return VStack(alignment: .trailing, spacing: 8) {
            TextEditor(text: binding)
                .font(.system(size: TextStyle.fontSize, design: .monospaced))
                .foregroundStyle(bubbleInk(.right))
                .scrollContentBackground(.hidden)
                .frame(minWidth: 220, minHeight: 64)
                .padding(6)
                .background(bubbleInk(.right).opacity(0.06),
                            in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .stroke(bubbleInk(.right).opacity(0.25), lineWidth: 1))
                .focused($editFocused)
            HStack(spacing: 8) {
                Spacer(minLength: 0)
                Button("Cancel") { engine.cancelEdit() }
                    .buttonStyle(.plain)
                    .foregroundStyle(bubbleDim(.right))
                Button("Save") {
                    let t = engine.editingText
                    Task { await engine.editMessage(message.id, to: t) }
                }
                .buttonStyle(.plain)
                .foregroundStyle(engine.accentColor(.right))
                .keyboardShortcut(.defaultAction)
            }
            .font(.system(size: TypeScale.caption, weight: .semibold))
        }
        .onAppear { editFocused = true }
    }

    private var assistant: some View {
        let _ = Perf.count("row.assistant")
        let m = CGFloat(gridMargin)
        let contentW = max(200, engine.contentSize.width - 2 * m)
        // the bubble spans C1…C9; the text sits inside a gutter of padding so it
        // never runs into the rounded edges (the columns share the same gutter)
        let hPad = CGFloat(gridGutter)
        let textArea = max(240, contentW - 2 * hPad)
        return HStack(spacing: 0) {
        Spacer(minLength: 0)
        VStack(alignment: .leading, spacing: 8) {
            // ---- the bubble itself ----
            VStack(alignment: .leading, spacing: 0) {
                roleHeader("mentat", symbol: "sparkles", region: .left, active: message.streaming)
                VStack(alignment: .leading, spacing: 8) {
                if !message.reasoning.isEmpty {
                    DropdownRow(title: "Thoughts", count: nil, tint: bubbleDim(.left)) {
                        // Same single column as the answer, at caption scale.
                        ReadingColumn(
                            text: message.reasoning,
                            color: bubbleDim(.left),
                            availableWidth: textArea,
                            ink: engine.textInk,
                            fontSize: 11)
                    }
                }

                if message.text.isEmpty && message.streaming {
                    HStack(spacing: 8) {
                        ProgressView().controlSize(.small)
                        Text(message.progress.isEmpty ? "thinking…" : message.progress)
                            .font(.callout).foregroundStyle(bubbleDim(.left))
                    }
                } else if message.streaming {
                    // Cheap live preview: a plain text view while tokens arrive.
                    // The expensive justified/paged layout is only built once the
                    // answer is complete, so streaming no longer re-typesets the
                    // whole column ~20×/s.
                    Text(streamingPreview(message.text))
                        .font(.system(size: TextStyle.fontSize, design: .monospaced))
                        .foregroundStyle(message.failed ? pal.bad : bubbleInk(.left))
                        .textSelection(.enabled)
                        .frame(maxWidth: TextStyle.maxMeasure(), alignment: .leading)
                    Text(message.progress.isEmpty ? "writing…" : message.progress)
                        .font(.caption).foregroundStyle(bubbleDim(.left))
                } else {
                    ReadingColumn(text: message.text,
                                  color: message.failed ? pal.bad : bubbleInk(.left),
                                  availableWidth: textArea,
                                  ink: engine.textInk,
                                  onTap: {
                                      engine.center(message.id)
                                      inspectorStore?.focus(message.id)
                                  })
                }

                HStack(spacing: 10) {
                    if message.streaming {
                        ActionButton(system: "stop.circle", help: "Stop") { engine.stop() }
                    } else if !message.text.isEmpty {
                        messageActions(isUser: false)
                            .opacity(hover ? 1 : 0)
                    }
                }

                // Generated views render inline, right under the answer — not only
                // in the Inspector. Any `scene`/`genui` block a model (or the
                // /scene command) emits shows up here through the element registry.
                if !message.streaming {
                    ForEach(
                        Array(SceneParser.extract(from: message.text).enumerated()), id: \.offset
                    ) { _, spec in
                        SceneRenderer(spec: spec)
                            .frame(maxWidth: TextStyle.maxMeasure(), alignment: .leading)
                            .padding(.top, 2)
                    }
                }
                }
                // a short beat between the "mentat" label and the answer body
                .padding(.top, 18)
            }
            // roomier padding, with the header band inside so the role reads as a
            // header rather than a caption perched on the bubble's edge
            .padding(.horizontal, hPad)
            .padding(.top, design.composition.bubblePaddingTop)
            .padding(.bottom, design.composition.bubblePaddingBottom)
            // plain prose in the reading column (Claude / Obsidian) — no card
            // clicking an answer keeps it centred so a page/reasoning animation
            // can't carry it out of the viewport, and pins the Inspector to it
            .onTapGesture {
                engine.center(message.id)
                inspectorStore?.focus(message.id)
            }
            // hugs its content and grows outward from the centre

            // ---- citations float underneath the bubble ----
            if !message.citations.isEmpty || message.ungrounded > 0 || message.meta != nil {
                DropdownRow(title: "Citations",
                            count: message.citations.isEmpty ? nil : message.citations.count,
                            tint: bubbleDim(.left)) {
                    VStack(alignment: .leading, spacing: 8) {
                        if message.ungrounded > 0 {
                            Label("\(message.ungrounded) unverified", systemImage: "exclamationmark.triangle")
                                .font(.caption2).foregroundStyle(engine.accentColor(.center))
                                .padding(.horizontal, 8).padding(.vertical, 3)
                                .background(engine.accentColor(.center).opacity(0.15), in: Capsule())
                        }
                        if !message.citations.isEmpty {
                            FlowRow(spacing: 6) {
                                ForEach(message.citations.prefix(10)) { c in
                                    CitationChip(citation: c) {
                                        engine.openSource(c, hint: message.text)
                                    }
                                }
                            }
                        }
                        if let meta = message.meta, !message.streaming {
                            Text(metaLine(meta)).font(.caption2).foregroundStyle(bubbleDim(.left))
                        }
                    }
                }
                .padding(.leading, 4)
            }
        }
        // no spring while tokens stream in (20×/s would thrash layout); animate
        // the grow only once, or for the reader's own messages
        .onHover { hover = $0 }
        .animation(message.streaming || reduceMotion ? nil : bubbleAnim, value: message.text)
        .onAppear { lastCount = message.text.count }
        .onChange(of: message.text) { _, t in trackText(t) }
        Spacer(minLength: 0)
        }
    }

    private var system: some View {
        Text(message.text)
            .font(.system(.callout, design: .monospaced))
            .foregroundStyle(message.failed ? pal.bad : engine.dim(.center))
            .textSelection(.enabled)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(12)
            // content layer: the same bubble plate as the transcript
            .background(
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .fill(pal.bg2.opacity(0.45)))
    }

    private func metaLine(_ meta: AnswerMeta) -> String {
        var bits: [String] = []
        if !message.model.isEmpty { bits.append(message.model) }
        if let k = meta.kind, !k.isEmpty { bits.append(k.uppercased()) }
        if let t = meta.t_content, t > 0 { bits.append(String(format: "%.1fs", t)) }
        if let tin = meta.tokens_in, let tout = meta.tokens_out { bits.append("\(tin)/\(tout) tok") }
        if let hit = meta.cache_hit_tokens, hit > 0 { bits.append("cached \(hit)") }
        if let reason = meta.route_reason, !reason.isEmpty { bits.append(reason) }
        if let c = meta.cost_usd, c > 0 { bits.append(String(format: "$%.4f", c)) }
        return bits.joined(separator: "  ·  ")
    }
}

func copyToPasteboard(_ s: String) {
    NSPasteboard.general.clearContents()
    NSPasteboard.general.setString(s, forType: .string)
}

// FlowRow + StaggeredGrid moved to DesignSystem/Masonry.swift
// (StaggeredGrid now caches measured heights per width).

// MARK: - Chat view

struct ChatView: View {
    var engine: Engine
    var compact: Bool = false
    @Environment(\.sandMotion) private var sandMotion
    @State private var question = ""
    @State private var showPalette = false
    @State private var showMenu = UserDefaults.standard.bool(forKey: "debugShowMenu")
    @State private var menuPanel: MenuPanel? =
        (UserDefaults.standard.string(forKey: "debugMenuPanel").flatMap { MenuPanel(rawValue: $0) })
    @State private var menuDetailH: CGFloat = 0
    @State private var composerH: CGFloat = 0
    @State private var showImporter = false
    @State private var dropTargeted = false
    @State private var inputHeight: CGFloat = 38

    /// Which sub-panel the hamburger's icon rail has open.
    private enum MenuPanel: String, CaseIterable, Identifiable {
        case looks, sand, settings, command
        var id: String { rawValue }
        var symbol: String {
            switch self {
            case .looks:      return "paintbrush.pointed.fill"
            case .sand:       return "mountain.2.fill"
            case .settings:   return "slider.horizontal.3"
            case .command:    return "command"
            }
        }
        var title: String {
            switch self {
            case .looks:      return "Looks"
            case .sand:       return "Sand"
            case .settings:   return "Settings"
            case .command:    return "Command palette"
            }
        }
    }
    @FocusState private var focused: Bool
    @Environment(\.palette) private var pal
    @Environment(\.ink) private var ink
    @Environment(\.openWindow) private var openWindow
    @Environment(AppStore.self) private var appStore: AppStore?
    @Environment(DesignStore.self) private var designStore: DesignStore?
    @Environment(InspectorStore.self) private var inspectorStore: InspectorStore?
    @Environment(\.runUIAction) private var runUIAction
    private var sidebarVisible: Bool { appStore?.state.sidebarVisible ?? true }
    private var showGrid: Bool { designStore?.tokens.inspector.showGrid ?? false }
    @AppStorage("gridMargin") private var gridMargin = 20.0
    @AppStorage("gridCols") private var gridCols = 9
    @AppStorage("gridGutter") private var gridGutter = 16.0
    @AppStorage("gridRows") private var gridRows = 8
    @AppStorage("gridBaseline") private var gridBaseline = 12.0
    @AppStorage("headerHeight") private var headerHeight = 68.0
    /// Global palette shift (degrees) — retints every UI colour at once.
    @AppStorage("paletteShift") private var paletteShift = 0.0

    private var suggestions: [Command] {
        guard question.hasPrefix("/") else { return [] }
        let token = question.dropFirst()
        if token.contains(" ") { return [] }
        return CommandRegistry.all(debug: engine.debugMode)
            .filter { $0.isSlash && (token.isEmpty || ($0.slash?.hasPrefix(token.lowercased()) ?? false)) }
    }

    var body: some View {
        let _ = Perf.count("chat.body")
        VStack(spacing: 0) {
            transcript.frame(maxHeight: .infinity)
            if !suggestions.isEmpty { suggestionList }
            if !engine.online { offlineBanner }
            composer
                .background(
                    GeometryReader { g in
                        Color.clear
                            .onAppear { composerH = g.size.height }
                            .onChange(of: g.size.height) { _, h in composerH = h }
                    }
                )
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .coordinateSpace(name: "mentat.window")
        .frame(minWidth: compact ? 400 : 640, minHeight: compact ? 360 : 520)
        .background(
            GeometryReader { g in
                Color.clear
                    .onAppear { engine.contentSize = g.size }
                    .onChange(of: g.size) { _, s in engine.contentSize = s }
            }
        )
        // the titlebar band, so the grid clears the traffic lights (no clipping)
        .background(TopInsetReader { engine.topInset = $0 })
        // no column-feather grid behind the text: the chat reads as a plain
        // single column, not a design armature.
        // arrow keys page the clicked answer (unless a text field is editing)
        .background(ArrowKeyMonitor(engine: engine))
        // overlays float ABOVE the page and never influence its layout
        .overlay { if showGrid && !compact { GridOverlay(windowSize: engine.windowSize) } }
        // dismiss catcher sits BELOW the hero layer, so the menu circle (in the
        // hero layer) stays clickable while clicks elsewhere close the menu
        .overlay(alignment: .topLeading) {
            if showMenu && !compact {
                Color.black.opacity(0.001).ignoresSafeArea()
                    .onTapGesture { withAnimation(Anim.snappy) { showMenu = false } }
            }
        }
        .overlay(alignment: .topLeading) { if !compact { heroLayer.ignoresSafeArea(edges: .top) } }
        .overlay(alignment: .topLeading) {
            if showMenu && !compact {
                // Liquid Glass appears/disappears with the system materialize
                // transition (Apple: use it for glass effects added/removed)
                floatingMenu.ignoresSafeArea(edges: .top)
                    .glassMaterialize()
                    .transition(.dropIn)
            }
        }
        // hidden power-user panel, revealed by /debug
        .overlay(alignment: .topTrailing) {
            if engine.debugMode && !compact {
                DeveloperScene(engine: engine) {
                    withAnimation(Anim.snappy) { engine.debugMode = false }
                }
                .padding(.top, 64)
                .padding(.trailing, CGFloat(gridMargin))
                .glassMaterialize()
                .transition(.dropIn)
            }
        }
        .animation(Anim.smooth, value: engine.colorTheme)
        .task {
            await engine.ensureEngine()
            await engine.loadSettings()
            focused = true
        }
        .sheet(isPresented: $showPalette) {
            CommandPalette(debugMode: engine.debugMode) { command in
                showPalette = false
                switch command.kind {
                case .ui(let action):
                    runUIAction(action)
                case .slash(let s):
                    if s == "settings" { showMenu = true; menuPanel = .settings }
                    else { question = "/\(s) "; focused = true }
                }
            }
        }
        .background(
            // Esc dismisses the topmost floating layer (reader → palette → menu → debug).
            Button("Dismiss") {
                if engine.sourceReaderOpen { engine.closeSource() }
                else if showPalette { showPalette = false }
                else if showMenu { withAnimation(Anim.snappy) { showMenu = false } }
                else if engine.debugMode { withAnimation(Anim.snappy) { engine.debugMode = false } }
            }
            .keyboardShortcut(.cancelAction)
            .opacity(0)
        )
        .background(
            // ⌘K opens the command palette.
            Button("Command palette") { showPalette = true }
                .keyboardShortcut("k", modifiers: .command)
                .opacity(0)
        )
        .overlay {
            if engine.sourceReaderOpen {
                SourceReader(engine: engine)
            }
        }
    }

    private func chip(_ system: String, help: String, action: @escaping () -> Void) -> some View {
        ChipButton(system: system, help: help, color: engine.text(.center), action: action)
    }

    private var trailingControls: some View {
        HStack(spacing: 7) {
            Spacer()
        }
    }

    /// No bar — the wordmark, status and small toggles float straight on the
    /// photo, with a legibility shadow that adapts to the mode.
    /// Horizontal centre of grid column `k`, relative to the header's content
    /// area (i.e. inside the margins). Used to place the settings circle on C7.
    private func headerColumnCenter(_ k: Int) -> CGFloat {
        let g = CGFloat(gridGutter), m = CGFloat(gridMargin)
        let n = max(1, gridCols)
        let contentW = max(200, engine.contentSize.width - 2 * m)
        let colW = max(2, (contentW - g * CGFloat(n - 1)) / CGFloat(n))
        return CGFloat(k - 1) * (colW + g) + colW / 2
    }

    /// Width of one column inside the margins.
    private func headerColumnWidth() -> CGFloat {
        let g = CGFloat(gridGutter), m = CGFloat(gridMargin)
        let n = max(1, gridCols)
        let contentW = max(200, engine.contentSize.width - 2 * m)
        return max(2, (contentW - g * CGFloat(n - 1)) / CGFloat(n))
    }

    /// Leading edge of grid column `k`, relative to the header's content area.
    private func headerColumnLeading(_ k: Int) -> CGFloat {
        headerColumnCenter(k) - headerColumnWidth() / 2
    }

    /// Absolute x (overlay coords, margins included) of column `k`'s centre.
    private func columnCenterX(_ k: Int) -> CGFloat {
        CGFloat(gridMargin) + headerColumnCenter(k)
    }

    /// Column nearest the page centre, so centred text lands on a column, never a gutter.
    private var middleColumn: Int { max(1, min(gridCols, Int((Double(gridCols) / 2).rounded()))) }

    private var appearance: AppTheme { appStore?.appearance ?? .fallback }
    private func cycleTheme() { runUIAction(.cycleAppearance) }

    /// Chrome palette for the right-hand rail + panels, sampled from the art
    /// behind them — the same language the history rail uses on the left.
    private var chrome: ChromePalette { ChromePalette(engine, .right) }

    private var menuSections: [(String, [SettingSpec])] {
        SettingSection.group(engine.settingsSpec) { SettingSpec.primaryKeys.contains($0.key) }
    }

    private func menuRow(_ title: String, symbol: String, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: PanelGrid.gap(gridGutter)) {
                Image(systemName: symbol)
                    .font(.system(size: TypeScale.body, weight: .semibold))
                    .frame(width: 28, height: 28)
                    .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 9, style: .continuous))
                    .overlay(RoundedRectangle(cornerRadius: 9, style: .continuous)
                        .stroke(chrome.dim.opacity(0.35), lineWidth: 1))
                Text(title).lineLimit(1)
                Spacer()
                Image(systemName: "chevron.right")
                    .font(.system(size: TypeScale.caption, weight: .bold))
                    .foregroundStyle(chrome.dim.opacity(0.6))
            }
            .font(.system(size: TypeScale.bodyMono, weight: .medium))
            .foregroundStyle(chrome.ink)
            .padding(.vertical, 5)
            .padding(.horizontal, 6)
            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous)
                .stroke(Color.white.opacity(pal.isDark ? 0.10 : 0.22), lineWidth: 1)
                .allowsHitTesting(false))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    /// The hamburger's menu: a thin rail of icons; tapping one opens that
    /// specific panel beside it, dropping down directly under the circle.
    private var floatingMenu: some View {
        return GeometryReader { geo in
        let W = geo.size.width, H = geo.size.height
        let m = CGFloat(gridMargin), g = CGFloat(gridGutter), n = max(1, gridCols)
        let contentW = max(200, W - 2 * m)
        let colW = max(2, (contentW - g * CGFloat(n - 1)) / CGFloat(n))
        let fullW = 2 * colW
        let railW: CGFloat = 50
        // settings rows need a comfortable reading column; simple panels hug
        // the two-column width but never get so narrow that a row wraps. Every
        // panel is capped at the 55-character measure (plus its own padding) so
        // no row of text ever reads wider than that.
        let panelCap = max(2 * colW,
                           min(W - 2 * m - railW,
                               TextStyle.maxMeasure() + 2 * PanelGrid.pad(gridGutter)))
        let detailW: CGFloat = {
            switch menuPanel {
            case .settings:
                return min(max(2 * colW, 396), panelCap)
            case .sand:
                return min(max(2 * colW, 360), panelCap)
            case .looks:
                return min(max(2 * colW, 360), panelCap)
            default:
                // one-line rows ("Command palette") need a little more room
                // than the raw two-column width
                return min(max(fullW, 216), panelCap)
            }
        }()
        let width = menuPanel == nil ? railW : detailW + railW
        // centre the popup under the hamburger (C`gridCols`, R1), then clamp so
        // it keeps a comfortable inset from both edges
        let menuX = m + CGFloat(max(1, gridCols) - 1) * (colW + g) + colW / 2
        // drop just below the hamburger (top of R1, nudged down when activated)
        let menuTop = (activated ? bandCenterY(H) + 24 : rowTop(1, H) + 48) + engine.topInset
        let inset = max(m, 2 * g)
        let leading = min(max(inset, menuX - width / 2), max(inset, W - width - inset))
        let top = menuTop
        // never taller than 70% of the window, and always clear of the bottom margin
        let maxH = min(max(240, H - top - m), H * 0.70)
        let detailH = menuDetailH > 0 ? min(menuDetailH, maxH) : maxH
        ZStack(alignment: .topLeading) {
            HStack(alignment: .top, spacing: 0) {
                if let panel = menuPanel {
                    // hug the panel's content; scroll only when it can't fit
                    ScrollView {
                        menuDetailBody(panel)
                            .background(GeometryReader { gp in
                                Color.clear.preference(key: MenuHeightKey.self, value: gp.size.height)
                            })
                    }
                    .softScrollEdges()
                    .frame(width: detailW, alignment: .topLeading)
                    .frame(height: detailH)
                    .onPreferenceChange(MenuHeightKey.self) { menuDetailH = $0 }
                    // each panel swaps in with a Liquid-Glass materialise
                    .transition(.asymmetric(
                        insertion: .opacity.combined(with: .move(edge: .trailing)),
                        removal: .opacity))
                    Divider().overlay(chrome.dim.opacity(0.3)).frame(height: detailH)
                }
                menuRail.frame(width: railW)
            }
            .animation(Anim.snappy, value: menuPanel)
            .glassPanel(corner: PanelGrid.radius(gridGutter) + 6)
            .offset(x: leading, y: top)
            .task { await engine.loadSettings() }
        }
        }
    }

    /// The vertical strip of icon buttons. Appearance is a one-tap toggle
    /// (Hue ↔ Mono) rather than a panel — it only has two states.
    private var menuRail: some View {
        VStack(spacing: 6) {
            // Inspector lives here now (folded out of the header): one tap toggles
            // the trailing pane, highlighted while it's open.
            CircleIconButton(
                system: "wrench.and.screwdriver",
                help: (inspectorStore?.visible ?? false) ? "Hide inspector" : "Show inspector",
                diameter: ChromeShape.circle,
                active: inspectorStore?.visible ?? false,
                tint: railAccent
            ) {
                withAnimation(Anim.snappy) { inspectorStore?.toggle() }
            }
            CircleIconButton(
                system: "circle.lefthalf.filled",
                help: "Appearance: \(appearance.label) — click to switch (Hue ↔ Mono)",
                diameter: ChromeShape.circle,
                tint: railAccent
            ) {
                withAnimation(Anim.snappy) { cycleTheme() }
            }
            ForEach(MenuPanel.allCases) { p in
                CircleIconButton(
                    system: p.symbol,
                    help: p.title,
                    diameter: ChromeShape.circle,
                    active: menuPanel == p,
                    tint: railAccent
                ) {
                    withAnimation(Anim.snappy) { menuPanel = (menuPanel == p ? nil : p) }
                }
            }
        }
        .animation(Anim.snappy, value: menuPanel)
        .padding(.vertical, 8).padding(.horizontal, 6)
    }

    @ViewBuilder private func menuDetailBody(_ panel: MenuPanel) -> some View {
        VStack(alignment: .leading, spacing: PanelGrid.gap(gridGutter)) {
                HStack(spacing: 6) {
                    Button {
                        withAnimation(Anim.snappy) { menuPanel = nil }
                    } label: {
                        Image(systemName: "chevron.left")
                            .font(.system(size: TypeScale.label, weight: .semibold))
                            .foregroundStyle(chrome.ink.opacity(0.85))
                            .contentShape(Rectangle())
                    }
                    .glassControl(.small, shape: .circle)
                    .help("Back to menu")
                    .accessibilityLabel("Back to menu")
                    Text(panel.title.uppercased())
                        .font(.caption2).tracking(1).foregroundStyle(chrome.accent)
                }
                switch panel {
                case .looks:
                    DesignStudioPanel()
                case .sand:
                    SandPanel()
                case .settings:
                    settingsSections
                case .command:
                    menuRow("Command palette", symbol: "command") { showMenu = false; showPalette = true }
                }
            }
            .padding(PanelGrid.pad(gridGutter))
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var settingsSections: some View {
        VStack(alignment: .leading, spacing: PanelGrid.gap(gridGutter) * 1.6) {
            // Design tokens — the same data the UI renders from.
            VStack(alignment: .leading, spacing: PanelGrid.gap(gridGutter) * 0.9) {
                Text("DESIGN")
                    .font(.system(size: TypeScale.caption, weight: .semibold))
                    .tracking(1.1)
                    .foregroundStyle(chrome.ink.opacity(0.92))
                    .padding(.horizontal, 13).padding(.vertical, 6)
                    .background(.ultraThinMaterial, in: Capsule(style: .continuous))
                    .overlay(Capsule(style: .continuous).stroke(
                        Color.white.opacity(chrome.isLight ? 0.5 : 0.14), lineWidth: 1))
                DesignPanel()
                    .foregroundStyle(chrome.ink)
            }
            ForEach(menuSections, id: \.0) { section, specs in
                VStack(alignment: .leading, spacing: PanelGrid.gap(gridGutter) * 0.9) {
                    // section title as a small floating chip (the "Stress Relief"
                    // pill from the reference), rather than a bare label
                    Text(section.uppercased())
                        .font(.system(size: TypeScale.caption, weight: .semibold))
                        .tracking(1.1)
                        .foregroundStyle(chrome.ink.opacity(0.92))
                        .lineLimit(1)
                        .padding(.horizontal, 13).padding(.vertical, 6)
                        .background(.ultraThinMaterial, in: Capsule(style: .continuous))
                        .overlay(Capsule(style: .continuous).stroke(
                            Color.white.opacity(chrome.isLight ? 0.5 : 0.14), lineWidth: 1))
                        .shadow(color: .black.opacity(chrome.isLight ? 0.12 : 0.30), radius: 6, y: 3)
                    // each setting floats as its own glass pill
                    ForEach(specs) { spec in
                        SettingRow(engine: engine, spec: spec, chrome: chrome)
                    }
                }
            }
        }
        .padding(.top, PanelGrid.gap(gridGutter) * 0.5)
    }

    private var activated: Bool { !question.isEmpty || !engine.messages.isEmpty }
    /// Extra space below the margin before page content begins: the masthead
    /// row plus a two-line gap, so the fade up toward the title finishes two
    /// grid lines before it and the first bubble sits on the grid's top edge.
    private var gridContentInset: CGFloat {
        activated ? wordmarkBandH + 2 * CGFloat(gridBaseline) : 0
    }
    /// Absolute y (from the top of the page) of the grid's top edge.
    private var gridTopInset: CGFloat {
        engine.topInset + CGFloat(gridMargin) + gridContentInset
    }
    /// Bottom edge of the title/masthead row, in page coordinates.
    private var titleBottomY: CGFloat { engine.topInset + CGFloat(gridMargin) + wordmarkBandH }
    /// Height of the masthead grid row that holds the wordmark + menu buttons.
    private let wordmarkBandH: CGFloat = 56
    /// Vertical centre of that masthead row, in layer coordinates.
    private func bandCenterY(_ H: CGFloat) -> CGFloat { rowTop(1, H) + wordmarkBandH / 2 }

    private func rowMetrics(_ H: CGFloat) -> (m: CGFloat, rowH: CGFloat) {
        let m = CGFloat(gridMargin), g = CGFloat(gridGutter), n = max(1, gridRows)
        let contentH = max(20, H - 2 * m)
        let rowH = max(2, (contentH - g * CGFloat(n - 1)) / CGFloat(n))
        return (m, rowH)
    }
    private func rowTop(_ k: Int, _ H: CGFloat) -> CGFloat {
        let (m, rowH) = rowMetrics(H)
        return m + CGFloat(k - 1) * (rowH + CGFloat(gridGutter))
    }
    private func rowCenter(_ k: Int, _ H: CGFloat) -> CGFloat {
        let (m, rowH) = rowMetrics(H)
        return m + CGFloat(k - 1) * (rowH + CGFloat(gridGutter)) + rowH / 2
    }

    /// The floating chrome is **white**: a plain white ring/glyph at rest, and a
    /// white fill with a black glyph when active. No sampled ink — the surface
    /// system owns legibility, so these read the same in every look.
    private func discFill(_ region: BgRegion) -> Color { .white }
    private func discContent(_ region: BgRegion) -> Color { .black }

    /// The rail's accent is white too.
    private var railAccent: Color { .white }
    private var railInk: Color { chrome.ink }

    private var menuCircle: some View {
        let fill = discFill(.right)
        let content = discContent(.right)
        let on = showMenu
        return ZStack {
            // no plate at rest — just a thin ring; fills in when open
            Circle().fill(on ? fill : Color.clear)
            Circle().stroke(fill.opacity(on ? 0.9 : 0.55), lineWidth: 1)
            Image(systemName: on ? "xmark" : "line.3.horizontal")
                .font(.system(size: TypeScale.label, weight: .bold))
                .contentTransition(.symbolEffect(.replace))
                .foregroundStyle(on ? content : fill)
        }
        .frame(width: 26, height: 26)
        // larger hit target than the visible circle so direct clicks always land
        .frame(width: 40, height: 40)
        .contentShape(Circle())
        .scaleEffect(on ? 1.05 : 1)
        .animation(Anim.snappy, value: on)
        // a tap gesture (not a Button) so the parent DragGesture can win a drag
        .onTapGesture { withAnimation(Anim.snappy) { showMenu.toggle() } }
        .help("Menu")
        .accessibilityLabel("Menu")
    }

    /// Floating chrome: the wordmark and the two header controls, laid on the
    /// grid. Static (no dragging).
    private var heroLayer: some View {
        GeometryReader { geo in
            let W = geo.size.width, H = geo.size.height
            let gm = CGFloat(gridMargin), gg = CGFloat(gridGutter), gn = max(1, gridCols)
            let contentW = max(200, W - 2 * gm)
            let colW = max(2, (contentW - gg * CGFloat(gn - 1)) / CGFloat(gn))
            let titleTop = (activated ? rowTop(1, H) : rowTop(4, H)) + engine.topInset
            let btnTop = (activated ? bandCenterY(H) - 20 : rowTop(1, H)) + engine.topInset
            let menuX = gm + CGFloat(gn - 1) * (colW + gg) + colW / 2
            let sidebarX = gm + colW / 2
            let titleInk = activated ? ink.top : ink(.center)
            // No halo/glow: the wordmark is brand sand, the subtitle takes the
            // adaptive ink. Separation comes from the surface, never a shadow.
            ZStack(alignment: .topLeading) {
                VStack(spacing: 12) {
                    Text("mentat")
                        .font(.custom("Quicksand-Light", size: 46))
                        .tracking(14)
                        .foregroundStyle(Color(nsColor: TextInk.brandMark(isLight: engine.colorTheme.isLight)))
                    Text("what wisdom do you seek?")
                        .font(.system(size: 15, design: .monospaced))
                        .foregroundStyle(titleInk)
                        .opacity(activated ? 0 : 1)
                }
                .fixedSize()
                .frame(maxWidth: .infinity, alignment: .center)
                .offset(y: titleTop)
                .allowsHitTesting(false)
                sidebarToggle
                    .frame(maxWidth: .infinity, alignment: .center)
                    .offset(x: sidebarX - W / 2, y: btnTop)
                menuCircle
                    .frame(maxWidth: .infinity, alignment: .center)
                    .offset(x: menuX - W / 2, y: btnTop)
            }
            .animation(Anim.smooth, value: activated)
            .animation(Anim.smooth, value: sidebarVisible)
        }
    }

    private var sidebarToggle: some View {
        let fill = discFill(.left)
        let content = discContent(.left)
        let on = sidebarVisible
        return ZStack {
            // thin ring; fills with the palette colour (Hue) or black/white (Sand)
            Circle().fill(on ? fill : Color.clear)
            Circle().stroke(fill.opacity(on ? 0.9 : 0.55), lineWidth: 1)
            Image(systemName: "sidebar.left")
                .font(.system(size: TypeScale.label, weight: .bold))
                .foregroundStyle(on ? content : fill)
        }
        .frame(width: 26, height: 26)
        // match the hamburger circle's 40pt hit frame so the two toggles
        // share the exact same vertical centre
        .frame(width: 40, height: 40)
        .contentShape(Circle())
        .scaleEffect(on ? 1.05 : 1)
        .animation(Anim.snappy, value: on)
        .onTapGesture { runUIAction(.toggleSidebar) }
        .help(sidebarVisible ? "Hide history" : "Show history")
        .accessibilityLabel(sidebarVisible ? "Hide history" : "Show history")
    }

    private var header: some View {
        ZStack {
            HStack(spacing: 7) {
                // the sidebar control lives in the hero layer and the
                // hamburger's icon rail holds the rest
                Spacer()
            }
            Group {
                // container spacing < HStack spacing, else the glass blobs
                // merge together at rest (per Apple's guidance)
                GlassEffectContainer(spacing: 3) { trailingControls }
            }
            .glassMaterialize()
        }
        // floating (no bar) but grid-aligned: spans columns 1–12
        .padding(.horizontal, compact ? 12 : CGFloat(gridMargin))
        .padding(.top, compact ? 12 : 28)
        .padding(.bottom, 8)
    }

    private var transcript: some View {
        GeometryReader { geo in
        // soft edges top and bottom: instead of a hard clip line, text rising
        // toward the wordmark — or settling toward the composer — fades smoothly
        // to nothing. The top fade is pinned to the grid: it is fully transparent
        // by the title's bottom edge and fully opaque at the grid's top, so the
        // fade finishes two grid lines before it can reach the title. The bottom
        // fade lands on the grid's last line.
        let H = max(1, geo.size.height)
        let fade = min(0.32, 84 / H)
        let clearLoc = min(0.6, max(0, titleBottomY / H))
        let opaqueLoc = max(clearLoc, min(0.85, max(0, gridTopInset / H)))
        let bottomStart = max(opaqueLoc, 1 - fade)
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 16) {
                    ForEach(engine.messages) { m in
                        MessageRow(message: m, engine: engine)
                            .id(m.id)
                            .transition(.scale(scale: 0.97).combined(with: .opacity))
                    }
                    Color.clear.frame(height: 1).id("bottom")
                    // Float room: a clicked message can scroll all the way to the
                    // centre even when it is the last one (nothing below it). It
                    // is invisible at rest because auto-follow anchors to
                    // "bottom", which sits above this spacer.
                    Color.clear.frame(height: max(0, H * 0.5))
                }
                // the first bubble starts exactly on the grid's top row
                .padding(.horizontal, compact ? 12 : CGFloat(gridMargin))
                .padding(.top, compact ? 12 : gridTopInset)
                .padding(.bottom, compact ? 12 : 28)
                .frame(maxWidth: .infinity, alignment: .leading)
                .animation(Anim.snappy, value: engine.messages.count)
            }
            .softScrollEdges()
            .mask(
                LinearGradient(stops: [
                    .init(color: .black.opacity(0), location: 0),
                    .init(color: .black.opacity(0), location: clearLoc),
                    .init(color: .black, location: opaqueLoc),
                    .init(color: .black, location: bottomStart),
                    .init(color: .black.opacity(0), location: 1)
                ], startPoint: .top, endPoint: .bottom)
            )
            // Pin to the bottom while content streams: the modern anchor follows
            // growth without us scrolling on every token (the old per-token
            // scrollTo was the main streaming stutter). Apple "SwiftUI — Scroll
            // views: defaultScrollAnchor".
            .defaultScrollAnchor(.bottom)
            // Reading imparts a light shear, proportional to the flick. The
            // threshold keeps it to real movements, not jitter.
            .onScrollGeometryChange(for: CGFloat.self) { $0.contentOffset.y } action: { old, new in
                let dy = new - old
                if abs(dy) > 2 { sandMotion?.emit(.scroll(dy: Double(dy))) }
            }
            // Jump on a new turn, but defer to the next runloop so a just
            // appended turn is laid out before we scroll to it (scrolling in
            // the same update silently no-ops and the answer lands off-screen)
            .onChange(of: engine.messages.count) { _, _ in
                DispatchQueue.main.async {
                    withAnimation(Anim.smooth) { proxy.scrollTo("bottom", anchor: .bottom) }
                }
            }
            // a reader paging through an answer keeps it centred instead of
            // letting the page animation drift it off-screen
            .onChange(of: engine.centerRequest) { _, id in
                guard let id else { return }
                DispatchQueue.main.async {
                    withAnimation(Anim.smooth) { proxy.scrollTo(id, anchor: .center) }
                    engine.centerRequest = nil
                }
            }
        }
        }
        // share the grid/hero coordinate space: the layer ignores the top safe
        // area, so if the transcript doesn't, its content is pushed down by the
        // titlebar inset and the first bubble misses the grid's top line.
        .ignoresSafeArea(edges: .top)
    }

    private var suggestionList: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(suggestions.prefix(8)) { item in
                Button {
                    question = "/\(item.slash ?? "") "
                    focused = true
                } label: {
                    HStack {
                        Text("/\(item.slash ?? "")").foregroundStyle(engine.accentColor(.center)).frame(width: 110, alignment: .leading)
                        Text(item.help).foregroundStyle(pal.textDim)
                        Spacer()
                    }
                    .padding(.horizontal, PanelGrid.gap(gridGutter)).padding(.vertical, PanelGrid.row(gridGutter) * 0.5)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.pressable)
            }
        }
        .surface(corner: PanelGrid.radius(gridGutter))
        .glassMaterialize()
        .padding(.horizontal, compact ? 12 : CGFloat(gridMargin))
    }

    /// Shown above the composer when the engine isn't reachable, so an offline
    /// engine is visible instead of silent.
    private var offlineBanner: some View {
        HStack(spacing: 8) {
            Image(systemName: "bolt.horizontal.circle")
            Text("engine offline")
            Spacer(minLength: 8)
            Button("Retry") { Task { await engine.ensureEngine() } }
                .buttonStyle(.plain)
        }
        .font(.caption)
        .foregroundStyle(engine.dim(.center))
        .padding(.horizontal, 12).padding(.vertical, 8)
        .surface(shape: Capsule(style: .continuous))
        .padding(.horizontal, 16).padding(.bottom, 6)
        .transition(.move(edge: .bottom).combined(with: .opacity))
    }

    private var composer: some View {
        VStack(alignment: .leading, spacing: 6) {
            if !compact && !engine.model.isEmpty {
                ModelPicker(engine: engine)
            }
            attachmentChips
            ZStack(alignment: .topLeading) {
                if question.isEmpty {
                    Text("ask mentat…  (/help · \"count <word>\" or /freq to count)")
                        .font(.system(size: 14))
                        .foregroundStyle(engine.dim(.right))
                        .padding(.leading, 44).padding(.trailing, 60).padding(.top, 10)
                        .allowsHitTesting(false)
                }
                ComposerTextView(text: $question, height: $inputHeight, maxHeight: 200,
                                 onSend: send,
                                 onFiles: { urls in for u in urls { engine.addAttachment(u) } },
                                 onPaste: handlePaste)
                    .padding(.leading, 36)
                    .padding(.trailing, 52)
                    .frame(height: inputHeight)
                    .frame(maxWidth: TextStyle.maxMeasure() + 52 + 2 * PanelGrid.row(gridGutter),
                           alignment: .leading)
            }
            .liquid(corner: PanelGrid.radius(gridGutter))
            // "+" attach (leading)
            .overlay(alignment: .leading) {
                Button { showImporter = true } label: {
                    Image(systemName: "plus")
                        .font(.system(size: TypeScale.emphasis, weight: .semibold))
                        .frame(width: 32, height: 32)
                        .foregroundStyle(engine.colorTheme.accent)
                }
                .buttonStyle(.plain)
                .padding(.leading, 6)
                .help("Attach a file")
                .accessibilityLabel("Attach a file")
            }
            // send / stop (trailing)
            .overlay(alignment: .trailing) {
                Button(action: send) {
                    Image(systemName: engine.busy ? "stop.fill" : "arrow.up")
                        .font(.system(size: TypeScale.emphasis, weight: .bold))
                        .contentTransition(.symbolEffect(.replace))
                        .symbolEffect(.bounce, options: .speed(1.8), value: engine.messages.count)
                        .frame(width: 32, height: 32)
                        .foregroundStyle(
                            canSend ? engine.colorTheme.onAccent : engine.dim(.right))
                        .background {
                            if canSend {
                                Circle().fill(engine.colorTheme.accent)
                            } else {
                                Circle().fill(.ultraThinMaterial)
                            }
                        }
                }
                .buttonStyle(.pressable)
                .animation(Anim.snappy, value: engine.busy)
                .animation(Anim.snappy, value: canSend)
                .padding(.trailing, 6)
                .disabled(!canSend)
                .help(engine.busy ? "Stop" : "Send")
                .accessibilityLabel(engine.busy ? "Stop" : "Send")
            }
        }
        // one Liquid Glass container for the composer's glass cluster
        .glassContainer(spacing: 6)
        .padding(.horizontal, compact ? 12 : CGFloat(gridMargin))
        .padding(.top, 8)
        .padding(.bottom, compact ? 10 : 18)
        .overlay {
            if dropTargeted {
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .stroke(engine.colorTheme.accent, lineWidth: 2)
                    .background(engine.colorTheme.accent.opacity(0.08),
                                in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                    .allowsHitTesting(false)
            }
        }
        .onDrop(of: [UTType.fileURL], isTargeted: $dropTargeted) { providers in
            for p in providers {
                _ = p.loadObject(ofClass: URL.self) { url, _ in
                    if let url { Task { @MainActor in engine.addAttachment(url) } }
                }
            }
            return true
        }
        .fileImporter(isPresented: $showImporter, allowedContentTypes: [.item],
                      allowsMultipleSelection: true) { result in
            if case .success(let urls) = result {
                for u in urls { engine.addAttachment(u) }
            }
        }
    }

    /// Staged file chips above the input (name · size · ✕), like Qwen/DeepSeek/Kimi.
    @ViewBuilder private var attachmentChips: some View {
        if !engine.pendingAttachments.isEmpty {
            FlowRow(spacing: 6) {
                ForEach(engine.pendingAttachments) { a in
                    HStack(spacing: 6) {
                        Image(systemName: "doc.text")
                            .font(.system(size: TypeScale.micro, weight: .semibold))
                        Text(a.label).font(.system(size: TypeScale.meta)).lineLimit(1)
                        Button { engine.removeAttachment(a.id) } label: {
                            Image(systemName: "xmark.circle.fill")
                                .font(.system(size: TypeScale.meta))
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("Remove attachment")
                    }
                    .foregroundStyle(engine.dim(.right))
                    .padding(.horizontal, 9).padding(.vertical, 4)
                    .background(.ultraThinMaterial, in: Capsule())
                    .overlay(Capsule().stroke(engine.dim(.right).opacity(0.25), lineWidth: 1))
                }
            }
            .padding(.horizontal, 4)
        }
    }

    private var canSend: Bool {
        engine.busy || !question.trimmingCharacters(in: .whitespaces).isEmpty
    }

    private func send() {
        if engine.busy { engine.stop(); return }
        let q = question.trimmingCharacters(in: .whitespacesAndNewlines)
        // Hidden developer escape hatch: reveal / hide the niche-mechanics panel.
        if q == "/debug" || q == "/debug on" {
            question = ""
            withAnimation(Anim.snappy) { engine.debugMode = true }
            return
        }
        if q == "/debug off" {
            question = ""
            withAnimation(Anim.snappy) { engine.debugMode = false }
            return
        }
        if q == "/grid", engine.debugMode {
            question = ""
            designStore?.tokens.inspector.showGrid.toggle()
            return
        }
        question = ""
        engine.send(q)
    }

    /// Qwen/Kimi behaviour: a large paste becomes a `.txt` attachment instead of
    /// flooding the input. Short pastes insert normally.
    private func handlePaste(_ s: String) -> Bool {
        let long = s.count > 2000 || s.split(separator: "\n").count > 15
        guard long, let url = writePastedText(s) else { return false }
        engine.addAttachment(url)
        return true
    }

    private func writePastedText(_ s: String) -> URL? {
        let dir = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Everything/mentat/app/mentat2_data/attachments")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let url = dir.appendingPathComponent("pasted text \(Int(Date().timeIntervalSince1970)).txt")
        do {
            try s.write(to: url, atomically: true, encoding: .utf8)
            return url
        } catch {
            return nil
        }
    }
}

// Developer scene moved to Screens/Developer/DeveloperScene.swift.




// Settings panels moved to Screens/Menu/Settings.swift.


// ConversationCard moved to Screens/Sidebar/ConversationCard.swift.

/// Turn a timestamp into a short relative string ("2h ago"), falling back to the
/// raw value when it can't be parsed.
func relativeDate(_ raw: String) -> String {
    guard !raw.isEmpty else { return "" }
    let df = DateFormatter()
    df.locale = Locale(identifier: "en_US_POSIX")
    for fmt in ["yyyy-MM-dd HH:mm:ss", "yyyy-MM-dd'T'HH:mm:ss", "yyyy-MM-dd HH:mm", "yyyy-MM-dd"] {
        df.dateFormat = fmt
        if let d = df.date(from: raw) {
            let r = RelativeDateTimeFormatter()
            r.unitsStyle = .abbreviated
            return r.localizedString(for: d, relativeTo: Date())
        }
    }
    return raw
}

struct RootView: View {
    var engine: Engine
    @Environment(\.palette) private var pal
    @AppStorage("layoutMode") private var layoutMode = false
    @State private var layoutStore = LayoutGridStore()
    /// Drives the sand surface. Held here but **not read** in `RootView.body`, so
    /// pointer/scroll events never invalidate the transcript.
    @State private var sandMotion = SandMotionStore()
    /// The detail's frame measured in global space — the sand canvas fills it,
    /// so the pointer maps to the pixel under the cursor's tip.
    @State private var sandFrame: CGRect = .zero
    @State private var designStore: DesignStore
    @State private var inspectorStore: InspectorStore
    @State private var appStore: AppStore
    @State private var slotRegistry: SlotRegistry

    init(engine: Engine) {
        self.engine = engine
        // Register the Developer scene's panels before first render (slots are
        // observable, but registering up front keeps the seam honest).
        let registry = SlotRegistry()
        registry.register(.developerPanels) { EngineInfoPanel(engine: engine) }
        _slotRegistry = State(initialValue: registry)
        let design = DesignStore()
        let inspector = InspectorStore()
        _designStore = State(initialValue: design)
        _inspectorStore = State(initialValue: inspector)
        _appStore = State(initialValue: AppStore(engine: engine, design: design, inspector: inspector))
        // the surface look is the colour authority — seed it before first render
        engine.surfaceLook = design.tokens.look
    }

    /// The history panel is a solid sheet with ink that always contrasts it —
    /// the look's own surface, never a photo sampled behind it.
    private var isLightTheme: Bool { engine.colorTheme.isLight }
    private var panel: Color {
        engine.colorTheme.surface.opacity(0.94)
    }
    private var panelInk: Color {
        engine.colorTheme.ink
    }
    private var panelDim: Color {
        engine.colorTheme.inkDim
    }
    private var panelAccent: Color {
        engine.colorTheme.accent
    }

    // MARK: history — Siri-inspired pin / find
    /// Conversations the reader pinned, kept as newline-separated ids in the UI
    /// layer only (the engine/store never sees pins, so base behaviour is
    /// untouched).
    @AppStorage("pinnedConversations") private var pinnedRaw = ""
    @AppStorage("historyLayout") private var historyLayout = "grid"
    @State private var findText = ""
    @State private var renameTarget: Conversation? = nil
    @State private var renameText = ""

    private var pinnedSet: Set<String> {
        Set(pinnedRaw.split(separator: "\n").map(String.init))
    }
    private func togglePin(_ id: String) {
        var ids = pinnedRaw.split(separator: "\n").map(String.init)
        if let i = ids.firstIndex(of: id) { ids.remove(at: i) } else { ids.append(id) }
        pinnedRaw = ids.joined(separator: "\n")
    }
    /// Newest first, then filtered by the Find field.
    private var historyMatches: [Conversation] {
        let sorted = engine.conversations.sorted { $0.last_ts > $1.last_ts }
        guard !findText.isEmpty else { return sorted }
        return sorted.filter { $0.label.localizedCaseInsensitiveContains(findText) }
    }
    /// While searching everything is one list; otherwise pinned rows stay on top
    /// (Siri/Mail convention).
    private var searching: Bool { !findText.isEmpty }
    private var pinnedList: [Conversation] {
        guard !searching else { return [] }
        // Pinned order follows the stored id order rather than recency, so a
        // future drag-to-reorder only has to write this string.
        let byID = Dictionary(historyMatches.map { ($0.conv, $0) }, uniquingKeysWith: { a, _ in a })
        return pinnedRaw.split(separator: "\n").map(String.init).compactMap { byID[$0] }
    }
    private var recentList: [Conversation] {
        searching ? historyMatches : historyMatches.filter { !pinnedSet.contains($0.conv) }
    }

    /// Pinned section. Drag-to-reorder is parked (native reorder never engaged in
    /// the custom sidebar; recoverable from git history), so the pinned rows are
    /// plain history cards for now.
    @ViewBuilder private func pinnedSection(_ style: ConversationCard.Style) -> some View {
        sectionHeader("Pinned")
        if style == .row {
            LazyVStack(alignment: .leading, spacing: 8) {
                ForEach(pinnedList) { c in historyCard(c, style) }
            }
        } else {
            StaggeredGrid(columns: 2, spacing: 8) {
                ForEach(pinnedList) { c in historyCard(c, style) }
            }
        }
    }

    private func sectionHeader(_ title: String) -> some View {
        Text(title)
            .font(.caption.weight(.semibold)).foregroundStyle(panelDim)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 12).padding(.vertical, 6)
    }

    private func historyCard(_ c: Conversation, _ style: ConversationCard.Style) -> some View {
        ConversationCard(title: c.label,
                         date: relativeDate(c.last_ts),
                         turns: c.count,
                         selected: engine.currentConv == c.conv,
                         pinned: pinnedSet.contains(c.conv),
                         style: style,
                         ink: panelInk,
                         dim: panelDim,
                         accent: panelAccent,
                         isLight: isLightTheme,
                         onTap: { Task { await engine.openConversation(c.conv) } },
                         onPin: { withAnimation(Anim.snappy) { togglePin(c.conv) } },
                         onEdit: { renameText = c.label; renameTarget = c },
                         onDelete: { Task { await engine.deleteConversation(c.conv) } })
    }

    private var findField: some View {
        HStack(spacing: 6) {
            Image(systemName: "magnifyingglass")
                .font(.system(size: TypeScale.label, weight: .semibold))
                .foregroundStyle(panelDim)
            TextField("Find", text: $findText)
                .textFieldStyle(.plain)
                .font(.system(size: TypeScale.body))
                .foregroundStyle(panelInk)
            if searching {
                Button { findText = "" } label: {
                    Image(systemName: "xmark.circle.fill")
                        .font(.system(size: TypeScale.label))
                        .foregroundStyle(panelDim)
                }
                .buttonStyle(.plain)
                .help("Clear")
                .accessibilityLabel("Clear find")
            }
        }
        .padding(.horizontal, 9).padding(.vertical, 6)
        .surface(shape: Capsule(style: .continuous))
        .overlay(Capsule(style: .continuous).stroke(panelDim.opacity(0.28), lineWidth: 1))
    }

    /// Find plus the Siri-style "as List / as Grid" switch.
    private var findRow: some View {
        HStack(spacing: 8) {
            findField
            Button {
                withAnimation(Anim.snappy) { historyLayout = historyLayout == "grid" ? "list" : "grid" }
            } label: {
                Image(systemName: historyLayout == "grid" ? "list.bullet" : "square.grid.2x2")
                    .font(.system(size: TypeScale.body, weight: .semibold))
                    .foregroundStyle(panelDim)
                    .frame(width: 28, height: 28)
                    .background(.ultraThinMaterial,
                                in: RoundedRectangle(cornerRadius: 8, style: .continuous))
                    .contentShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            }
            .buttonStyle(.plain)
            .help(historyLayout == "grid" ? "as List" : "as Grid")
            .accessibilityLabel(historyLayout == "grid" ? "Show as list" : "Show as grid")
        }
        .padding(.horizontal, 10).padding(.vertical, 6)
    }

    /// The history body in either mode: a 2-column staggered (masonry) grid, or
    /// the classic single-column list.
    @ViewBuilder private var historyBody: some View {
        historyContent.padding(8)
    }

    @ViewBuilder private var historyContent: some View {
        if historyLayout == "list" {
            LazyVStack(alignment: .leading, spacing: 8) {
                if searching {
                    sectionHeader(recentList.isEmpty ? "No matches" : "Results")
                    ForEach(recentList) { c in historyCard(c, .row) }
                } else {
                    if !pinnedList.isEmpty { pinnedSection(.row) }
                    sectionHeader("Past conversations")
                    ForEach(recentList) { c in historyCard(c, .row) }
                }
            }
        } else {
            VStack(alignment: .leading, spacing: 6) {
                if searching {
                    sectionHeader(recentList.isEmpty ? "No matches" : "Results")
                    StaggeredGrid(columns: 2, spacing: 8) {
                        ForEach(recentList) { c in historyCard(c, .tile) }
                    }
                } else {
                    if !pinnedList.isEmpty { pinnedSection(.tile) }
                    sectionHeader("Past conversations")
                    StaggeredGrid(columns: 2, spacing: 8) {
                        ForEach(recentList) { c in historyCard(c, .tile) }
                    }
                }
            }
        }
    }

    var body: some View {
        NavigationSplitView(columnVisibility: Binding(
            get: { appStore.state.sidebarVisible ? .all : .detailOnly },
            set: { appStore.state.sidebarVisible = ($0 != .detailOnly) }
        )) {
                VStack(spacing: 0) {
                    Button {
                        Task { await engine.newConversation() }
                    } label: {
                        Label("New conversation", systemImage: "plus")
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(10)
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(panelAccent)
                    Divider().overlay(panelDim.opacity(0.22))
                    findRow
                    ScrollView {
                        historyBody
                    }
                    .softScrollEdges()
                    // version history: the build that produced this session, so
                    // a past chat can be dated against the current code
                    Divider().overlay(panelDim.opacity(0.22))
                    Text("build \(engine.buildStamp)")
                        .font(.system(size: TypeScale.micro, design: .monospaced))
                        .foregroundStyle(panelDim)
                        .lineLimit(1)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal, 12).padding(.vertical, 6)
                        .help("Executable build time · source revision")
                }
                .sidebarGlass(solid: panel,
                              tint: engine.colorTheme.surface.opacity(0.55))
                .background(engine.colorTheme.surface)
                .scrollContentBackground(.hidden)
                // Palette/tokens adapt live (observable) — no `.id(theme)` subtree
                // rebuild, which used to hitch the rail on every appearance flip.
                .navigationSplitViewColumnWidth(
                    min: designStore.tokens.metrics.sidebarMin,
                    ideal: designStore.tokens.metrics.sidebarIdeal,
                    max: designStore.tokens.metrics.sidebarMax)
            } detail: {
                ZStack {
                    // The procedural sand is the **Sand** canvas. Every other look
                    // owns its own surface (paper cream, system, mono), so colour
                    // and ink stay paired — no dark ink over a dark shader.
                    if designStore.tokens.sand.enabled, designStore.tokens.look == .sand {
                        // Two amber masses travel the frame and cross-fade to
                        // deep-orange, grain streaming like wind-blown sand —
                        // always moving, nudged by the UI.
                        SandCanvas(
                            style: .sand.merging(designStore.tokens.sand),
                            store: sandMotion,
                            busy: engine.busy)
                    } else {
                        engine.colorTheme.background
                    }
                    // The inspector is an **in-content** trailing pane, not the
                    // native `.inspector`: the system one hosts itself in the
                    // window and forced it to grow when opened. Here the window
                    // never resizes — the reading column just narrows.
                    HStack(spacing: 0) {
                        ChatView(engine: engine)
                            .frame(maxWidth: .infinity, maxHeight: .infinity)
                        if inspectorStore.visible {
                            Rectangle()
                                .fill(engine.colorTheme.border.opacity(0.5))
                                .frame(width: 1)
                            InspectorPane(engine: engine, inspector: inspectorStore)
                                .frame(width: inspectorStore.width)
                                .transition(.move(edge: .trailing).combined(with: .opacity))
                        }
                    }
                }
                .background(GeometryReader { g in
                    Color.clear
                        .onAppear { sandFrame = g.frame(in: .global) }
                        .onChange(of: g.frame(in: .global)) { _, f in sandFrame = f }
                })
                .animation(Anim.snappy, value: inspectorStore.visible)
                .onContinuousHover(coordinateSpace: .global) { phase in
                    // Map the pointer into the detail's frame so the obstacle
                    // sits under the cursor tip.
                    switch phase {
                    case .active(let p):
                        let s = sandFrame.size.width < 2 ? engine.contentSize : sandFrame.size
                        sandMotion.setPointer(CGPoint(x: p.x - sandFrame.minX,
                                                      y: p.y - sandFrame.minY), in: s)
                    case .ended: sandMotion.clearPointer()
                    }
                }
                // Big moves nudge the sand; small ones barely register.
                .onChange(of: engine.messages.count) { _, _ in sandMotion.emit(.send) }
                .onChange(of: engine.busy) { _, b in sandMotion.setBreath(b ? 1 : 0) }
                .onChange(of: inspectorStore.visible) { _, v in
                    sandMotion.emit(.panel(.trailing, open: v))
                }
                .onChange(of: appStore.state.sidebarVisible) { _, v in
                    sandMotion.emit(.panel(.leading, open: v))
                }
                .onChange(of: designStore.tokens.look) { _, _ in sandMotion.emit(.modeChange) }
                .onChange(of: engine.contentSize) { old, new in
                    // ignore the first layout (0 → size): that is not a resize
                    guard old != .zero, new != .zero else { return }
                    sandMotion.emit(.resize(dx: new.width - old.width,
                                            dy: new.height - old.height))
                }
            }
        .environment(layoutStore)
        .environment(designStore)
        .environment(inspectorStore)
        .environment(\.slots, slotRegistry)
        .environment(appStore)
        .environment(\.runUIAction) { action in
            appStore.send(action)
        }
        .environment(\.sandMotion, sandMotion)
        .environment(\.design, designStore.tokens)
        .task { sandMotion.configure(designStore.tokens.sand) }
        .onChange(of: designStore.tokens.sand) { _, t in sandMotion.configure(t) }
        .onChange(of: designStore.tokens.look) { _, look in engine.surfaceLook = look }
        .background(Color.clear)
        .background(
            GeometryReader { g in
                Color.clear
                    .onAppear { engine.windowSize = g.size }
                    .onChange(of: g.size) { _, s in engine.windowSize = s }
            }
        )
        .hideWindowToolbar()      // no system toolbar stacked above the header
        // paint the window/canvas so no system light background shows through
        .background(engine.colorTheme.background)
        .alert("Edit title", isPresented: Binding(
            get: { renameTarget != nil },
            set: { if !$0 { renameTarget = nil } }
        )) {
            TextField("Conversation title", text: $renameText)
            Button("Save") {
                if let t = renameTarget {
                    let title = renameText
                    Task { await engine.renameConversation(t.conv, title) }
                }
                renameTarget = nil
            }
            Button("Cancel", role: .cancel) { renameTarget = nil }
        } message: {
            Text("Rename this conversation.")
        }
        .overlay { if layoutMode { LayoutInstrument(store: layoutStore, isOn: $layoutMode) } }
        // Hide the native traffic lights — the custom header stands alone.
        .overlay(alignment: .topLeading) {
            HideTrafficLights().frame(width: 1, height: 1)
        }
        .background(
            // ⌥⌘G opens the Layout instrument (armature, presets, guides, snapping).
            // Esc closes it, or clears the history find field.
            Button("Layout mode") { layoutMode.toggle() }
                .keyboardShortcut("g", modifiers: [.command, .option])
                .opacity(0)
        )
        .background(
            // ⌘I toggles the right-hand Inspector (citations · source · files · context).
            Button("Inspector") { withAnimation(Anim.snappy) { inspectorStore.toggle() } }
                .keyboardShortcut("i", modifiers: .command)
                .opacity(0)
        )
        .background(
            Button("Dismiss") {
                if layoutMode { withAnimation(Anim.snappy) { layoutMode = false } }
                else if !findText.isEmpty { findText = "" }
            }
            .keyboardShortcut(.cancelAction)
            .opacity(0)
        )
        .task {
            await engine.loadConversations()
        }
        .onChange(of: appStore.state.appearanceRaw) { _, newValue in
            // appearance swap is O(1) from cached data (no re-analysis) and
            // crossfades unless Reduce Motion is on.
            let t = AppTheme(rawValue: newValue) ?? .fallback
            if NSWorkspace.shared.accessibilityDisplayShouldReduceMotion {
                engine.setAppearance(t)
            } else {
                withAnimation(Anim.smooth) { engine.setAppearance(t) }
            }
        }
    }
}
