// swift-tools-version:6.4
import PackageDescription

/// SandCore — the single source of truth for the Mentat sand surface.
///
/// Both the shipping app (`MentatApp`) and the tuning harness (`SandLab`) depend
/// on this package, and both `build.sh` scripts compile `SandShaders.metal` from
/// here into their bundle's `default.metallib`. That keeps one shader and one
/// parameter vocabulary (`SandConfig`) shared across app and lab, so a change
/// prototyped in the lab is the same code that ships.
let package = Package(
    name: "SandCore",
    platforms: [.macOS(.v27)],
    products: [.library(name: "SandCore", targets: ["SandCore"])],
    targets: [
        .target(
            name: "SandCore",
            path: "Sources/SandCore",
            exclude: ["SandShaders.metal"])
    ]
)
