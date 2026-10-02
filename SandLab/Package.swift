// swift-tools-version:6.4
import PackageDescription

let package = Package(
    name: "SandLab",
    platforms: [.macOS(.v27)],
    dependencies: [.package(path: "../SandCore")],
    targets: [
        .executableTarget(
            name: "SandLab",
            dependencies: [.product(name: "SandCore", package: "SandCore")],
            path: "Sources/SandLab")
    ]
)
