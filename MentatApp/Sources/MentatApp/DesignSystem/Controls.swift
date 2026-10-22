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

/// Floating glass panel — real Liquid Glass material (`glassEffect`) with a
/// refractive surface and a soft shadow. Honors Reduce Transparency.
struct GlassPanel: ViewModifier {
    @Environment(\.palette) private var pal
    @Environment(\.colorTheme) private var colorTheme
    @Environment(\.glassStyle) private var glassStyle
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    var corner: CGFloat
    @ViewBuilder
    func body(content: Content) -> some View {
        let shape = RoundedRectangle(cornerRadius: corner, style: .continuous)
        if reduceTransparency {
            content
                .background(pal.bg2.opacity(0.96), in: shape)
                .overlay(
                    shape.stroke(Color.white.opacity(pal.isDark ? 0.12 : 0.35), lineWidth: 1)
                        .allowsHitTesting(false)
                )
                .shadow(color: .black.opacity(pal.isDark ? 0.42 : 0.20), radius: 24, y: 12)
        } else {
            let glass =
                colorTheme != .placeholder
                ? Glass.regular.tint(
                    glassStyle == .clear ? colorTheme.clearTint : colorTheme.accentTint)
                : Glass.regular
            content
                .glassEffect(glass, in: shape)
                .shadow(color: .black.opacity(pal.isDark ? 0.34 : 0.18), radius: 22, y: 10)
        }
    }
}

extension View {
    func glassPanel(corner: CGFloat = 26) -> some View { modifier(GlassPanel(corner: corner)) }
}

/// Applies the **effective** look's light/dark to the SwiftUI content AND the
/// window/titlebar, so the window follows `ColorTheme` (the one colour authority)
/// rather than a separate appearance flag.
struct AppearanceModifier: ViewModifier {
    var isDark: Bool

    func body(content: Content) -> some View {
        content
            .preferredColorScheme(isDark ? .dark : .light)
            .onAppear { apply() }
            .onChange(of: isDark) { _, _ in apply() }
    }

    private func apply() {
        // Never mutate global appearance *during* a SwiftUI layout/display pass —
        // AppKit throws from `_postWindowNeedsUpdateConstraints` and the app dies
        // (EXC_BREAKPOINT, `_crashOnException`). Defer to the next runloop and only
        // touch it when the value actually changed. Same pattern as HideTrafficLights.
        let name: NSAppearance.Name = isDark ? .darkAqua : .aqua
        DispatchQueue.main.async {
            if NSApp.appearance?.name != name { NSApp.appearance = NSAppearance(named: name) }
        }
    }
}

extension View {
    func applyAppearance(isDark: Bool) -> some View { modifier(AppearanceModifier(isDark: isDark)) }
}

/// Reports the window's top safe-area inset (titlebar band) so the grid can sit
/// below it. Reads `NSView.safeAreaInsets` and falls back to the traffic-light
/// height when the system reports zero. Reference: Apple HIG *Layout* + AppKit
/// `NSView.safeAreaInsets`.
struct TopInsetReader: NSViewRepresentable {
    var onChange: (CGFloat) -> Void

    final class Coordinator { var last: CGFloat? }

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeNSView(context: Context) -> NSView {
        let v = NSView()
        DispatchQueue.main.async { report(v, context.coordinator) }
        return v
    }

    func updateNSView(_ v: NSView, context: Context) {
        // Report only when the value actually changes — reporting on *every*
        // update wrote `engine.topInset` (an @Observable) unconditionally, which
        // re-invalidated the view graph and looped forever (redraw storm + crash
        // window). Guarded + change-only here.
        DispatchQueue.main.async { report(v, context.coordinator) }
    }

    private func report(_ v: NSView, _ coord: Coordinator) {
        guard let w = v.window else { return }
        let safe = w.contentView?.safeAreaInsets.top ?? 0
        // A hidden-titlebar window often reports 0, so fall back to the standard
        // traffic-light band height (Apple's ~28pt) rather than clipping.
        let value: CGFloat = safe > 1 ? safe : 28
        guard coord.last != value else { return }
        coord.last = value
        onChange(value)
    }
}

/// Pins the hosting window's appearance so the system materials / Liquid Glass
/// resolve against the app's own light/dark scheme rather than the *system*
/// scheme while the window is inactive. Note: this does NOT (and cannot) stop
/// the platform from desaturating tinted glass in a non-key window — that is
/// Liquid Glass's intended active/inactive behaviour. Re-asserted on key/main
/// changes because AppKit can reset a window's appearance there.
struct WindowAppearance: NSViewRepresentable {
    var isDark: Bool

    // TRANSITIONAL: main-thread-only coordinator (AppKit window appearance).
    final class Coordinator: @unchecked Sendable {
        var isDark = true
        var observers: [NSObjectProtocol] = []
        @MainActor func apply(to view: NSView) {
            guard let w = view.window else { return }
            let name: NSAppearance.Name = isDark ? .darkAqua : .aqua
            if w.appearance?.name != name { w.appearance = NSAppearance(named: name) }
        }
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeNSView(context: Context) -> NSView {
        let v = NSView()
        let coord = context.coordinator
        coord.isDark = isDark
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
        coord.isDark = isDark
        DispatchQueue.main.async { MainActor.assumeIsolated { coord.apply(to: v) } }
    }

    static func dismantleNSView(_ v: NSView, coordinator: Coordinator) {
        // Remove the NotificationCenter observers — otherwise they (and the
        // coordinator) leak for the app's lifetime.
        for o in coordinator.observers { NotificationCenter.default.removeObserver(o) }
        coordinator.observers.removeAll()
    }
}
