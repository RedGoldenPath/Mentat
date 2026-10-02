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
            // Defer to the next runloop and only mutate when it actually changes:
            // toggling a window button *during* a layout pass (viewDidMoveToWindow
            // / updateNSView) made AppKit throw from `_NSViewUpdateConstraints`,
            // which surfaces as an EXC_BREAKPOINT crash (`_crashOnException`).
            DispatchQueue.main.async { [weak self] in
                guard let self, let window = self.window else { return }
                for type in [NSWindow.ButtonType.closeButton, .miniaturizeButton, .zoomButton] {
                    if let button = window.standardWindowButton(type), !button.isHidden {
                        button.isHidden = true
                    }
                }
            }
        }
    }
}
