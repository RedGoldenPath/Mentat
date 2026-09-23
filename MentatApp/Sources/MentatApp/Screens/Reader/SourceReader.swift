import AppKit
import SwiftUI

/// Full-height source reader: a tapped citation resolved to its verbatim
/// passage. The quote is the focal card; the wider window is readable in
/// context. Back (or Esc, handled by the host) returns to the answer.
///
/// The plate is deliberately *not* glass. Over a loud photograph the accent
/// glass tint left the prose illegible, so the plate instead takes the *inverse*
/// luminance of the artwork behind it (bright art → dark plate, dark art → light
/// plate) along with the art's complementary hue, near-opaque so the photo can't
/// wash the text out. That keeps the pop-up readable on any background.
struct SourceReader: View {
    let engine: Engine
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private struct Contrast {
        let artIsLight: Bool
        let surface: Color
        let card: Color
        let ink: Color
        let dim: Color
    }

    private var contrast: Contrast {
        let artIsLight = engine.bgLightCenter
        let hue = complementHue
        if artIsLight {
            // bright art behind → deep plate in the opposite temperature
            return Contrast(
                artIsLight: true,
                surface: plate(hue, sat: 0.24, brightness: 0.12),
                card: plate(hue, sat: 0.30, brightness: 0.20),
                ink: Color(white: 0.98),
                dim: Color(white: 0.70))
        }
        // dark art behind → bright plate in the opposite temperature
        return Contrast(
            artIsLight: false,
            surface: plate(hue, sat: 0.16, brightness: 0.97),
            card: plate(hue, sat: 0.22, brightness: 0.90),
            ink: Color(white: 0.07),
            dim: Color(white: 0.40))
    }

    /// The opposite-temperature hue of the artwork behind the plate — nil for
    /// grey art, which stays neutral so no phantom hue appears.
    private var complementHue: CGFloat? {
        guard engine.bgRegionAvg.count > 1 else { return nil }
        let c = engine.bgRegionAvg[1]
        guard ColorTheory.temperature(c) != .neutral else { return nil }
        return ColorTheory.contrastingHue(c)
    }

    private func plate(_ hue: CGFloat?, sat: Double, brightness: Double) -> Color {
        if let hue {
            return Color(hue: Double(hue), saturation: sat, brightness: brightness, opacity: 0.95)
        }
        return Color(white: brightness, opacity: 0.95)
    }

    private var accent: Color { engine.accentColor(.center) }

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
        let c = contrast
        return VStack(alignment: .leading, spacing: 16) {
            header(c)
            Rectangle().fill(c.dim.opacity(0.22)).frame(height: 1)
            content(c)
        }
        .padding(22)
        .frame(maxWidth: 1040, maxHeight: .infinity, alignment: .topLeading)
        .background(
            c.surface,
            in: RoundedRectangle(cornerRadius: ChromeShape.radiusL, style: .continuous)
        )
        .overlay(
            RoundedRectangle(cornerRadius: ChromeShape.radiusL, style: .continuous)
                .strokeBorder(c.ink.opacity(0.10), lineWidth: 1))
        .shadow(color: .black.opacity(c.artIsLight ? 0.40 : 0.30), radius: 30, y: 16)
    }

    private func header(_ c: Contrast) -> some View {
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
                    .font(.system(size: TypeScale.title, weight: .semibold)).foregroundStyle(c.ink)
                if let loc = engine.readerSource?.loc, !loc.isEmpty {
                    Text(loc).font(.system(size: TypeScale.caption)).foregroundStyle(c.dim)
                }
            }
        }
    }

    @ViewBuilder private func content(_ c: Contrast) -> some View {
        if engine.readerLoading {
            HStack(spacing: 10) {
                ProgressView().controlSize(.small)
                Text("Finding the source…").font(.callout).foregroundStyle(c.dim)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if engine.readerFailed {
            VStack(spacing: 8) {
                Image(systemName: "text.book.closed")
                    .font(.system(size: 24)).foregroundStyle(c.dim)
                Text("Couldn't locate that passage").font(.callout).foregroundStyle(c.ink)
                Text("The index may not carry this edition yet.")
                    .font(.caption).foregroundStyle(c.dim)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if let src = engine.readerSource, let text = src.text, !text.isEmpty {
            VStack(alignment: .leading, spacing: 18) {
                if let q = src.quote, !q.isEmpty { quoteCard(q, c) }
                passage(text, quote: src.quote, c)
            }
        }
    }

    /// The one solid focal: the exact sentence the citation points at.
    private func quoteCard(_ q: String, _ c: Contrast) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: "quote.opening")
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(accent.opacity(0.90))
                .padding(.top, 2)
            Text(q)
                .font(.system(size: 16, design: .serif))
                .foregroundStyle(c.ink)
                .lineSpacing(3)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
        }
        .padding(.horizontal, 16).padding(.vertical, 14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            c.card,
            in: RoundedRectangle(cornerRadius: ChromeShape.radiusM, style: .continuous))
    }

    /// The surrounding book text, set in reading columns (1 → 2 → 3) with the
    /// same pager the answer body uses, so a long passage pages rather than
    /// stretching one narrow strip.
    private func passage(_ text: String, quote: String?, _ c: Contrast) -> some View {
        GeometryReader { g in
            let w = max(260, min(1200, g.size.width))
            ColumnText(
                text: text, color: c.ink, availableWidth: w,
                showsPager: true, highlight: quote
            )
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .frame(maxHeight: .infinity)
    }
}
