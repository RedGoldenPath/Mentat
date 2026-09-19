import AppKit
import SwiftUI

/// Full-height source reader: a tapped citation resolved to its verbatim
/// passage. The quote is the focal card; the wider window is readable in
/// context. Back (or Esc, handled by the host) returns to the answer.
struct SourceReader: View {
    let engine: Engine
    @Environment(\.palette) private var pal
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var ink: Color {
        engine.useOKLCHTheme ? engine.colorTheme.ink : pal.text
    }
    private var dim: Color {
        engine.useOKLCHTheme ? engine.colorTheme.inkDim : pal.textDim
    }
    private var accent: Color { engine.accentColor(.center) }
    private var quoteSurface: Color {
        engine.useOKLCHTheme ? engine.colorTheme.surface : pal.bg2
    }
    private var quoteInk: Color {
        engine.useOKLCHTheme ? engine.colorTheme.ink : pal.text
    }

    var body: some View {
        ZStack {
            // Focus scrim; clicking outside the plate returns to the answer.
            Color.black.opacity(0.30).ignoresSafeArea()
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
            Rectangle().fill(dim.opacity(0.16)).frame(height: 1)
            content
        }
        .padding(22)
        .frame(maxWidth: 1040, maxHeight: .infinity, alignment: .topLeading)
        .glassPanel(corner: 28)
        .shadow(color: .black.opacity(0.34), radius: 30, y: 16)
    }

    private var header: some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Button {
                engine.closeSource()
            } label: {
                Label("Answer", systemImage: "chevron.left")
                    .font(.callout.weight(.medium))
            }
            .buttonStyle(.plain)
            .foregroundStyle(accent)
            .help("Back to the answer")
            .accessibilityLabel("Back to the answer")

            Spacer()

            VStack(alignment: .trailing, spacing: 2) {
                Text(engine.readerSource?.book ?? "Source")
                    .font(.headline).foregroundStyle(ink)
                if let loc = engine.readerSource?.loc, !loc.isEmpty {
                    Text(loc).font(.caption).foregroundStyle(dim)
                }
            }
        }
    }

    @ViewBuilder private var content: some View {
        if engine.readerLoading {
            HStack(spacing: 10) {
                ProgressView().controlSize(.small)
                Text("Finding the source…").font(.callout).foregroundStyle(dim)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if engine.readerFailed {
            VStack(spacing: 8) {
                Image(systemName: "text.book.closed")
                    .font(.system(size: 24)).foregroundStyle(dim)
                Text("Couldn't locate that passage").font(.callout).foregroundStyle(ink)
                Text("The index may not carry this edition yet.")
                    .font(.caption).foregroundStyle(dim)
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
                .foregroundStyle(accent.opacity(0.85))
                .padding(.top, 2)
            Text(q)
                .font(.system(size: 16, design: .serif))
                .foregroundStyle(quoteInk)
                .lineSpacing(3)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
        }
        .padding(.horizontal, 16).padding(.vertical, 14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(quoteSurface, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
    }

    /// The surrounding book text, scrollable, with the quote softly washed.
    private func passage(_ text: String, quote: String?) -> some View {
        GeometryReader { g in
            let measure = min(TextStyle.measure(chars: 42), TextStyle.maxMeasure())
            let w = max(260, min(measure, g.size.width))
            ScrollView(.vertical) {
                BookTextView(attr: attributed(text, quote: quote), width: w)
                    .frame(width: w, alignment: .leading)
                    .padding(.bottom, 24)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .frame(maxHeight: .infinity)
    }

    private func attributed(_ text: String, quote: String?) -> NSAttributedString {
        let base = TextStyle.attributed(text, color: NSColor(ink), alignment: .justified)
        guard let q = quote, !q.isEmpty, let r = text.range(of: q) else { return base }
        let nsr = NSRange(r, in: text)
        guard nsr.location != NSNotFound, nsr.length > 0 else { return base }
        let m = NSMutableAttributedString(attributedString: base)
        m.addAttribute(
            .backgroundColor,
            value: NSColor(accent).withAlphaComponent(0.20), range: nsr)
        return m
    }
}
