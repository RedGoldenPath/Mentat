import AppKit
import SwiftUI

// MARK: - Reader (book pagination surface)

/// An `NSTextView` that reports plain clicks back to SwiftUI (AppKit otherwise
/// swallows them, so a parent gesture never fires over the body text).
final class TappableTextView: NSTextView {
    var onTap: (() -> Void)?
    override func mouseDown(with event: NSEvent) {
        onTap?()
        super.mouseDown(with: event)
    }
}

struct BookTextView: NSViewRepresentable {
    let attr: NSAttributedString
    let width: CGFloat
    var onTap: (() -> Void)? = nil

    nonisolated(unsafe) private static var heightCache: [String: CGFloat] = [:]

    static func height(_ attr: NSAttributedString, width: CGFloat) -> CGFloat {
        let w = max(20, width)
        // Identity + width → O(1) hit (no O(n) string hashing per render).
        let key = "\(ObjectIdentifier(attr).hashValue)|\(Int(w))"
        if let hit = heightCache[key] { return hit }
        let r = attr.boundingRect(
            with: NSSize(width: w, height: .greatestFiniteMagnitude),
            options: [.usesLineFragmentOrigin, .usesFontLeading])
        let h = ceil(r.height) + 2
        if heightCache.count > 300 { heightCache.removeAll() }
        heightCache[key] = h
        return h
    }
    func makeNSView(context: Context) -> NSTextView {
        let tv = TappableTextView()
        tv.onTap = onTap
        tv.isEditable = false
        tv.isSelectable = true
        tv.drawsBackground = false
        tv.textContainerInset = .zero
        tv.textContainer?.lineFragmentPadding = 0
        tv.textContainer?.widthTracksTextView = false
        tv.isVerticallyResizable = false
        tv.isHorizontallyResizable = false
        return tv
    }
    func updateNSView(_ tv: NSTextView, context: Context) {
        (tv as? TappableTextView)?.onTap = onTap
        let w = max(20, width)
        let h = Self.height(attr, width: w)
        tv.textStorage?.setAttributedString(attr)
        tv.textContainer?.containerSize = NSSize(width: w, height: h)
        tv.frame.size = NSSize(width: w, height: h)
        tv.needsDisplay = true
    }
    func sizeThatFits(_ proposal: ProposedViewSize, nsView tv: NSTextView, context: Context)
        -> CGSize?
    {
        let w = max(20, min(width, proposal.width ?? width))
        return CGSize(width: w, height: Self.height(attr, width: w))
    }
}

/// Watches for the left/right arrow keys and pages the clicked answer. A local
/// `NSEvent` monitor is used so it only steps in when a text field (the
/// composer, or a settings input) is *not* editing — otherwise the cursor keys
/// keep working normally.
struct ArrowKeyMonitor: NSViewRepresentable {
    let engine: Engine

    func makeCoordinator() -> Coordinator { Coordinator(engine: engine) }
    func makeNSView(context: Context) -> NSView {
        context.coordinator.start()
        return NSView(frame: .zero)
    }
    func updateNSView(_ nsView: NSView, context: Context) {}
    static func dismantleNSView(_ nsView: NSView, coordinator: Coordinator) { coordinator.stop() }

    // TRANSITIONAL: a local NSEvent monitor always fires on the main thread; the
    // rewritten key handling owns its isolation properly.
    final class Coordinator: @unchecked Sendable {
        private let engine: Engine
        private var monitor: Any?
        init(engine: Engine) { self.engine = engine }

        func start() {
            guard monitor == nil else { return }
            monitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
                guard let self else { return event }
                // left arrow = 123, right arrow = 124
                guard event.keyCode == 123 || event.keyCode == 124 else { return event }
                let mods = event.modifierFlags
                if mods.contains(.command) || mods.contains(.control) || mods.contains(.option) {
                    return event
                }
                // A field editor (composer) keeps its caret keys *while it has
                // text*; an empty composer lets the arrows turn the answer's page.
                let keyCode = event.keyCode
                let isFieldEditor: Bool = MainActor.assumeIsolated {
                    if let tv = NSApp.keyWindow?.firstResponder as? NSTextView,
                        tv.isFieldEditor, !tv.string.isEmpty
                    {
                        return true
                    }
                    return false
                }
                if isFieldEditor { return event }
                let consumed: Bool = MainActor.assumeIsolated {
                    guard self.engine.selectedCanTurn else { return false }
                    self.engine.turnPage(keyCode == 123 ? -1 : 1)
                    return true
                }
                return consumed ? nil : event
            }
        }

        func stop() {
            if let monitor { NSEvent.removeMonitor(monitor) }
            monitor = nil
        }
    }
}

/// Single centred column (the user's own messages).
struct BookText: View {
    let text: String
    let color: Color
    var ink: TextInk? = nil
    var onTap: (() -> Void)? = nil
    var body: some View {
        let measure = min(TextStyle.measure(chars: 40), TextStyle.maxMeasure())
        let w = max(40, TextStyle.hugWidth(text, max: measure))
        BookTextView(
            attr: TextStyle.attributed(text, color: NSColor(color), ink: ink, alignment: .center),
            width: w, onTap: onTap)
    }
}

/// A single, continuous reading column for chat answers: no column spilling and
/// no pagination — the text simply flows down, the way a normal chat app reads.
/// Capped at a comfortable width so it never becomes a full-width wall of text.
struct ReadingColumn: View {
    let text: String
    let color: Color
    let availableWidth: CGFloat
    var ink: TextInk? = nil
    var fontSize: CGFloat? = nil
    var highlight: String? = nil
    var onTap: (() -> Void)? = nil
    @Environment(LayoutGridStore.self) private var layoutStore: LayoutGridStore?

    /// The column width: the book measure for the current size, never wider than
    /// the space available. The column itself is centred on the page.
    private var width: CGFloat {
        let sz = fontSize ?? TextStyle.fontSize
        return max(280, min(availableWidth, TextStyle.maxMeasure(size: sz)))
    }
    private var baseline: CGFloat {
        guard let b = layoutStore?.grid.baseline, b > 2 else { return 0 }
        return b
    }

    var body: some View {
        let ns = NSColor(color)
        var attr = TextStyle.attributed(
            text, color: ns, ink: ink, alignment: .justified, baseline: baseline, size: fontSize)
        // Softly wash the cited quote (source reader), same as the paged body.
        if let hl = highlight, !hl.isEmpty, let r = text.range(of: hl) {
            let nsr = NSRange(r, in: text)
            if nsr.location != NSNotFound, nsr.length > 0 {
                let wash = NSColor(Engine.shared.accentColor(.center)).withAlphaComponent(0.20)
                let m = NSMutableAttributedString(attributedString: attr)
                m.addAttribute(.backgroundColor, value: wash, range: nsr)
                attr = m
            }
        }
        // Natural column width (the measure); the parent centres it on the page,
        // so the answer reads as a centred, justified column of text.
        return BookTextView(attr: attr, width: width, onTap: onTap)
    }
}

/// Assistant body text: measured line breaks, strict `linesPerColumn`-line
/// columns that fill and spill 1 → up to the token max, then page mode. All the pagination
/// math lives in the pure `PageEngine`; this view owns only state + rendering.
struct PagedText: View {
    let text: String
    let color: Color
    let availableWidth: CGFloat
    var ink: TextInk? = nil
    /// Identity of the owning message, so arrow-key turn requests can be matched.
    var messageID: UUID
    /// Externally-driven page turn (set by the arrow keys when this answer is
    /// the clicked one).
    var turn: PageTurn? = nil
    /// Optional per-view overrides; by default the app-wide tokens govern them,
    /// read live so changing Type in the design panel re-paginates immediately.
    var linesPerColumn: Int? = nil
    var maxColumns: Int? = nil
    /// A substring of `text` to softly tint (the source reader highlights the
    /// quote the citation came from).
    var highlight: String? = nil
    /// Show the `‹ 2/3 ›` pager when the text spans more than one page. Pop-ups
    /// that just want the column *layout* can turn it off.
    var showsPager: Bool = true
    /// Typographic size override — pop-ups set their own scale; the answer body
    /// uses the book size.
    var fontSize: CGFloat? = nil
    /// Called after a page flip so the host can keep this answer in view.
    var onPage: (() -> Void)? = nil
    /// Called when the answer body itself is clicked.
    var onTap: (() -> Void)? = nil
    /// Reports how many pages this answer lays out to.
    var onPages: ((Int) -> Void)? = nil
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    /// The live armature — its baseline grid snaps the body text.
    @Environment(LayoutGridStore.self) private var layoutStore: LayoutGridStore?
    @Environment(\.design) private var design
    @State private var page = 0
    @State private var forward = true

    private var measure: CGFloat { TextStyle.measure(chars: 40, size: fontSize) }
    /// Gutters between text columns match the layout grid, so three columns line
    /// up exactly with the C1 / C4 / C7 bands.
    @AppStorage("gridGutter") private var gutter = 16.0
    private var spacing: CGFloat { max(8, CGFloat(gutter)) }
    private var baseline: CGFloat {
        guard let b = layoutStore?.grid.baseline, b > 2 else { return 0 }
        return b
    }

    private var engine: PageEngine {
        PageEngine(
            measure: measure, maxColumnWidth: TextStyle.maxMeasure(),
            linesPerColumn: linesPerColumn ?? design.typography.linesPerColumn,
            maxColumns: maxColumns ?? design.typography.maxColumns, gutter: spacing)
    }

    private var pageTransition: AnyTransition {
        if reduceMotion { return .opacity }
        // a short slide that stays inside the bubble's padding + a fade, so the
        // text melts at the border instead of flying out of the box
        let dx = CGFloat(design.motion.pageSlide)
        return .asymmetric(
            insertion: .offset(x: forward ? dx : -dx).combined(with: .opacity),
            removal: .offset(x: forward ? -dx : dx).combined(with: .opacity))
    }

    var body: some View {
        let R = cachedResolved()
        let idx = min(page, R.layout.pages - 1)

        let content = pageView(idx, R)
            .id(idx)
            .transition(pageTransition)

        // The pager lives at the TOP of the answer, not overlaid on the bottom
        // edge: a page can be taller than the viewport, so a bottom control
        // scrolls out of reach (the back button visibly "disappeared"). Keeping
        // it above the text means it stays put whenever the answer is in view.
        VStack(alignment: .leading, spacing: 6) {
            if R.layout.pages > 1 && showsPager { pager(idx, R.layout.pages) }
            // the bubble hugs whatever this page actually holds, so a short
            // final page collapses instead of leaving a full-height empty box
            content
        }
        .onChange(of: text) { _, _ in page = 0 }
        // arrow-key (or pager) turn request aimed at this answer
        .onChange(of: turn) { _, newTurn in
            guard let t = newTurn, t.id == messageID else { return }
            flip(page + t.delta, R.layout.pages)
        }
        // publish the page count so the host knows arrows have work to do
        .onAppear { onPages?(R.layout.pages) }
        .onChange(of: R.layout.pages) { _, n in onPages?(n) }
    }

    /// Compact page control: `‹ 2 / 3 ›`, always visible at the top of the body.
    private func pager(_ idx: Int, _ pages: Int) -> some View {
        HStack(spacing: 8) {
            Button {
                flip(idx - 1, pages)
            } label: {
                Image(systemName: "chevron.left")
                    .font(.system(size: TypeScale.caption, weight: .bold))
                    .padding(5).contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .disabled(idx <= 0)
            .opacity(idx <= 0 ? 0.28 : 1)
            .help("Previous page")
            // page dots for short answers (the reference language); a numeric
            // readout only when there are too many pages for dots.
            if pages <= 8 {
                HStack(spacing: 5) {
                    ForEach(0..<pages, id: \.self) { i in
                        Circle()
                            .fill(color.opacity(i == idx ? 0.85 : 0.26))
                            .frame(width: 5, height: 5)
                    }
                }
                .animation(Anim.snappy, value: idx)
            } else {
                Text("page \(idx + 1) / \(pages)")
                    .font(.system(size: TypeScale.meta, weight: .medium, design: .monospaced))
                    .foregroundStyle(color.opacity(0.62))
            }
            Button {
                flip(idx + 1, pages)
            } label: {
                Image(systemName: "chevron.right")
                    .font(.system(size: TypeScale.caption, weight: .bold))
                    .padding(5).contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .disabled(idx >= pages - 1)
            .opacity(idx >= pages - 1 ? 0.28 : 1)
            .help("Next page")
        }
        .foregroundStyle(color.opacity(0.8))
    }

    private struct Resolved {
        let attr: NSAttributedString
        let lines: [NSRange]
        let layout: PageEngine.Layout
    }

    /// `resolve()` runs several full CoreText passes; memoise it keyed on the
    /// exact inputs so streaming/resizing doesn't re-typeset the same text. The
    /// key is cheap (no O(n) hashing); the exact string is verified on a hit.
    private struct ResolvedEntry {
        let text: String
        let resolved: Resolved
    }
    nonisolated(unsafe) private static var resolvedCache: [String: ResolvedEntry] = [:]
    private func cachedResolved() -> Resolved {
        let key =
            "\(text.count)|\(ink?.cacheKey ?? "-")|\(Int(availableWidth))|\(linesPerColumn ?? design.typography.linesPerColumn)|\(maxColumns ?? design.typography.maxColumns)|\(Int(baseline))|\(Int(spacing))|\(Int(fontSize ?? 0))|\(highlight?.hashValue ?? 0)"
        if let hit = PagedText.resolvedCache[key], hit.text == text { return hit.resolved }
        let fresh = resolve()
        if PagedText.resolvedCache.count > 120 { PagedText.resolvedCache.removeAll() }
        PagedText.resolvedCache[key] = ResolvedEntry(text: text, resolved: fresh)
        return fresh
    }

    private func resolve() -> Resolved {
        let started = CFAbsoluteTimeGetCurrent()
        defer { Perf.record("layout", ms: (CFAbsoluteTimeGetCurrent() - started) * 1000) }
        let ns = NSColor(color)
        let justified = TextStyle.attributed(
            text, color: ns, ink: ink, alignment: .justified, baseline: baseline, size: fontSize)
        // Everything is measured at the fixed book measure: one column is worth
        // `linesPerColumn` lines there. The column count therefore comes from
        // how many measure-columns the text needs — 1, then 2, then a
        // new page — and resizing the window never changes it.
        let lines = TextLayout.lineRanges(justified, width: measure)
        let layout = engine.layout(lineCount: lines.count, availableWidth: availableWidth)
        var attr =
            layout.centredSingleColumn
            ? TextStyle.attributed(
                text, color: ns, ink: ink, alignment: .center, baseline: baseline, size: fontSize)
            : justified
        // Softly tint the cited quote inside the passage (no outline, just a wash).
        if let hl = highlight, !hl.isEmpty, let r = text.range(of: hl) {
            let nsr = NSRange(r, in: text)
            if nsr.location != NSNotFound, nsr.length > 0 {
                let wash = NSColor(Engine.shared.accentColor(.center)).withAlphaComponent(0.20)
                let m = NSMutableAttributedString(attributedString: attr)
                m.addAttribute(.backgroundColor, value: wash, range: nsr)
                attr = m
            }
        }
        return Resolved(attr: attr, lines: lines, layout: layout)
    }

    private func flip(_ to: Int, _ pages: Int) {
        let t = min(max(0, to), pages - 1)
        forward = t > page
        if reduceMotion { page = t } else { withAnimation(Anim.smooth) { page = t } }
        onPage?()
    }

    private func pageView(_ index: Int, _ R: Resolved) -> some View {
        let p = engine.page(index, layout: R.layout, lines: R.lines, availableWidth: availableWidth)
        // the bubble is as wide as the columns this page actually uses, so it
        // resizes as you flip between a full page and a short one
        let fullW = CGFloat(p.columns) * p.columnWidth + CGFloat(p.columns - 1) * spacing
        return HStack(alignment: .top, spacing: spacing) {
            ForEach(Array(p.slices.enumerated()), id: \.offset) { _, range in
                BookTextView(
                    attr: R.attr.attributedSubstring(from: range),
                    width: p.columnWidth, onTap: onTap)
            }
        }
        .frame(width: fullW, alignment: .leading)
    }
}

/// The reading-column engine as a standalone view for prose surfaces outside the
/// answer body — the `Thoughts` disclosure and the menu panels — so every block
/// of prose typesets at the same measure and flows into the same columns. Runs
/// at its own scale; the pager is optional (off for one-screen pop-up text).
struct ColumnText: View {
    let text: String
    let color: Color
    let availableWidth: CGFloat
    var fontSize: CGFloat? = nil
    var showsPager: Bool = false
    var highlight: String? = nil
    var onPages: ((Int) -> Void)? = nil
    @State private var id = UUID()

    var body: some View {
        PagedText(
            text: text, color: color, availableWidth: availableWidth,
            messageID: id, highlight: highlight, showsPager: showsPager,
            fontSize: fontSize, onPages: onPages)
    }
}
