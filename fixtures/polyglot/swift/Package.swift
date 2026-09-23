// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "App",
    dependencies: [
        .package(url: "https://github.com/vapor/vapor.git", from: "4.0.0"),
    ],
    targets: [
        .executableTarget(name: "App", dependencies: ["Vapor"]),
    ]
)
