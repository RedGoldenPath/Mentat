import Foundation
import os

/// Lightweight performance instrumentation: signposts for Instruments plus
/// counters/timings for the `/debug` HUD.
///
/// Counters are lock-guarded and deliberately **not** observable, so calling
/// them from a view body can never create a render loop.
enum Perf {
    static let log = OSLog(subsystem: "ai.mentat.app", category: .pointsOfInterest)

    private static let lock = NSLock()
    nonisolated(unsafe) private static var counts: [String: Int] = [:]
    nonisolated(unsafe) private static var timings: [String: Double] = [:]

    /// Wrap a synchronous block in an Instruments signpost span.
    static func span<T>(_ name: StaticString, _ body: () -> T) -> T {
        let id = OSSignpostID(log: log)
        os_signpost(.begin, log: log, name: name, signpostID: id)
        defer { os_signpost(.end, log: log, name: name, signpostID: id) }
        return body()
    }

    /// Bump a counter (e.g. a row render).
    static func count(_ name: String, _ n: Int = 1) {
        lock.lock()
        counts[name, default: 0] += n
        lock.unlock()
    }

    /// Record the latest duration (ms) for a named operation.
    static func record(_ name: String, ms: Double) {
        lock.lock()
        timings[name] = ms
        lock.unlock()
    }

    /// Time a synchronous block and record its duration.
    @discardableResult
    static func time<T>(_ name: String, _ body: () -> T) -> T {
        let start = CFAbsoluteTimeGetCurrent()
        let out = body()
        record(name, ms: (CFAbsoluteTimeGetCurrent() - start) * 1000)
        return out
    }

    static func snapshot() -> (counts: [String: Int], timings: [String: Double]) {
        lock.lock()
        defer { lock.unlock() }
        return (counts, timings)
    }

    static func reset() {
        lock.lock()
        counts.removeAll()
        timings.removeAll()
        lock.unlock()
    }
}
