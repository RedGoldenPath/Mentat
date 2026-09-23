import SwiftUI
import AppKit
import CoreImage
import CoreText
import Observation

// MARK: - Wire models
// Wire + chat models (Citation, AnswerMeta, AskResponse, StreamEvent,
// Conversation, LibraryBook, DocBlock, SettingSpec, ChatRole, ChatMessage,
// PageTurn) now live in Engine/Models.swift.

/// A rounded rectangle that nests concentrically with its container (Apple's
/// "concentric corners" guidance).
struct NestedShape: Shape {
    var radius: CGFloat
    func path(in rect: CGRect) -> Path {
        ConcentricRectangle().path(in: rect)
    }
}

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

/// A sampled patch of the background: brightness + busyness (variance).
struct BgCell {
    let lum: CGFloat
    let variance: CGFloat
}

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

// MARK: - Background analysis

/// Reads the chosen photo so the UI can pick complementary, quiet colours.
/// Small colour-theory toolkit shared by every palette. The rule is
/// **luminance first, then hue**: decide whether the art reads light or dark
/// (that governs text value), then whether its colour is *warm* or *cool*
/// (that governs the UI hue — a warm photo gets a cool-leaning palette and
/// vice-versa, while surfaces stay in the art's own temperature family so they
/// feel cohesive rather than pasted on).
enum ColorTheory {
    enum Temperature { case warm, cool, neutral }

    /// Perceptual (Rec. 709) luminance, 0…1.
    static func luminance(_ color: NSColor) -> CGFloat {
        let c = color.usingColorSpace(.deviceRGB) ?? .darkGray
        return 0.2126 * c.redComponent + 0.7152 * c.greenComponent + 0.0722 * c.blueComponent
    }
    static func isLight(_ color: NSColor) -> Bool { luminance(color) >= 0.5 }

    static func hsb(_ color: NSColor) -> (h: CGFloat, s: CGFloat, b: CGFloat) {
        let c = color.usingColorSpace(.deviceRGB) ?? .darkGray
        var h: CGFloat = 0, s: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
        c.getHue(&h, saturation: &s, brightness: &b, alpha: &a)
        return (h, s, b)
    }

    /// Warm = reds/oranges/yellows (hue < 65° or > 320°); cool = green→purple.
    /// Near-greys carry no temperature.
    static func temperature(_ color: NSColor) -> Temperature {
        let (h, s, _) = hsb(color)
        guard s > 0.12 else { return .neutral }
        let deg = h * 360
        return (deg < 65 || deg > 320) ? .warm : .cool
    }
    static func isWarm(_ color: NSColor) -> Bool { temperature(color) == .warm }

    /// Nearest hue of the *opposite* temperature (≈ the complement): the UI
    /// answers a warm photo with a cool accent and vice-versa.
    static func contrastingHue(_ color: NSColor) -> CGFloat {
        (hsb(color).h + 0.5).truncatingRemainder(dividingBy: 1)
    }
    /// A neighbouring hue that stays inside the art's own temperature family.
    static func adjacentHue(_ color: NSColor) -> CGFloat {
        (hsb(color).h + 0.083).truncatingRemainder(dividingBy: 1)   // +30°
    }
}


/// Colour-grades the bundled desert photo for each mode.
struct DesertGrade: ViewModifier {
    let theme: AppTheme
    func body(content: Content) -> some View {
        switch theme {
        case .hue:
            content.contrast(1.12).saturation(1.14)
        case .mono:
            content.grayscale(1.0).contrast(1.45).brightness(0.02)   // punchy B&W
        }
    }
}

/// Photo background (Pexels / Pixabay) with mode grading and soft scrims so the
/// floating chrome stays readable. The art is panned vertically so its calmest
/// band sits behind the wordmark.
struct DesertBackground: View {
    @Environment(\.palette) private var pal
    @Environment(\.appTheme) private var theme
    var name: String = ""
    /// Normalized y of the calm band in the source art (top-origin).
    var quietY: CGFloat = 0.4
    /// Decoded artwork size (aspect preserved), for the pan maths.
    var imageSize: CGSize = .zero

    var body: some View {
        GeometryReader { geo in
            let fw = geo.size.width, fh = geo.size.height
            let dy = panOffset(frame: CGSize(width: fw, height: fh))
            ZStack {
                Group {
                    if let img = NSImage(named: name), !name.isEmpty {
                        Color.clear
                            .frame(width: fw, height: fh)
                            .overlay(
                                Image(nsImage: img)
                                    .resizable()
                                    .scaledToFill()
                                    .modifier(DesertGrade(theme: theme))
                                    .offset(y: dy)
                            )
                            .clipped()
                    } else {
                        LinearGradient(colors: [pal.bg2, pal.bg],
                                       startPoint: .top, endPoint: .bottom)
                            .frame(width: fw, height: fh)
                    }
                }
                scrims
            }
        }
        .ignoresSafeArea()
    }

    /// Vertical shift so the image's quiet band lands ~40% down the frame (the
    /// resting wordmark), clamped so the photo still covers the whole view.
    private func panOffset(frame: CGSize) -> CGFloat {
        let iw = imageSize.width, ih = imageSize.height
        guard iw > 1, ih > 1, frame.width > 1, frame.height > 1 else { return 0 }
        let scale = max(frame.width / iw, frame.height / ih)
        return BackgroundAnalysis.panY(frameH: frame.height, dispH: ih * scale, quietY: quietY)
    }

    /// No top or bottom bars — everything floats straight on the photo.
    /// Only a soft cinematic vignette remains.
    private var scrims: some View {
        RadialGradient(colors: [.clear, Color.black.opacity(theme == .hue ? 0.16 : 0.45)],
                       center: .center, startRadius: 200, endRadius: 1100)
            .allowsHitTesting(false)
    }
}

/// Renders the *continuation* of the page artwork beneath the history sidebar:
/// the same photo at the same scale and pan as the detail column, shifted so the
/// slice belonging to the left of the sidebar lines up seamlessly. The sidebar's
/// Liquid Glass sits on top, so the image reads edge-to-edge under the glass
/// instead of the column sitting on a solid fill.
struct SidebarArtwork: View {
    @Environment(\.appTheme) private var theme
    var name: String
    var quietY: CGFloat
    var imageSize: CGSize
    /// Width of the detail column (its art's frame), in points.
    var artWidth: CGFloat

    var body: some View {
        GeometryReader { geo in
            let sw = geo.size.width, h = geo.size.height
            let iw = imageSize.width, ih = imageSize.height
            let W = artWidth > 1 ? artWidth : sw
            Group {
                if let img = NSImage(named: name), !name.isEmpty, iw > 1, ih > 1, h > 1 {
                    let scale = max(W / iw, h / ih)
                    let dw = iw * scale, dh = ih * scale
                    let dy = BackgroundAnalysis.panY(frameH: h, dispH: dh, quietY: quietY)
                    Image(nsImage: img)
                        .resizable()
                        .scaledToFill()
                        .frame(width: dw, height: dh)
                        .modifier(DesertGrade(theme: theme))
                        // centre the photo where the detail column centres it,
                        // then let the sidebar frame clip out its left slice
                        .offset(x: (sw + W) / 2 - sw / 2, y: dy)
                        .frame(width: sw, height: h)
                        .clipped()
                } else {
                    Color.clear
                }
            }
            .frame(width: sw, height: h)
        }
        .ignoresSafeArea()
        .allowsHitTesting(false)
    }
}

// MARK: - Engine

@MainActor
// Engine moved to Engine/Engine.swift.

// Command catalog moved to Screens/Menu/CommandItem.swift.

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
    @State private var expanded = false
    @State private var lastCount = 0
    @State private var bubbleAnim: Animation = Anim.smooth
    /// Stable legibility backing for a region — never zero, so text is always
    /// readable; the strength scales with how mid-toned (low-contrast) it is.
    /// Noir keeps every bubble dark regardless of how bright the photo is;
    /// Light adapts to the artwork behind it.
    private func scrim(_ r: BgRegion, strength: Double = 1) -> some View {
        let base = engine.scrimOpacity(r)
        // Stained glass: the plate is the theme surface (hued), one surface for
        // the whole page rather than a per-region neutral plate.
        return RoundedRectangle(cornerRadius: design.composition.bubbleCorner, style: .continuous)
            .fill(engine.colorTheme.surface.opacity(base * strength))
    }

    /// Body ink for a bubble: light on Noir's dark bubbles, otherwise sampled
    /// from the photo so it always contrasts.
    private func bubbleInk(_ r: BgRegion) -> Color {
        pal.isDark ? Color(white: 0.95) : engine.text(r)
    }
    private func bubbleDim(_ r: BgRegion) -> Color {
        pal.isDark ? Color(white: 0.68) : engine.dim(r)
    }

    private func trackText(_ text: String) {
        let delta = abs(text.count - lastCount)
        lastCount = text.count
        bubbleAnim = Anim.bubble(delta)
    }

    /// Header band that lives *inside* each bubble: role name + glyph, ruled off
    /// from the body by a hairline, so the body reads as its own section rather
    /// than raw padding. Natural width, so a hugging bubble stays hugged.
    private func roleHeader(_ name: String, symbol: String, region: BgRegion) -> some View {
        HStack(spacing: 6) {
            Image(systemName: symbol).font(.system(size: TypeScale.micro, weight: .bold))
            Text(name).font(.system(size: TypeScale.caption, weight: .semibold)).tracking(0.7)
        }
        .foregroundStyle(bubbleDim(region))
    }

    /// Hairline under the header band, spanning the bubble (drawn as an overlay
    /// so it never widens a bubble that hugs its text).
    private func headerRule(_ region: BgRegion) -> some View {
        Rectangle()
            .fill(bubbleDim(region).opacity(0.22))
            .frame(height: 0.75)
            .padding(.top, 35)
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
                BookText(text: message.text,
                         color: bubbleInk(.right).opacity(0.92),
                         onTap: { engine.center(message.id) })
                    .padding(.top, design.composition.roleHeaderTop)
                if message.pendingQuestion != nil {
                    HStack(spacing: 8) {
                        ActionButton(system: "arrow.clockwise", help: "Edit & re-ask") { engine.reAsk(message.id) }
                        ActionButton(system: "doc.on.doc", help: "Copy") { copyToPasteboard(message.text) }
                    }
                    .padding(.top, 11)
                }
            }
            .padding(.horizontal, design.composition.bubblePaddingH)
            .padding(.top, design.composition.bubblePaddingTop)
            .padding(.bottom, design.composition.bubblePaddingBottom)
            // a lighter, region-tinted backing so the reader's own words read as
            // a distinct, brighter note against the darker "mentat" answers
            .background {
                ZStack {
                    scrim(.right, strength: 0.8)
                    RoundedRectangle(cornerRadius: design.composition.bubbleCorner, style: .continuous)
                        .fill(pal.isDark ? Color.white.opacity(0.05) : engine.tint(.right))
                }
            }
            // one legibility plate for the content — no stacked glass on top
            .overlay(alignment: .top) { headerRule(.right) }
            .onTapGesture { engine.center(message.id) }
            .accessibilityElement(children: .contain)
            Spacer(minLength: 0)
        }
        .animation(reduceMotion ? nil : bubbleAnim, value: message.text)
        .onAppear { lastCount = message.text.count }
        .onChange(of: message.text) { _, t in trackText(t) }
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
                roleHeader("mentat", symbol: "sparkles", region: .left)
                VStack(alignment: .leading, spacing: 8) {
                if !message.reasoning.isEmpty {
                    DropdownRow(title: "Thoughts", count: nil, tint: bubbleDim(.left)) {
                        // Same reading columns as the answer, at caption scale.
                        ColumnText(
                            text: message.reasoning,
                            color: bubbleDim(.left),
                            availableWidth: textArea,
                            fontSize: 11,
                            showsPager: true)
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
                    PagedText(text: message.text,
                              color: message.failed ? pal.bad : bubbleInk(.left),
                              availableWidth: textArea,
                              messageID: message.id,
                              turn: engine.pageTurn,
                              onPage: { engine.center(message.id) },
                              onTap: { engine.center(message.id) },
                              onPages: { engine.setPageCount(message.id, $0) })
                }

                HStack(spacing: 10) {
                    if message.streaming {
                        ActionButton(system: "stop.circle", help: "Stop") { engine.stop() }
                    } else if !message.text.isEmpty {
                        ActionButton(system: "doc.on.doc", help: "Copy") { copyToPasteboard(message.text) }
                    }
                }
                }
                // two lines of breathing room between the "mentat" header and the
                // answer body
                .padding(.top, 40)
            }
            // roomier padding, with the header band inside so the role reads as a
            // header rather than a caption perched on the bubble's edge
            .padding(.horizontal, hPad)
            .padding(.top, design.composition.bubblePaddingTop)
            .padding(.bottom, design.composition.bubblePaddingBottom)
            .background(scrim(.left))
            // no stacked glass bubble: the scrim is the single content plate
            .overlay(alignment: .top) { headerRule(.left) }
            // clicking an answer keeps it centred so a page/reasoning animation
            // can't carry it out of the viewport
            .onTapGesture { engine.center(message.id) }
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
            // content layer: standard material, not Liquid Glass (per the HIG)
            .background(.regularMaterial,
                        in: RoundedRectangle(cornerRadius: 12, style: .continuous))
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
    @State private var question = ""
    @State private var showPalette = false
    @State private var showMenu = UserDefaults.standard.bool(forKey: "debugShowMenu")
    @State private var menuPanel: MenuPanel? =
        (UserDefaults.standard.string(forKey: "debugMenuPanel").flatMap { MenuPanel(rawValue: $0) })
    @State private var menuDetailH: CGFloat = 0
    @State private var composerH: CGFloat = 0

    /// Which sub-panel the hamburger's icon rail has open.
    private enum MenuPanel: String, CaseIterable, Identifiable {
        case background, palette, settings, command
        var id: String { rawValue }
        var symbol: String {
            switch self {
            case .background: return "photo.on.rectangle.angled"
            case .palette:    return "paintpalette"
            case .settings:   return "slider.horizontal.3"
            case .command:    return "command"
            }
        }
        var title: String {
            switch self {
            case .background: return "Background"
            case .palette:    return "Palette"
            case .settings:   return "Settings"
            case .command:    return "Command palette"
            }
        }
    }
    @FocusState private var focused: Bool
    @Environment(\.palette) private var pal
    @Environment(\.appTheme) private var theme
    @Environment(\.ink) private var ink
    @Environment(\.openWindow) private var openWindow
    @AppStorage("sidebarVisible") private var sidebarVisible = true
    @Environment(DesignStore.self) private var designStore: DesignStore?
    private var showGrid: Bool { designStore?.tokens.inspector.showGrid ?? false }
    @AppStorage("gridMargin") private var gridMargin = 20.0
    @AppStorage("gridCols") private var gridCols = 9
    @AppStorage("gridGutter") private var gridGutter = 16.0
    @AppStorage("gridRows") private var gridRows = 8
    @AppStorage("gridBaseline") private var gridBaseline = 12.0
    @AppStorage("headerHeight") private var headerHeight = 68.0
    @AppStorage("appearance") private var appearanceRaw = AppTheme.fallback.rawValue
    @AppStorage("shuffleBackgrounds") private var shuffleOnLaunch = false
    /// Global palette shift (degrees) — retints every UI colour at once.
    @AppStorage("paletteShift") private var paletteShift = 0.0

    private var suggestions: [CommandItem] {
        guard question.hasPrefix("/") else { return [] }
        let token = question.dropFirst()
        if token.contains(" ") { return [] }
        return CommandItem.all(debug: engine.debugMode)
            .filter { token.isEmpty || $0.cmd.hasPrefix(token.lowercased()) }
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
        .frame(minWidth: compact ? 400 : 640, minHeight: compact ? 360 : 520)
        .background(
            GeometryReader { g in
                Color.clear
                    .onAppear { engine.contentSize = g.size; engine.refreshBackgroundRegions() }
                    // resizing changes the visible crop of the photo, so the
                    // adaptive ink has to be recomputed against what's on screen
                    .onChange(of: g.size) { _, s in engine.contentSize = s; engine.refreshBackgroundRegions() }
            }
        )
        // the grid sits under the UI but over the art; it nudges down and grows a
        // masthead band for the wordmark once you start typing, and always stops
        // short of the composer (rounded + guttered) instead of clipping into it
        .background {
            // the grid runs from the page's top margin (up behind the wordmark,
            // matching the top row of the layout grid) down to the top of the
            // composer, leaving the model line + spacing as breathing room
            GridLinesLayer(topInset: 0, bottomTrim: composerH)
        }
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
                DebugPanel(engine: engine) {
                    withAnimation(Anim.snappy) { engine.debugMode = false }
                }
                .padding(.top, 64)
                .padding(.trailing, CGFloat(gridMargin))
                .glassMaterialize()
                .transition(.dropIn)
            }
        }
        .animation(Anim.smooth, value: engine.bgTint)
        .animation(Anim.smooth, value: engine.bgIsLight)
        .task {
            await engine.ensureEngine()
            focused = true
        }
        .sheet(isPresented: $showPalette) {
            CommandPalette(debugMode: engine.debugMode) { cmd in
                showPalette = false
                if cmd == "settings" { showMenu = true; menuPanel = .settings } else { question = "/\(cmd) "; focused = true }
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

    private var shadowColor: Color {
        engine.isLight(.center) ? Color.white.opacity(0.7) : Color.black.opacity(0.55)
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

    private var appearance: AppTheme { AppTheme(rawValue: appearanceRaw) ?? .fallback }
    private func cycleTheme() { appearanceRaw = appearance.next.rawValue }

    /// Chrome palette for the right-hand rail + panels, sampled from the art
    /// behind them — the same language the history rail uses on the left.
    private var chrome: ChromePalette { ChromePalette(engine, .right) }

    private var menuSections: [(String, [SettingSpec])] {
        var order: [String] = []; var map: [String: [SettingSpec]] = [:]
        for s in engine.settingsSpec where SettingSpec.primaryKeys.contains(s.key) {
            let sec = s.section ?? "Other"
            if map[sec] == nil { order.append(sec); map[sec] = [] }
            map[sec]?.append(s)
        }
        return order.map { ($0, map[$0] ?? []) }
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

    /// Background gallery: opens inside the menu so a wallpaper can be chosen
    /// without leaving the page. Live thumbnails, current one ringed in spice.
    private var backgroundPicker: some View {
        VStack(alignment: .leading, spacing: PanelGrid.gap(gridGutter)) {
            HStack {
                Text("BACKGROUNDS").font(.caption2).tracking(1).foregroundStyle(chrome.accent)
                Spacer()
                Button { engine.shuffleBackground() } label: {
                    Label("Shuffle", systemImage: "shuffle")
                }
                .buttonStyle(.plain).foregroundStyle(chrome.accent).font(.caption2)
            }
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 78), spacing: PanelGrid.gap(gridGutter) * 0.5)],
                      spacing: PanelGrid.gap(gridGutter) * 0.5) {
                ForEach(engine.backgrounds, id: \.self) { name in
                    Button { engine.selectBackground(name) } label: {
                        Color.clear
                            .frame(height: 52)
                            .frame(maxWidth: .infinity)
                            .overlay(
                                AsyncThumbnail(name: name)
                                    .modifier(DesertGrade(theme: theme))
                            )
                            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                            .overlay(
                                RoundedRectangle(cornerRadius: 8, style: .continuous)
                                    .strokeBorder(
                                        engine.backgroundName == name ? chrome.accent : chrome.dim.opacity(0.25),
                                        lineWidth: engine.backgroundName == name ? 2 : 1)
                            )
                    }
                    .buttonStyle(.pressable)
                }
            }
            Toggle("Shuffle on launch", isOn: $shuffleOnLaunch)
                .font(.caption2).foregroundStyle(engine.text(.center))

            // The OKLCH colour system: the roles resolved for the current image.
            VStack(alignment: .leading, spacing: 6) {
                Text("COLOUR SYSTEM").font(.caption2).tracking(1).foregroundStyle(chrome.accent)
                PaletteSwatches(colors: [engine.colorTheme.background, engine.colorTheme.surface,
                                         engine.colorTheme.accent, engine.colorTheme.ink,
                                         engine.colorTheme.good, engine.colorTheme.bad],
                                bigCount: 3, big: 22, small: 13)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(.top, PanelGrid.gap(gridGutter) * 0.5)
        }
        .padding(.top, PanelGrid.gap(gridGutter) * 0.5)
    }

    /// The palette tool: OKLCH-native controls over the active colour system.
    /// Hue follows the image; chroma and contrast tune the resolved, contrast-
    /// enforced theme. No named schemes.
    /// A small caption above a control, so the palette panel reads consistently
    /// now that the pickers are glass capsules instead of system segmenteds.
    @ViewBuilder private func labeledControl<Content: View>(
        _ title: String, @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(.system(size: TypeScale.caption)).foregroundStyle(chrome.dim)
            content()
        }
    }

    private var palettePicker: some View {
        let controls = engine.colorControls
        let theme = engine.colorTheme
        return VStack(alignment: .leading, spacing: PanelGrid.gap(gridGutter)) {
            HStack {
                Text("COLOUR SYSTEM").font(.caption2).tracking(1).foregroundStyle(chrome.accent)
                Spacer()
                Text(theme.isLight ? "light" : "dark")
                    .font(.caption2).foregroundStyle(chrome.dim)
            }
            ColumnText(
                text: "Hue follows the image. Contrast is enforced to WCAG.",
                color: chrome.dim,
                availableWidth: TextStyle.measure(chars: 40, size: 12),
                fontSize: 12)
            Text("image \(engine.imagePalette.isNeutral ? "neutral" : "\(Int(engine.imagePalette.baseHue))°") · base \(Int(theme.baseHue))°")
                .font(.system(size: TypeScale.micro, design: .monospaced))
                .foregroundStyle(chrome.dim)
                .fixedSize(horizontal: false, vertical: true)

            schemeList

            themePreview(theme)

            sliderRow("Hue", value: theme.baseHue, range: 0...360, suffix: "°") { v in
                var c = controls
                c.hueShift = v - engine.imagePalette.baseHue
                engine.setColorControls(c)
            }
            sliderRow("Chroma", value: controls.chroma, range: 0...2, format: "%.2f") { v in
                var c = controls; c.chroma = v; engine.setColorControls(c)
            }
            sliderRow("Contrast", value: controls.contrast, range: 0.6...1.8, format: "%.2f") { v in
                var c = controls; c.contrast = v; engine.setColorControls(c)
            }
            sliderRow("Tint", value: controls.tintStrength, range: 0...2, format: "%.2f") { v in
                var c = controls; c.tintStrength = v; engine.setColorControls(c)
            }
            Toggle("Follow image", isOn: Binding(
                get: { controls.followImage },
                set: { v in var c = controls; c.followImage = v; engine.setColorControls(c) }))
                .font(.caption2)

            labeledControl("Text ink") {
                GlassSegmentedControl(
                    options: [Engine.InkMode.background, .theme],
                    label: { $0 == .background ? "Adaptive" : "Theme" },
                    selection: Binding(
                        get: { engine.inkMode }, set: { engine.setInkMode($0) }))
            }

            labeledControl("Glass") {
                GlassSegmentedControl(
                    options: [GlassStyle.tinted, .clear],
                    label: { $0 == .tinted ? "Tinted" : "Clear" },
                    selection: Binding(
                        get: { engine.glassStyle }, set: { engine.setGlassStyle($0) }))
            }

            HStack(spacing: 8) {
                Button("Reset") {
                    var c = ColorControls.default
                    c.light = controls.light
                    c.monochrome = controls.monochrome
                    engine.setColorControls(c)
                }
                .buttonStyle(.plain).foregroundStyle(chrome.accent).font(.caption2)
                Spacer()
                Text(engine.imagePalette.isNeutral ? "neutral image"
                     : "image \(Int(engine.imagePalette.baseHue))°")
                    .font(.caption2).foregroundStyle(chrome.dim)
            }
        }
        .padding(.top, PanelGrid.gap(gridGutter) * 0.5)
    }

    /// A row of the theme's resolved roles, so the tool shows the actual result.
    private func themePreview(_ theme: ColorTheme) -> some View {
        HStack(spacing: 4) {
            ForEach(Array([theme.background, theme.surface, theme.accent, theme.secondary,
                           theme.tertiary, theme.ink, theme.good, theme.bad].enumerated()),
                    id: \.offset) { _, c in
                RoundedRectangle(cornerRadius: 5, style: .continuous)
                    .fill(c)
                    .frame(height: 26)
            }
        }
    }

    /// The scheme picker: one row per scheme with a live preview built from the
    /// current image, tap to apply.
    private var schemeList: some View {
        VStack(spacing: 4) {
            ForEach(PaletteScheme.allCases) { scheme in
                schemeRow(scheme)
            }
        }
    }

    private func schemeRow(_ scheme: PaletteScheme) -> some View {
        let t = engine.previewTheme(for: scheme)
        let active = engine.colorControls.scheme == scheme
        return Button {
            var c = engine.colorControls
            c.scheme = scheme
            engine.setColorControls(c)
        } label: {
            HStack(spacing: 8) {
                HStack(spacing: 3) {
                    ForEach(Array([t.background, t.surface, t.accent,
                                   t.secondary, t.tertiary, t.ink].enumerated()),
                            id: \.offset) { i, c in
                        RoundedRectangle(cornerRadius: 3, style: .continuous)
                            .fill(c)
                            .frame(width: i == 0 ? 20 : 12, height: 16)
                    }
                }
                Text(scheme.label)
                    .font(.system(size: 10.5, weight: .medium))
                    .foregroundStyle(active ? chrome.accent : chrome.ink)
                Spacer(minLength: 4)
                if active {
                    Image(systemName: "checkmark")
                        .font(.system(size: TypeScale.micro, weight: .bold))
                        .foregroundStyle(chrome.accent)
                }
            }
            .padding(.horizontal, 8).padding(.vertical, 5)
            .background(RoundedRectangle(cornerRadius: 9, style: .continuous)
                .fill(active ? chrome.accent.opacity(0.14) : Color.clear))
            .contentShape(RoundedRectangle(cornerRadius: 9, style: .continuous))
        }
        .buttonStyle(.plain)
    }

    private func sliderRow(_ label: String, value: Double, range: ClosedRange<Double>,
                           suffix: String = "", format: String = "%.0f",
                           set: @escaping (Double) -> Void) -> some View {
        HStack(spacing: 8) {
            Text(label).font(.caption2).foregroundStyle(engine.text(.center))
                .frame(width: 54, alignment: .leading)
            Slider(value: Binding(get: { value }, set: set), in: range)
            Text(String(format: format, value) + suffix)
                .font(.caption2).foregroundStyle(engine.dim(.center))
                .frame(width: 42, alignment: .trailing)
        }
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
            case .palette:
                return min(max(2 * colW, 356), panelCap)
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
        let menuTop = activated ? bandCenterY(H) + 24 : rowTop(1, H) + 48
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
    /// (Hue ↔ Noir) rather than a panel — it only has two states.
    private var menuRail: some View {
        VStack(spacing: 6) {
            CircleIconButton(
                system: "circle.lefthalf.filled",
                help: "Appearance: \(appearance.label) — click to switch (Hue ↔ Noir)",
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
                case .background:
                    backgroundPicker
                case .palette:
                    palettePicker
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
    private var gridTopInset: CGFloat { CGFloat(gridMargin) + gridContentInset }
    /// Bottom edge of the title/masthead row, in page coordinates.
    private var titleBottomY: CGFloat { CGFloat(gridMargin) + wordmarkBandH }
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

    /// One-line model + running dot, floated at the bottom-left of the page.
    private var modelLine: some View {
        HStack(spacing: 6) {
            Circle()
                .fill(engine.busy ? pal.good : (engine.online ? ink(.center).opacity(0.7) : engine.accentColor(.center)))
                .frame(width: 7, height: 7)
                .shadow(color: shadowColor, radius: 3)
            Text(engine.model)
                .font(.system(size: TypeScale.caption, weight: .semibold, design: .monospaced))
                .foregroundStyle(ink(.center))
                .lineLimit(1)
                .fixedSize()
        }
        .fixedSize()
        // a small Liquid Glass pill so the model name reads cleanly on the art
        .padding(.horizontal, 9).padding(.vertical, 4)
        .liquid(corner: 11, interactive: true)
        .shadow(color: shadowColor.opacity(0.5), radius: 2, y: 1)
    }

    /// Header disc colours: adaptive black/white sampled from the photo.
    private func discFill(_ region: BgRegion) -> Color { ink(region) }
    private func discContent(_ region: BgRegion) -> Color {
        // Contrast the disc's own fill (the adaptive ink), so the glyph never
        // vanishes when the art behind the control is dark.
        let lum = ColorScience.relativeLuminance(NSColor(ink(region)))
        return lum > 0.5 ? Color.black : Color.white
    }

    /// The rail's active/ink colours: adaptive ink sampled from the photo.
    private var railAccent: Color { ink(.right) }
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
        .shadow(color: shadowColor.opacity(0.6), radius: 3, y: 1)
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
            let titleTop = activated ? rowTop(1, H) : rowTop(4, H)
            let btnTop = activated ? bandCenterY(H) - 20 : rowTop(1, H)
            let menuX = gm + CGFloat(gn - 1) * (colW + gg) + colW / 2
            let sidebarX = gm + colW / 2
            let titleInk = activated ? ink.top : ink(.center)
            // Soft opposite-tone shadow guarantees separation if the art behind
            // is mid-tone — no outline, just a gentle halo.
            let titleIsLight = ColorScience.relativeLuminance(NSColor(titleInk)) > 0.5
            let titleShadow = titleIsLight ? Color.black.opacity(0.45) : Color.white.opacity(0.5)
            ZStack(alignment: .topLeading) {
                VStack(spacing: 12) {
                    Text("mentat")
                        .font(.custom("Quicksand-Light", size: 46))
                        .tracking(14)
                        .foregroundStyle(titleInk)
                    Text("what wisdom do you seek?")
                        .font(.system(size: 15, design: .monospaced))
                        .foregroundStyle(titleInk)
                        .opacity(activated ? 0 : 1)
                }
                .fixedSize()
                .shadow(color: titleShadow, radius: 16, y: 2)
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
            // thin ring; fills with the palette colour (Hue) or black/white (Noir)
            Circle().fill(on ? fill : Color.clear)
            Circle().stroke(fill.opacity(on ? 0.9 : 0.55), lineWidth: 1)
            Image(systemName: "sidebar.left")
                .font(.system(size: TypeScale.label, weight: .bold))
                .foregroundStyle(on ? content : fill)
        }
        .frame(width: 26, height: 26)
        .shadow(color: shadowColor.opacity(0.6), radius: 3, y: 1)
        // match the hamburger circle's 40pt hit frame so the two toggles
        // share the exact same vertical centre
        .frame(width: 40, height: 40)
        .contentShape(Circle())
        .scaleEffect(on ? 1.05 : 1)
        .animation(Anim.snappy, value: on)
        .onTapGesture { withAnimation(Anim.snappy) { sidebarVisible.toggle() } }
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
            // follow the newest turn, but defer to the next runloop so a just
            // appended turn is laid out before we scroll to it (scrolling in
            // the same update silently no-ops and the answer lands off-screen)
            .onChange(of: engine.messages.last?.text) { _, _ in
                DispatchQueue.main.async { proxy.scrollTo("bottom", anchor: .bottom) }
            }
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
                    question = "/\(item.cmd) "
                    focused = true
                } label: {
                    HStack {
                        Text("/\(item.cmd)").foregroundStyle(engine.accentColor(.center)).frame(width: 110, alignment: .leading)
                        Text(item.help).foregroundStyle(pal.textDim)
                        Spacer()
                    }
                    .padding(.horizontal, PanelGrid.gap(gridGutter)).padding(.vertical, PanelGrid.row(gridGutter) * 0.5)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.pressable)
            }
        }
        .liquid(corner: PanelGrid.radius(gridGutter))
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
        .background(.ultraThinMaterial, in: Capsule(style: .continuous))
        .padding(.horizontal, 16).padding(.bottom, 6)
        .transition(.move(edge: .bottom).combined(with: .opacity))
    }

    private var composer: some View {
        VStack(alignment: .leading, spacing: 6) {
            if !compact && !engine.model.isEmpty {
                modelLine.allowsHitTesting(false)
            }
            TextField("ask mentat…  (/help · \"count <word>\" or /freq to count)", text: $question, axis: .vertical)
                .textFieldStyle(.plain)
                .lineLimit(1...10)
                .padding(PanelGrid.row(gridGutter))
                .padding(.trailing, 52)
                // cap the input's measure so a line never reads past 55 chars
                .frame(maxWidth: TextStyle.maxMeasure() + 52 + 2 * PanelGrid.row(gridGutter),
                       alignment: .leading)
                .liquid(corner: PanelGrid.radius(gridGutter))
                .focused($focused)
                .onSubmit(send)
                // overlay (not ZStack) so the button can't stretch the bar
                .overlay(alignment: .trailing) {
                    // The one solid focal on screen (the reference's shutter):
                    // a filled accent circle when there's something to send,
                    // neutral glass otherwise.
                    Button(action: send) {
                        Image(systemName: engine.busy ? "stop.fill" : "arrow.up")
                            .font(.system(size: TypeScale.emphasis, weight: .bold))
                            .contentTransition(.symbolEffect(.replace))
                            .frame(width: 32, height: 32)
                            .foregroundStyle(
                                canSend
                                    ? engine.colorTheme.onAccent
                                    : engine.dim(.right))
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
}

// Debug panel moved to Screens/Debug/DebugPanel.swift.


// PaletteSwatches + PaletteGraph moved to Screens/Debug/DebugWidgets.swift.

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
    @Environment(\.appTheme) private var theme
    @AppStorage("sidebarVisible") private var sidebarVisible = true
    @AppStorage("appearance") private var appearanceRaw = AppTheme.fallback.rawValue
    @AppStorage("layoutMode") private var layoutMode = false
    @State private var layoutStore = LayoutGridStore()
    @State private var designStore = DesignStore()

    /// The history panel is a solid sheet with ink that always contrasts it,
    /// rather than sampling the photo: a dark, near-opaque panel with light text
    /// in Noir, and a light panel with dark text in Light.
    private var noir: Bool { theme == .mono }
    // The rail follows the OKLCH theme (hue from the image).
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
                         isLight: !noir,
                         onTap: { Task { await engine.openConversation(c.conv) } },
                         onPin: { withAnimation(Anim.snappy) { togglePin(c.conv) } },
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
        .background(.ultraThinMaterial, in: Capsule(style: .continuous))
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
            get: { sidebarVisible ? .all : .detailOnly },
            set: { sidebarVisible = ($0 != .detailOnly) }
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
                .background {
                    // the artwork behind the glass so it refracts the page photo
                    SidebarArtwork(name: engine.backgroundName,
                                   quietY: engine.bgQuietY,
                                   imageSize: engine.bgImageSize,
                                   artWidth: engine.contentSize.width)
                }
                .scrollContentBackground(.hidden)
                // Rebuild the rail whenever the theme flips, so no colour is
                // left over from the previous mode (kept the old text tint).
                .id(theme)
                .navigationSplitViewColumnWidth(
                    min: designStore.tokens.metrics.sidebarMin,
                    ideal: designStore.tokens.metrics.sidebarIdeal,
                    max: designStore.tokens.metrics.sidebarMax)
            } detail: {
                // the page (art + grid) owns the detail column; the sidebar
                // renders its own continuation of the artwork (SidebarArtwork)
                ZStack {
                    DesertBackground(name: engine.backgroundName,
                                     quietY: engine.bgQuietY,
                                     imageSize: engine.bgImageSize)
                    ChatView(engine: engine)
                }
            }
        .environment(layoutStore)
        .environment(designStore)
        .environment(\.design, designStore.tokens)
        .background(Color.clear)
        .background(
            GeometryReader { g in
                Color.clear
                    .onAppear { engine.windowSize = g.size }
                    .onChange(of: g.size) { _, s in engine.windowSize = s }
            }
        )
        .hideWindowToolbar()      // no system toolbar stacked above the header
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
            Button("Dismiss") {
                if layoutMode { withAnimation(Anim.snappy) { layoutMode = false } }
                else if !findText.isEmpty { findText = "" }
            }
            .keyboardShortcut(.cancelAction)
            .opacity(0)
        )
        .task {
            await engine.loadConversations()
            engine.loadBackgrounds()
        }
        .onChange(of: appearanceRaw) { _, _ in
            engine.selectBackground(engine.backgroundName)
        }
    }
}
