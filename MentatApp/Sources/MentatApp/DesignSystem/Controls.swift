import AppKit
import SwiftUI

/// A Liquid-Glass-style press: the control dips and dims a hair, springing back
/// on release. Applied broadly so every tappable thing responds.
struct Pressable: ButtonStyle {
    var scale: CGFloat = 0.955
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? scale : 1)
            .opacity(configuration.isPressed ? 0.88 : 1)
            .animation(Anim.interactive, value: configuration.isPressed)
    }
}

extension ButtonStyle where Self == Pressable {
    static var pressable: Pressable { Pressable() }
}

extension View {
    /// Apple's Liquid Glass control treatment: the system glass button style with
    /// a *semantic* control size and border shape, so the metrics (radius,
    /// padding, height) come from the system exactly as Apple's own apps get
    /// them — no fixed frames, no hand-set corner radii. Tint drives the accent.
    @ViewBuilder
    func glassControl(
        _ size: ControlSize = .regular,
        shape: ButtonBorderShape = .automatic,
        prominent: Bool = false,
        tint: Color? = nil
    ) -> some View {
        let base = self.controlSize(size).buttonBorderShape(shape)
        Group {
            if prominent { base.buttonStyle(.glassProminent) } else { base.buttonStyle(.glass) }
        }
        .tint(tint)
    }
}

/// Fades/scales the whole window in on launch, so opening the app has a soft
/// Liquid-Glass materialise rather than a hard pop.
struct AppearIn: ViewModifier {
    @State private var on = false
    func body(content: Content) -> some View {
        content
            .opacity(on ? 1 : 0)
            .scaleEffect(on ? 1 : 0.985)
            .onAppear { withAnimation(.easeOut(duration: 0.42)) { on = true } }
    }
}

struct ThemeToggleButton: View {
    @AppStorage("appearance") private var appearanceRaw = AppTheme.fallback.rawValue
    @Environment(\.palette) private var pal

    private var appearance: AppTheme { AppTheme(rawValue: appearanceRaw) ?? .fallback }

    var body: some View {
        Button {
            appearanceRaw = appearance.next.rawValue
        } label: {
            Image(systemName: appearance.symbol)
                .font(.system(size: 13, weight: .medium))
                .frame(width: 30, height: 30)
        }
        .buttonStyle(.glass)
        .foregroundStyle(pal.text)
        .help("Appearance: \(appearance.label) — click to switch (Hue ↔ Noir)")
    }
}

/// Floating glass panel — real Liquid Glass material (`glassEffect`) with a
/// refractive surface and a soft shadow. Honors Reduce Transparency.
struct GlassPanel: ViewModifier {
    @Environment(\.palette) private var pal
    @Environment(\.colorTheme) private var colorTheme
    @Environment(\.glassStyle) private var glassStyle
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    var corner: CGFloat
    func body(content: Content) -> some View {
        let shape = RoundedRectangle(cornerRadius: corner, style: .continuous)
        if reduceTransparency {
            return AnyView(
                content
                    .background(pal.bg2.opacity(0.96), in: shape)
                    .overlay(
                        shape.stroke(Color.white.opacity(pal.isDark ? 0.12 : 0.35), lineWidth: 1)
                            .allowsHitTesting(false)
                    )
                    .shadow(color: .black.opacity(pal.isDark ? 0.42 : 0.20), radius: 24, y: 12))
        }
        var glass = Glass.regular
        if colorTheme != .placeholder {
            glass = glass.tint(
                glassStyle == .clear ? colorTheme.clearTint : colorTheme.accentTint)
        }
        return AnyView(
            content
                .glassEffect(glass, in: shape)
                .shadow(color: .black.opacity(pal.isDark ? 0.34 : 0.18), radius: 22, y: 10))
    }
}

extension View {
    func glassPanel(corner: CGFloat = 26) -> some View { modifier(GlassPanel(corner: corner)) }
}

/// Frosted capsule segmented control — a glass track with a sliding glass
/// thumb behind the active option (the "pill" from the Liquid-Glass references).
struct GlassSegmented: View {
    let options: [AppTheme]
    @Binding var selection: AppTheme
    @Environment(\.palette) private var pal
    @Environment(\.colorTheme) private var colorTheme
    @Namespace private var ns

    var body: some View {
        HStack(spacing: 3) {
            ForEach(options) { opt in
                let active = opt == selection
                Button {
                    withAnimation(Anim.snappy) { selection = opt }
                } label: {
                    Text(opt.label)
                        .font(.system(size: 12, weight: .medium))
                        .lineLimit(1)
                        .fixedSize(horizontal: true, vertical: false)
                        .foregroundStyle(active ? colorTheme.accent : pal.text.opacity(0.72))
                        .padding(.vertical, 7).padding(.horizontal, 10)
                        .frame(maxWidth: .infinity)
                        .background {
                            if active {
                                Capsule(style: .continuous)
                                    .fill(.ultraThinMaterial)
                                    .overlay(
                                        Capsule().fill(
                                            colorTheme.accent.opacity(pal.isDark ? 0.16 : 0.20))
                                    )
                                    .overlay(
                                        Capsule(style: .continuous).stroke(
                                            LinearGradient(
                                                colors: [
                                                    Color.white.opacity(pal.isDark ? 0.38 : 0.8),
                                                    Color.white.opacity(0.05),
                                                ],
                                                startPoint: .top, endPoint: .bottom),
                                            lineWidth: 1)
                                    )
                                    .shadow(
                                        color: .black.opacity(pal.isDark ? 0.40 : 0.18), radius: 5,
                                        y: 2
                                    )
                                    .matchedGeometryEffect(id: "seg", in: ns)
                            }
                        }
                        .contentShape(Capsule())
                }
                .buttonStyle(.plain)
            }
        }
        .padding(4)
        .background(Capsule(style: .continuous).fill(.ultraThinMaterial))
        .overlay(
            Capsule(style: .continuous)
                .stroke(Color.white.opacity(pal.isDark ? 0.16 : 0.35), lineWidth: 1)
        )
        .shadow(color: .black.opacity(pal.isDark ? 0.35 : 0.14), radius: 10, y: 4)
    }
}

/// Applies the chosen appearance to the SwiftUI content AND the window/titlebar.
struct AppearanceModifier: ViewModifier {
    @AppStorage("appearance") private var raw = AppTheme.fallback.rawValue
    private var theme: AppTheme { AppTheme(rawValue: raw) ?? .fallback }

    func body(content: Content) -> some View {
        content
            .preferredColorScheme(theme.colorScheme)
            .onAppear { apply() }
            .onChange(of: raw) { _, _ in apply() }
    }

    private func apply() {
        NSApp.appearance = NSAppearance(named: theme == .hue ? .aqua : .darkAqua)
    }
}

extension View {
    func applyAppearance() -> some View { modifier(AppearanceModifier()) }
}

/// Pins the hosting window's appearance so the system materials / Liquid Glass
/// never re-resolve against the *system* light/dark scheme while the window is
/// inactive. macOS otherwise flips vibrancy when the app loses focus, which is
/// why the tint used to change every time you clicked off the app. Re-asserted
/// on key/main changes because AppKit can reset a window's appearance there.
struct WindowAppearance: NSViewRepresentable {
    var theme: AppTheme

    // TRANSITIONAL: main-thread-only coordinator (AppKit window appearance).
    final class Coordinator: @unchecked Sendable {
        var theme: AppTheme = .fallback
        var observers: [NSObjectProtocol] = []
        @MainActor func apply(to view: NSView) {
            guard let w = view.window else { return }
            let name: NSAppearance.Name = theme == .hue ? .aqua : .darkAqua
            if w.appearance?.name != name { w.appearance = NSAppearance(named: name) }
        }
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeNSView(context: Context) -> NSView {
        let v = NSView()
        let coord = context.coordinator
        coord.theme = theme
        let c = NotificationCenter.default
        let names: [Notification.Name] = [
            NSWindow.didBecomeKeyNotification,
            NSWindow.didResignKeyNotification,
            NSWindow.didBecomeMainNotification,
            NSWindow.didResignMainNotification,
        ]
        coord.observers = names.map { n in
            c.addObserver(forName: n, object: nil, queue: .main) { [weak v] _ in
                guard let v else { return }
                MainActor.assumeIsolated { coord.apply(to: v) }
            }
        }
        DispatchQueue.main.async { MainActor.assumeIsolated { coord.apply(to: v) } }
        return v
    }

    func updateNSView(_ v: NSView, context: Context) {
        let coord = context.coordinator
        coord.theme = theme
        DispatchQueue.main.async { MainActor.assumeIsolated { coord.apply(to: v) } }
    }
}
