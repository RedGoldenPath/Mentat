import SwiftUI
import WebKit

/// A sandboxed HTML app rendered from a model-authored ` ```html ` block (the
/// MCP-Apps / OpenAI Apps SDK pattern). Locked down: an ephemeral data store, no
/// network (all http/https subresources blocked + top-level navigation cancelled),
/// and a single typed message channel — the widget can only act through the host.
struct HTMLWidgetView: View {
    var html: String
    var onMessage: ((String) -> Void)? = nil
    @Environment(\.palette) private var pal

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Image(systemName: "lock.shield")
                Text("sandboxed widget")
                Spacer()
            }
            .font(.system(size: TypeScale.micro, weight: .semibold))
            .foregroundStyle(pal.textDim)

            HTMLWebView(html: html, onMessage: onMessage)
                .frame(height: 280)
                .clipShape(RoundedRectangle(cornerRadius: ChromeShape.radiusS, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: ChromeShape.radiusS, style: .continuous)
                        .stroke(pal.border.opacity(0.4), lineWidth: 1))
        }
    }
}

struct HTMLWebView: NSViewRepresentable {
    var html: String
    var onMessage: ((String) -> Void)?

    func makeCoordinator() -> Coordinator { Coordinator(onMessage: onMessage) }

    func makeNSView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()          // ephemeral, no cookies
        config.defaultWebpagePreferences.allowsContentJavaScript = true
        config.userContentController.add(context.coordinator, name: "mentat")
        installNetworkBlock(on: config)

        let web = WKWebView(frame: .zero, configuration: config)
        web.navigationDelegate = context.coordinator
        context.coordinator.lastHTML = html
        web.loadHTMLString(Self.wrap(html), baseURL: nil)
        return web
    }

    func updateNSView(_ web: WKWebView, context: Context) {
        guard context.coordinator.lastHTML != html else { return }
        context.coordinator.lastHTML = html
        web.loadHTMLString(Self.wrap(html), baseURL: nil)
    }

    /// Best-effort block on every network subresource type; inline content and
    /// in-memory scripts still run.
    private func installNetworkBlock(on config: WKWebViewConfiguration) {
        let json = """
        [{"trigger":{"url-filter":".*","resource-type":
          ["image","style-sheet","script","font","media","fetch","websocket","raw","ping"]},
          "action":{"type":"block"}}]
        """
        WKContentRuleListStore.default()?.compileContentRuleList(
            forIdentifier: "mentat-widget-block", encodedContentRuleList: json
        ) { list, _ in
            if let list { config.userContentController.add(list) }
        }
    }

    private static func wrap(_ body: String) -> String {
        """
        <!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">
        <style>
          :root { color-scheme: light dark; }
          body { margin:0; padding:10px; font:13px -apple-system,system-ui,sans-serif;
                 background:transparent; color:inherit; }
        </style>
        \(body)
        """
    }

    final class Coordinator: NSObject, WKNavigationDelegate, WKScriptMessageHandler {
        var lastHTML = ""
        let onMessage: ((String) -> Void)?
        init(onMessage: ((String) -> Void)?) { self.onMessage = onMessage }

        func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            let scheme = navigationAction.request.url?.scheme
            // Only the in-memory document may load; every network navigation is refused.
            decisionHandler(scheme == nil || scheme == "about" ? .allow : .cancel)
        }

        func userContentController(_ controller: WKUserContentController,
                                   didReceive message: WKScriptMessage) {
            onMessage?(String(describing: message.body))
        }
    }
}
