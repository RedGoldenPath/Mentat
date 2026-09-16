import SwiftUI
import AppKit

// MARK: - Engine client (talks to the local Mentat engine at 127.0.0.1:8765)

struct AskResponse: Decodable {
    let status: String?
    let answer: String?
    let error: String?
}

@MainActor
final class Engine: ObservableObject {
    @Published var answer: String = ""
    @Published var busy: Bool = false
    @Published var online: Bool = false
    @Published var status: String = "starting…"

    private let base = URL(string: "http://127.0.0.1:8765")!

    func checkHealth() async {
        do {
            let (data, _) = try await URLSession.shared.data(from: base.appendingPathComponent("status"))
            let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any]
            online = (obj?["ok"] as? Bool) ?? false
            status = online ? "engine ready" : "engine down"
        } catch {
            online = false
            status = "engine offline — run: python server.py"
        }
    }

    func ask(_ question: String) async {
        let q = question.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !q.isEmpty, !busy else { return }
        busy = true
        status = "thinking…"
        defer { busy = false }
        var req = URLRequest(url: base.appendingPathComponent("ask"))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(withJSONObject: ["question": q])
        req.timeoutInterval = 600
        do {
            let (data, _) = try await URLSession.shared.data(for: req)
            let res = try JSONDecoder().decode(AskResponse.self, from: data)
            answer = res.answer ?? res.error ?? "(no answer)"
            status = res.status ?? "done"
        } catch {
            answer = "Error: \(error.localizedDescription)"
            status = "error"
        }
    }
}

// MARK: - UI

struct AskView: View {
    @ObservedObject var engine: Engine
    @State private var question: String = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Image(systemName: "eye")
                Text("Mentat").font(.headline)
                Spacer()
                Circle()
                    .fill(engine.online ? Color.green : Color.orange)
                    .frame(width: 8, height: 8)
                Text(engine.status).font(.caption).foregroundStyle(.secondary)
            }

            HStack(spacing: 8) {
                TextField("Ask your library…", text: $question)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit { Task { await engine.ask(question) } }
                Button {
                    Task { await engine.ask(question) }
                } label: {
                    Image(systemName: "arrow.up.circle.fill").font(.title2)
                }
                .buttonStyle(.plain)
                .disabled(engine.busy || question.trimmingCharacters(in: .whitespaces).isEmpty)
            }

            Divider()

            ScrollView {
                Text(engine.answer.isEmpty ? "Ask a question grounded in your books. Answers cite their sources." : engine.answer)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .foregroundStyle(engine.answer.isEmpty ? AnyShapeStyle(.secondary) : AnyShapeStyle(.primary))
            }
            .frame(minHeight: 200)
        }
        .padding(14)
        .frame(width: 460, height: 400)
        .task { await engine.checkHealth() }
    }
}

@main
struct MentatApp: App {
    @StateObject private var engine = Engine()

    var body: some Scene {
        MenuBarExtra("Mentat", systemImage: "eye") {
            AskView(engine: engine)
        }
        .menuBarExtraStyle(.window)

        Window("Mentat", id: "main") {
            AskView(engine: engine)
        }
    }
}
