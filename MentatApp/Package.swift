// swift-tools-version:6.4
import PackageDescription

let package = Package(
    name: "MentatApp",
    platforms: [.macOS(.v27)],
    dependencies: [.package(path: "../SandCore")],
    targets: [
        .executableTarget(
            name: "MentatApp",
            dependencies: [.product(name: "SandCore", package: "SandCore")],
            path: "Sources/MentatApp"),
        .testTarget(name: "MentatAppTests", dependencies: ["MentatApp"], path: "Tests/MentatAppTests")
    ]
)
