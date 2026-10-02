import CoreGraphics
import Foundation
import Observation
import QuartzCore
import simd

/// A UI event that briefly nudges the sand. Any feature can emit one through
/// the `\.sandMotion` environment value without touching the shell.
enum SandEvent: Equatable {
    case send
    case panel(SandEdge, open: Bool)
    case scroll(dy: Double)
    case modeChange
    case resize(dx: Double, dy: Double)
    case pulse
}

enum SandEdge: Equatable { case leading, trailing }

/// One decaying nudge. Motion is the **sum of decaying impulses** (WWDC18
/// *Designing Fluid Interfaces*: behaviours that settle to a resting state) —
/// so the renderer is a pure function of time and nothing needs a timer per
/// frame.
struct SandImpulse {
    var start: TimeInterval
    var tau: Double
    var shift: CGSize = .zero
    var shear: Double = 0
    var gust: Double = 0
    var pulse: Double = 0
    var glowShift: Double = 0
    /// An optional moving solid (a UI element) the dust flows around: its rect
    /// in uv at rest (x, y, w, h), and how far it slides over the event.
    var solid: SIMD4<Float>? = nil
    var solidTravel: SIMD2<Float> = .zero

    /// 1 at the moment of the event, easing to 0 (exponential, framerate-free).
    func decay(at t: TimeInterval) -> Double {
        let dt = t - start
        guard dt >= 0 else { return 0 }
        return exp(-dt / max(0.05, tau))
    }
}

/// Drives the sand from UI events **and the pointer**. Stateless per frame; the
/// only observed state is `isActive`, which flips the render cadence (active ↔
/// idle) so the surface runs at display rate while touched and eases back.
@MainActor
@Observable
final class SandMotionStore {
    /// True while a recent event should run the sand at its active cadence.
    private(set) var isActive = false

    // Read every frame by the renderer (never observed → no view churn).
    @ObservationIgnored private(set) var parallax: CGSize = .zero
    @ObservationIgnored private(set) var breath: Double = 0
    /// Pointer position in normalized view coordinates (y down) + its per-event
    /// velocity, for the fluid splat.
    @ObservationIgnored private(set) var pointer: SIMD2<Float> = .zero
    @ObservationIgnored private(set) var pointerVelocity: SIMD2<Float> = .zero
    @ObservationIgnored private(set) var hasPointer = false
    @ObservationIgnored private var lastPointer: SIMD2<Float>?

    @ObservationIgnored private var impulses: [SandImpulse] = []
    @ObservationIgnored private var lastEventAt: TimeInterval = -.greatestFiniteMagnitude
    @ObservationIgnored private var idleTask: Task<Void, Never>?

    /// How long after the last event the sand drops to the idle cadence.
    var idleWindow: TimeInterval = 2.5
    /// Global gain on event nudges (data-driven from tokens).
    var impulseScale: Double = 1.0
    /// Bound memory: keep only the freshest impulses.
    var maxImpulses = 24

    /// Apply token configuration.
    func configure(_ t: DesignTokens.Sand) {
        idleWindow = max(0.2, t.idleWindow)
        impulseScale = max(0, t.impulseScale)
    }

    // MARK: Continuous couplings

    func setBreath(_ v: Double) { breath = max(0, min(1, v)) }

    /// Pointer moved: record the normalized position + velocity and wake the
    /// surface to the active cadence.
    func setPointer(_ p: CGPoint, in size: CGSize) {
        guard size.width > 1, size.height > 1 else { return }
        let uv = SIMD2<Float>(Float(p.x / size.width), Float(p.y / size.height))
        pointerVelocity = lastPointer.map { uv - $0 } ?? .zero
        lastPointer = uv
        pointer = uv
        hasPointer = true
        // Pointer offset from centre drives the parallax split (small, uv).
        parallax = CGSize(width: Double(uv.x - 0.5), height: Double(uv.y - 0.5))
        wake()
    }
    func clearPointer() {
        hasPointer = false
        pointerVelocity = .zero
        lastPointer = nil
        parallax = .zero
    }

    // MARK: Events

    func emit(_ event: SandEvent, at now: TimeInterval = CACurrentMediaTime()) {
        let imp = impulse(for: event, at: now)
        impulses.append(imp)
        if impulses.count > maxImpulses {
            impulses.removeFirst(impulses.count - maxImpulses)
        }
        lastEventAt = now
        if !isActive { isActive = true }
        // Big moves keep the surface awake longer; small ones only briefly.
        let window = min(idleWindow, max(0.75, imp.tau * 1.5))
        scheduleIdle(after: now + window)
    }

    /// Keep the surface at the active cadence without a visible nudge.
    func wake() {
        let now = CACurrentMediaTime()
        lastEventAt = now
        if !isActive { isActive = true }
        scheduleIdle(after: now + idleWindow)
    }

    /// Sum of decaying impulses + the continuous couplings. Pure; safe to call
    /// every frame.
    func motion(at now: TimeInterval = CACurrentMediaTime()) -> SandMotion {
        var shiftW = 0.0, shiftH = 0.0, shear = 0.0, gust = 0.0, pulse = 0.0, glow = 0.0
        for imp in impulses {
            let d = imp.decay(at: now)
            if d < 0.001 { continue }
            shiftW += imp.shift.width * d
            shiftH += imp.shift.height * d
            shear += imp.shear * d
            gust += imp.gust * d
            pulse += imp.pulse * d
            glow += imp.glowShift * d
        }
        return SandMotion(
            parallax: parallax,
            glowShift: glow,
            breath: breath,
            gust: min(2.0, gust),
            shift: CGSize(width: shiftW, height: shiftH),
            shear: shear,
            pulse: min(1.6, pulse))
    }

    // MARK: Amplitude ladder — calm by default, bigger only for big moves.

    private func impulse(for event: SandEvent, at now: TimeInterval) -> SandImpulse {
        let g = impulseScale
        switch event {
        case .send:
            return SandImpulse(start: now, tau: 1.25,
                               shift: CGSize(width: 0, height: 60 * g),
                               shear: 0.16 * g, gust: 1.25 * g, pulse: 0.50 * g,
                               solid: SIMD4(0.35, 0.78, 0.30, 0.24),
                               solidTravel: SIMD2(0, 0.18))
        case .panel(let edge, let open):
            let dir: Double = edge == .trailing ? -1 : 1
            let s: Double = open ? 1 : -1
            let x: Float = edge == .trailing ? 0.84 : 0.0
            return SandImpulse(start: now, tau: 1.30,
                               shift: CGSize(width: dir * s * 110 * g, height: 0),
                               shear: dir * s * 0.80 * g, glowShift: dir * s * 130 * g,
                               solid: SIMD4(x, 0.14, 0.16, 0.72),
                               solidTravel: SIMD2(Float(dir) * 0.16, 0))
        // Global transitions are FORCES now, not walls: a full-span collider
        // captures every mote and parks it on a line (the old border-pooling
        // bug). The dust is pushed instead, and no wall can trap it.
        case .scroll(let dy):
            return SandImpulse(start: now, tau: 0.55,
                               shift: CGSize(width: 0, height: max(-26, min(26, dy * 0.35)) * g),
                               shear: max(-0.35, min(0.35, dy * 0.010)) * g)
        case .modeChange:
            return SandImpulse(start: now, tau: 1.10,
                               shift: CGSize(width: 0, height: -34 * g), pulse: 0.80 * g)
        case .resize(let dx, let dy):
            return SandImpulse(start: now, tau: 1.00,
                               shift: CGSize(width: max(-56, min(56, -dx * 0.35)) * g,
                                             height: max(-56, min(56, -dy * 0.35)) * g))
        case .pulse:
            return SandImpulse(start: now, tau: 0.85, pulse: 0.5 * g)
        }
    }

    /// The moving solids (UI rects in uv) currently in play, for the dust's
    /// collision pass. Pure; safe to call every frame.
    func solids(at now: TimeInterval = CACurrentMediaTime()) -> [SIMD4<Float>] {
        var rects: [SIMD4<Float>] = []
        for imp in impulses {
            guard let base = imp.solid, rects.count < 16 else { continue }
            // Defensive: a collider must never span the domain or a full axis —
            // that is what traps the dust into a line. Global events are forces.
            if base.z >= 0.98 || base.w >= 0.98 { continue }
            let d = imp.decay(at: now)
            if d < 0.05 { continue }
            let k = Float(1 - d)
            rects.append(SIMD4(base.x + imp.solidTravel.x * k,
                               base.y + imp.solidTravel.y * k,
                               base.z, base.w))
        }
        return rects
    }

    // MARK: Idle cadence

    private func scheduleIdle(after deadline: TimeInterval) {
        idleTask?.cancel()
        let delay = max(0, deadline - CACurrentMediaTime())
        idleTask = Task { @MainActor [weak self] in
            try? await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))
            guard let self, !Task.isCancelled else { return }
            if CACurrentMediaTime() - self.lastEventAt >= self.idleWindow {
                self.isActive = false
            }
        }
    }
}
