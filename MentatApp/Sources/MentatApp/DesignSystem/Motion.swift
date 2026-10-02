import SwiftUI

/// The app's motion language, driven by `DesignTokens.motion` (data, not
/// literals). macOS 27 only, so no availability gates.
///
/// Grounded in Apple's motion guidance:
/// - **SwiftUI spring presets** (`.smooth`/`.snappy`/`.bouncy`/`.interactiveSpring`)
///   rather than hand-tuned curves — Apple "Designing Fluid Interfaces" (WWDC18):
///   motion should be interruptible and follow velocity, not a fixed duration.
/// - **Two registers**: `interactive` for anything under the finger (press,
///   hover), `smooth`/`snappy` for chrome, `bubble` for content arriving.
/// - **Symbol + content transitions** (`.symbolEffect`, `.contentTransition`)
///   carry state changes, so the *glyph* animates rather than the container.
enum Anim {
    private static var m: DesignTokens.Motion { DesignTokens.current.motion }

    static var interactive: Animation { .interactiveSpring() }
    static var smooth: Animation { .smooth(duration: m.smoothDuration) }
    static var snappy: Animation {
        .snappy(duration: m.snappyDuration, extraBounce: m.snappyBounce)
    }

    /// Airy settle for panels/bars that should feel physical but calm.
    static var gentle: Animation { .smooth(duration: 0.34) }
    /// A touch of overshoot for confirmations (copy, pin, toggle on).
    static var pop: Animation { .snappy(duration: 0.24, extraBounce: 0.18) }

    /// Bouncy spring whose duration scales with how much text arrived — a long
    /// answer grows with a slower, weightier spring than a one-liner.
    static func bubble(_ delta: Int) -> Animation {
        let d: Double = delta > 400 ? 0.50 : (delta > 120 ? 0.40 : (delta > 24 ? 0.32 : 0.24))
        return .bouncy(duration: d, extraBounce: m.bubbleBounce)
    }
}

extension View {
    /// Reduce-Motion-aware animation. Prefer this over a bare `.animation` so the
    /// accessibility setting is honoured in one place (Apple HIG "Accessibility —
    /// Reduce motion").
    func motion<V: Equatable>(_ animation: Animation?, value: V) -> some View {
        modifier(MotionModifier(animation: animation, value: value))
    }
}

private struct MotionModifier<V: Equatable>: ViewModifier {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    let animation: Animation?
    let value: V
    func body(content: Content) -> some View {
        content.animation(reduceMotion ? nil : animation, value: value)
    }
}
