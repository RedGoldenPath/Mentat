// swift-tools-version:6.4
import PackageDescription

let package = Package(
    name: "MentatApp",
    platforms: [.macOS(.v27)],
    targets: [
        .executableTarget(name: "MentatApp", path: "Sources/MentatApp"),
        .testTarget(name: "MentatAppTests", dependencies: ["MentatApp"], path: "Tests/MentatAppTests")
    ]
)
