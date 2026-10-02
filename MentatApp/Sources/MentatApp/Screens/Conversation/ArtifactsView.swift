import SwiftUI

/// A fenced code block lifted out of an answer — the app's "artifact".
struct Artifact: Identifiable, Hashable {
    let id = UUID()
    let language: String
    let code: String
}

/// Pulls fenced code blocks (```lang … ```) out of an answer. Pure, so it can be
/// tested without a view.
enum ArtifactParser {
    static func parse(_ text: String) -> [Artifact] {
        var out: [Artifact] = []
        var language = ""
        var buffer: [String] = []
        var inBlock = false
        for raw in text.split(separator: "\n", omittingEmptySubsequences: false) {
            let line = String(raw)
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            if trimmed.hasPrefix("```") {
                if inBlock {
                    out.append(Artifact(language: language, code: buffer.joined(separator: "\n")))
                    buffer = []; language = ""; inBlock = false
                } else {
                    inBlock = true
                    language = String(trimmed.dropFirst(3)).trimmingCharacters(in: .whitespaces)
                }
                continue
            }
            if inBlock { buffer.append(line) }
        }
        if inBlock, !buffer.isEmpty {
            out.append(Artifact(language: language, code: buffer.joined(separator: "\n")))
        }
        return out
    }
}

/// The Inspector's Artifacts tab: every fenced block in the current answer, with
/// a copy button. When the app grows real generated files this is where they land.
struct ArtifactsView: View {
    let text: String
    @Environment(\.palette) private var pal

    private var artifacts: [Artifact] { ArtifactParser.parse(text) }

    var body: some View {
        if artifacts.isEmpty {
            MentatEmptyState(
                system: "curlybraces", title: "No artifacts",
                message: "Code blocks in the current answer become copyable artifacts here.")
        } else {
            VStack(alignment: .leading, spacing: Spacing.s) {
                ForEach(artifacts) { a in
                    artifactView(a)
                }
            }
        }
    }

    /// A fenced block becomes generated UI when its language is a scene language
    /// (`scene`/`genui`/`ui`/`mentat`), a sandboxed HTML widget for `html`, and a
    /// copyable code card otherwise.
    @ViewBuilder private func artifactView(_ a: Artifact) -> some View {
        let lang = a.language.lowercased()
        if SceneParser.languages.contains(lang), let spec = SceneParser.parse(a.code) {
            SceneRenderer(spec: spec)
        } else if lang == "html" {
            HTMLWidgetView(html: a.code)
        } else {
            codeCard(a)
        }
    }

    private func codeCard(_ a: Artifact) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: Spacing.xs) {
                Text(a.language.isEmpty ? "code" : a.language)
                    .font(.system(size: TypeScale.micro, weight: .semibold, design: .monospaced))
                    .foregroundStyle(pal.textDim)
                Spacer(minLength: Spacing.xs)
                Button { copyToPasteboard(a.code) } label: {
                    Image(systemName: "doc.on.doc")
                        .font(.system(size: TypeScale.caption, weight: .semibold))
                        .foregroundStyle(pal.textDim)
                        .frame(width: 22, height: 22)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .help("Copy")
            }
            ScrollView(.horizontal, showsIndicators: false) {
                Text(a.code)
                    .font(.system(size: TypeScale.caption, design: .monospaced))
                    .foregroundStyle(pal.text)
                    .textSelection(.enabled)
            }
        }
        .padding(Spacing.s)
        .frame(maxWidth: .infinity, alignment: .leading)
        .surface(.tonal, corner: ChromeShape.radiusS)
    }
}
