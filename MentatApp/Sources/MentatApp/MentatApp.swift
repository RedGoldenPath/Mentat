import SwiftUI
import AppKit

// MARK: - Engine client (talks to the local Mentat engine at 127.0.0.1:8765)

struct Citation: Decodable, Hashable {
    let book: String
    let loc: String
}

struct AskResponse: Decodable {
    let status: String?
    let answer: String?
    let error: String?
    let citations: [Citation]?
    let ungrounded: Int?
    let model: String?
}

@MainActor
final class Engine: ObservableObject {
    @Published var answer: String = ""
    @Published var citations: [Citation] = []
    @Published var ungrounded: Int = 0
    @Published var model: String = ""
    @Published var busy: Bool = false
    @Published var online: Bool = false
    @Published var status: String = "starting…"

    private let base = URL(string: "http://127.0.0.1:8765")!

    func checkHealth() async {
        do {
            let (data, _) = try await URLSession.shared.data(from: base.appendingPathComponent("status"))
            let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any]
            online = (obj?["ok"] as? Bool) ?? false
            model = (obj?["model"] as? String) ?? ""
            status = online ? "engine ready" : "engine down"
        } catch {
            online = false
            status = "engine offline — run MentatApp/run.sh"
        }
    }

    func ask(_ question: String) async {
        let q = question.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !q.isEmpty, !busy else { return }
        busy = true
        status = "thinking…"
        citations = []
        ungrounded = 0
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
            citations = res.citations ?? []
            ungrounded = res.ungrounded ?? 0
            if let m = res.model, !m.isEmpty { model = m }
            status = res.status ?? "done"
        } catch {
            answer = "Error: \(error.localizedDescription)"
            status = "error"
        }
    }
}

// MARK: - UI

struct CitationChip: View {
    let citation: Citation
    var body: some View {
        HStack(spacing: 4) {
            Image(systemName: "text.quote").font(.caption2)
            Text("\(citation.book) · \(citation.loc)")
                .font(.caption2)
                .lineLimit(1)
        }
        .padding(.horizontal, 8).padding(.vertical, 3)
        .background(Color.secondary.opacity(0.12), in: Capsule())
    }
}

struct AskView: View {
    @ObservedObject var engine: Engine
    @State private var question: String = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Image(systemName: "eye")
                Text("Mentat").font(.headline)
                Spacer()
                if !engine.model.isEmpty {
                    Text(engine.model).font(.caption2).foregroundStyle(.tertiary)
                }
                Circle().fill(engine.online ? Color.green : Color.orange)
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
                VStack(alignment: .leading, spacing: 8) {
                    Text(engine.answer.isEmpty
                         ? "Ask a question grounded in your books. Answers cite their sources."
                         : engine.answer)
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .foregroundStyle(engine.answer.isEmpty ? AnyShapeStyle(.secondary) : AnyShapeStyle(.primary))

                    if !engine.citations.isEmpty || engine.ungrounded > 0 {
                        HStack(spacing: 6) {
                            if engine.ungrounded > 0 {
                                Label("\(engine.ungrounded) unverified", systemImage: "exclamationmark.triangle")
                                    .font(.caption2).foregroundStyle(.orange)
                                    .padding(.horizontal, 8).padding(.vertical, 3)
                                    .background(Color.orange.opacity(0.15), in: Capsule())
                            }
                            ForEach(engine.citations.prefix(8), id: \.self) { c in
                                CitationChip(citation: c)
                            }
                        }
                        .padding(.top, 4)
                    }
                }
            }
            .frame(minHeight: 200)
        }
        .padding(14)
        .frame(width: 480, height: 420)
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
