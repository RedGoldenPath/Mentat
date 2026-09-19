import Foundation

/// Health of the local engine.
struct EngineHealth: Equatable {
    var online: Bool
    var model: String
    static let offline = EngineHealth(online: false, model: "")
}

/// Owns the app-owned Python engine: where it lives, launching it on demand, and
/// reporting health. The engine is the only source of answers — the app never
/// embeds the brain, it just starts it and talks to it over localhost.
///
/// An actor so the `Engine` (MainActor) can hand work across the boundary
/// without sending non-Sendable state.
actor EngineProcess {
    /// The local engine's address.
    static let baseURL = URL(string: "http://127.0.0.1:8765")!

    /// Where the Python brain lives on disk (`~/Everything/mentat/app`).
    let appDir: URL
    let port: Int
    /// Kept alive for the process lifetime once launched.
    private var process: Process?

    var python: URL { appDir.appendingPathComponent(".venv/bin/python") }
    var server: URL { appDir.appendingPathComponent("server.py") }

    static func `default`() -> EngineProcess {
        let app = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Everything/mentat/app")
        return EngineProcess(appDir: app, port: 8765)
    }

    init(appDir: URL, port: Int = 8765) {
        self.appDir = appDir
        self.port = port
    }

    /// Ping `/status`. Never throws — an unreachable engine is simply offline.
    func health() async -> EngineHealth {
        do {
            let url = Self.baseURL.appendingPathComponent("status")
            let (data, _) = try await URLSession.shared.data(from: url)
            let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any]
            return EngineHealth(
                online: (obj?["ok"] as? Bool) ?? false,
                model: (obj?["model"] as? String) ?? "")
        } catch {
            return .offline
        }
    }

    /// Launch the engine if it isn't already up, waiting briefly for it to come
    /// online. Returns the resulting health. Safe to call repeatedly.
    @discardableResult
    func ensureRunning(timeoutTicks: Int = 15) async -> EngineHealth {
        var h = await health()
        if h.online { return h }
        guard process == nil,
            FileManager.default.fileExists(atPath: python.path),
            FileManager.default.fileExists(atPath: server.path)
        else { return h }
        let p = Process()
        p.executableURL = python
        p.arguments = [server.path, "--port", "\(port)"]
        p.currentDirectoryURL = appDir
        do { try p.run() } catch { return h }
        process = p
        for _ in 0..<timeoutTicks {
            try? await Task.sleep(nanoseconds: 900_000_000)
            h = await health()
            if h.online { break }
        }
        return h
    }
}
