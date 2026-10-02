import AppKit
import SwiftUI

/// Full-height source reader: a tapped citation resolved to its verbatim
/// passage. The quote is the focal card; the wider window is readable in
/// context. Back (or Esc, handled by the host) returns to the answer.
///
/// The plate takes the **look's** surface + ink (the same authority as the rest
/// of the app), so it is legible by construction in every look and never depends
/// on what is behind it.
struct SourceReader: View {
    let engine: Engine
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.colorTheme) private var theme

    private var accent: Color { theme.accent }

    var body: some View {
        ZStack {
            // Focus scrim; clicking outside the plate returns to the answer.
            Color.black.opacity(0.34).ignoresSafeArea()
                .onTapGesture { engine.closeSource() }

            plate
                .padding(.horizontal, 30)
                .padding(.vertical, 26)
        }
        .transition(
            reduceMotion
                ? .opacity
                : .asymmetric(
                    insertion: .offset(y: 26).combined(with: .opacity),
                    removal: .opacity))
    }

    private var plate: some View {
        VStack(alignment: .leading, spacing: 16) {
            header
            Rectangle().fill(theme.inkDim.opacity(0.22)).frame(height: 1)
            content
        }
        .padding(22)
        .frame(maxWidth: 1040, maxHeight: .infinity, alignment: .topLeading)
        .background(
            theme.background,
            in: RoundedRectangle(cornerRadius: ChromeShape.radiusL, style: .continuous)
        )
        .overlay(
            RoundedRectangle(cornerRadius: ChromeShape.radiusL, style: .continuous)
                .strokeBorder(theme.border.opacity(0.6), lineWidth: 1))
        .shadow(color: .black.opacity(theme.isLight ? 0.18 : 0.40), radius: 30, y: 16)
    }

    private var header: some View {
        HStack(alignment: .center, spacing: 12) {
            CircleIconButton(
                system: "chevron.left",
                help: "Back to the answer",
                diameter: ChromeShape.circle,
                tint: accent
            ) {
                engine.closeSource()
            }

            Spacer()

            VStack(alignment: .trailing, spacing: 2) {
                Text(engine.readerSource?.book ?? "Source")
                    .font(.system(size: TypeScale.title, weight: .semibold)).foregroundStyle(theme.ink)
                if let loc = engine.readerSource?.loc, !loc.isEmpty {
                    Text(loc).font(.system(size: TypeScale.caption)).foregroundStyle(theme.inkDim)
                }
            }
        }
    }

    @ViewBuilder private var content: some View {
        if engine.readerLoading {
            HStack(spacing: 10) {
                ProgressView().controlSize(.small)
                Text("Finding the source…").font(.callout).foregroundStyle(theme.inkDim)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if engine.readerFailed {
            VStack(spacing: 8) {
                Image(systemName: "text.book.closed")
                    .font(.system(size: 24)).foregroundStyle(theme.inkDim)
                Text("Couldn't locate that passage").font(.callout).foregroundStyle(theme.ink)
                Text("The index may not carry this edition yet.")
                    .font(.caption).foregroundStyle(theme.inkDim)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if let src = engine.readerSource, let text = src.text, !text.isEmpty {
            VStack(alignment: .leading, spacing: 18) {
                if let q = src.quote, !q.isEmpty { quoteCard(q) }
                passage(text, quote: src.quote)
            }
        }
    }

    /// The one solid focal: the exact sentence the citation points at.
    private func quoteCard(_ q: String) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: "quote.opening")
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(accent.opacity(0.90))
                .padding(.top, 2)
            Text(q)
                .font(.system(size: 16, design: .serif))
                .foregroundStyle(theme.ink)
                .lineSpacing(3)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
        }
        .padding(.horizontal, 16).padding(.vertical, 14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            theme.surface,
            in: RoundedRectangle(cornerRadius: ChromeShape.radiusM, style: .continuous))
    }

    /// The surrounding book text, set in reading columns (1 → 2 → 3) with the
    /// same pager the answer body uses, so a long passage pages rather than
    /// stretching one narrow strip.
    private func passage(_ text: String, quote: String?) -> some View {
        GeometryReader { g in
            let w = max(260, min(1200, g.size.width))
            ColumnText(
                text: text, color: theme.ink, availableWidth: w,
                showsPager: true, highlight: quote
            )
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .frame(maxHeight: .infinity)
    }
}
