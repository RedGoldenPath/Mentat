import AppKit
import SwiftUI

/// Hides the native window traffic lights (close / minimize / zoom) so the
/// custom header stands alone. Re-asserted because macOS can reset window button
/// state; the overlay never intercepts clicks.
struct HideTrafficLights: NSViewRepresentable {
    func makeNSView(context: Context) -> NSView { ConfiguredView() }
    func updateNSView(_ nsView: NSView, context: Context) {
        (nsView as? ConfiguredView)?.apply()
    }

    final class ConfiguredView: NSView {
        override func hitTest(_ point: NSPoint) -> NSView? { nil }

        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            apply()
        }

        func apply() {
            guard let window else { return }
            for type in [NSWindow.ButtonType.closeButton, .miniaturizeButton, .zoomButton] {
                window.standardWindowButton(type)?.isHidden = true
            }
        }
    }
}
