import SwiftUI

/// The right-hand Inspector: artifacts · citations · source · files · context.
/// Reads live engine state (the current answer's citations and telemetry, the
/// open passage, attachments) so there is a single source of truth.
struct InspectorPane: View {
    let engine: Engine
    @Bindable var inspector: InspectorStore
    @Environment(\.palette) private var pal

    /// The answer the Inspector is showing: the one you clicked, or the most
    /// current answer when nothing is pinned.
    private var answer: ChatMessage? {
        InspectorStore.focusedAnswer(in: engine.messages, focused: inspector.focusedAnswerID)
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            tabStrip
            Divider().overlay(pal.border.opacity(0.4))
            ScrollView {
                content
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(Spacing.m)
            }
            .softScrollEdges()
            SlotView(key: .inspectorContent)
        }
        .background(panel)
        .overlay(alignment: .leading) {
            Rectangle()
                .fill(pal.border.opacity(0.5))
                .frame(width: 1)
        }
    }

    private var panel: some View {
        pal.bg2.opacity(pal.isDark ? 0.92 : 0.95)
    }

    // MARK: header

    private var header: some View {
        HStack(spacing: Spacing.xs) {
            Image(systemName: "rectangle.righthalf.inset.filled")
                .font(.system(size: TypeScale.label, weight: .semibold))
                .foregroundStyle(pal.textDim)
            Text("Inspector")
                .font(.system(size: TypeScale.title, weight: .semibold))
                .foregroundStyle(pal.text)
            Spacer(minLength: Spacing.xs)
            Button {
                withAnimation(Anim.snappy) { inspector.visible = false }
            } label: {
                Image(systemName: "xmark")
                    .font(.system(size: TypeScale.caption, weight: .bold))
                    .foregroundStyle(pal.textDim)
                    .frame(width: 22, height: 22)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .help("Hide inspector (⌘I)")
            .accessibilityLabel("Hide inspector")
        }
        .padding(.horizontal, Spacing.s)
        .padding(.vertical, Spacing.s)
    }

    private var tabStrip: some View {
        HStack(spacing: 2) {
            ForEach(InspectorTab.allCases) { t in
                Button { inspector.tab = t } label: {
                    VStack(spacing: 3) {
                        Image(systemName: t.symbol)
                            .font(.system(size: TypeScale.label, weight: .semibold))
                        Text(t.title)
                            .font(.system(size: TypeScale.micro, weight: .semibold))
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, Spacing.xs)
                    .foregroundStyle(inspector.tab == t ? pal.text : pal.textDim)
                    .background(
                        RoundedRectangle(cornerRadius: ChromeShape.radiusS, style: .continuous)
                            .fill(inspector.tab == t ? pal.text.opacity(0.08) : .clear))
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .help(t.title)
            }
        }
        .padding(.horizontal, Spacing.xs)
        .padding(.bottom, Spacing.xs)
    }

    // MARK: content

    @ViewBuilder private var content: some View {
        switch inspector.tab {
        case .artifacts: artifactsTab
        case .citations: citationsTab
        case .source: sourceTab
        case .files: filesTab
        case .context: contextTab
        }
    }

    private var artifactsTab: some View {
        ArtifactsView(text: answer?.text ?? "")
    }

    @ViewBuilder private var citationsTab: some View {
        let answer = self.answer
        let cites = answer?.citations ?? []
        VStack(alignment: .leading, spacing: Spacing.xs) {
            if let answer, answer.ungrounded > 0 {
                MentatBadge(text: "\(answer.ungrounded) ungrounded", color: pal.bad)
            }
            if cites.isEmpty {
                MentatEmptyState(
                    system: "quote.opening", title: "No citations",
                    message: "Citations from the current answer appear here.")
            } else {
                ForEach(cites) { c in
                    Button {
                        engine.openSource(c, hint: answer?.text ?? "")
                    } label: {
                        MentatListRow(system: "text.book.closed", title: c.book, subtitle: c.loc)
                    }
                    .buttonStyle(.plain)
                    .help("Open source")
                }
            }
        }
    }

    @ViewBuilder private var sourceTab: some View {
        if let src = engine.readerSource, src.found {
            VStack(alignment: .leading, spacing: Spacing.s) {
                if let book = src.book {
                    Text(book)
                        .font(.system(size: TypeScale.label, weight: .semibold))
                        .foregroundStyle(pal.spice)
                }
                if let q = src.quote, !q.isEmpty {
                    Text(q)
                        .font(.system(size: TypeScale.body))
                        .italic()
                        .foregroundStyle(pal.text)
                        .padding(Spacing.s)
                        .background(pal.text.opacity(0.06),
                                    in: RoundedRectangle(cornerRadius: ChromeShape.radiusS, style: .continuous))
                }
                if let t = src.text, !t.isEmpty {
                    Text(t)
                        .font(.system(size: TypeScale.body))
                        .lineSpacing(3)
                        .foregroundStyle(pal.textDim)
                        .textSelection(.enabled)
                }
            }
        } else {
            MentatEmptyState(
                system: "text.book.closed", title: "No source open",
                message: "Tap a citation to load its passage. Esc returns.")
        }
    }

    @ViewBuilder private var filesTab: some View {
        let names = attachmentNames
        if names.isEmpty {
            MentatEmptyState(
                system: "paperclip", title: "No files",
                message: "Documents attached to this conversation appear here.")
        } else {
            VStack(alignment: .leading, spacing: Spacing.xs) {
                ForEach(names, id: \.self) { name in
                    MentatListRow(system: "doc", title: name)
                }
            }
        }
    }

    @ViewBuilder private var contextTab: some View {
        let m = answer?.meta
        let tin = Double(m?.tokens_in ?? 0)
        let tout = Double(m?.tokens_out ?? 0)
        let total = max(1, tin + tout)
        VStack(alignment: .leading, spacing: Spacing.s) {
            meter(fraction: tin / total, caption: "\(Int(tin)) in · \(Int(tout)) out")
            VStack(alignment: .leading, spacing: 2) {
                stat("Model", answer?.model.nonEmpty ?? "—")
                stat("Kind", m?.kind?.nonEmpty ?? "—")
                stat("Route", m?.route_reason?.nonEmpty ?? "—")
                stat("Thinking", m?.t_thinking.map { String(format: "%.1fs", $0) } ?? "—")
                if let cache = m?.cache_hit_tokens, cache > 0 {
                    stat("Cache hit", "\(cache) tok")
                }
                if let cost = m?.cost_usd, cost > 0 {
                    stat("Cost", String(format: "$%.4f", cost))
                }
            }
        }
    }

    // MARK: helpers

    private var attachmentNames: [String] {
        var seen = Set<String>()
        var out: [String] = []
        for n in engine.pendingAttachments.map(\.name) + engine.messages.flatMap(\.attachmentNames)
        where seen.insert(n).inserted {
            out.append(n)
        }
        return out
    }

    private func meter(fraction: Double, caption: String) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            GeometryReader { g in
                ZStack(alignment: .leading) {
                    Capsule().fill(pal.text.opacity(0.10))
                    Capsule().fill(pal.spice.opacity(0.85))
                        .frame(width: max(2, g.size.width * min(1, max(0, fraction))))
                }
            }
            .frame(height: 8)
            Text(caption)
                .font(.system(size: TypeScale.micro, weight: .medium))
                .foregroundStyle(pal.textDim)
        }
    }

    private func stat(_ title: String, _ value: String) -> some View {
        HStack(spacing: Spacing.s) {
            Text(title)
                .font(.system(size: TypeScale.body))
                .foregroundStyle(pal.textDim)
            Spacer(minLength: Spacing.xs)
            Text(value)
                .font(.system(size: TypeScale.body, weight: .medium))
                .foregroundStyle(pal.text)
                .lineLimit(1)
        }
        .padding(.vertical, 3)
    }
}

private extension String {
    var nonEmpty: String? { isEmpty ? nil : self }
}
