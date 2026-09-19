import Foundation

/// Carries a value that isn't `Sendable` (e.g. `NSImage`) across an isolation
/// boundary in cases where we know the access is read-only. Prefer a real
/// `Sendable` type; use this only as a last resort at a measured seam.
struct Unchecked<T>: @unchecked Sendable {
    let value: T
    init(_ value: T) { self.value = value }
}
