import SwiftUI

/// The seam that lets any feature nudge the sand without editing the shell —
/// same idea as the `\.slots` registry. `RootView` provides the store; a view
/// emits with `@Environment(\.sandMotion) private var sand` → `sand?.emit(.send)`.
///
/// The store is a `@MainActor` class, hence `Sendable`, so it is safe to carry
/// in the environment (a raw closure is not).
private struct SandMotionKey: EnvironmentKey {
    static let defaultValue: SandMotionStore? = nil
}

extension EnvironmentValues {
    var sandMotion: SandMotionStore? {
        get { self[SandMotionKey.self] }
        set { self[SandMotionKey.self] = newValue }
    }
}
