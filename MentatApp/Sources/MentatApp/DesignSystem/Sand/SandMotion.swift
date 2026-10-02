import CoreGraphics

/// The couplings that let the sand rest, then move only when the interface is
/// touched — then settle. Produced by `SandMotionStore`; the renderer takes one
/// immutable value per frame.
struct SandMotion: Equatable {
    /// Pointer offset from centre, in points (small).
    var parallax: CGSize = .zero
    /// Shift of the amber mass (e.g. a panel opening).
    var glowShift: Double = 0
    /// Streaming breathing (0…1).
    var breath: Double = 0
    /// One-shot gust (0…1) — send / big moves.
    var gust: Double = 0
    /// Translational nudge of the dune field, in points.
    var shift: CGSize = .zero
    /// Horizontal shear (top vs bottom) — scroll / panels.
    var shear: Double = 0
    /// Brightness bloom (0…1) — mode change / send.
    var pulse: Double = 0

    static let rest = SandMotion()
}
