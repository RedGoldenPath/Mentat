import SwiftUI

/// The app's motion language, driven by `DesignTokens.motion` (data, not
/// literals). macOS 27 only, so no availability gates.
enum Anim {
    private static var m: DesignTokens.Motion { DesignTokens.current.motion }

    static var interactive: Animation { .interactiveSpring() }
    static var smooth: Animation { .smooth(duration: m.smoothDuration) }
    static var snappy: Animation {
        .snappy(duration: m.snappyDuration, extraBounce: m.snappyBounce)
    }

    /// Bouncy spring whose duration scales with how much text arrived — a long
    /// answer grows with a slower, weightier spring than a one-liner.
    static func bubble(_ delta: Int) -> Animation {
        let d: Double = delta > 400 ? 0.50 : (delta > 120 ? 0.40 : (delta > 24 ? 0.32 : 0.24))
        return .bouncy(duration: d, extraBounce: m.bubbleBounce)
    }
}
