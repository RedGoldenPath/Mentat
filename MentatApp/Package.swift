// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "MentatApp",
    platforms: [.macOS(.v13)],
    targets: [
        .executableTarget(name: "MentatApp", path: "Sources/MentatApp")
    ]
)
