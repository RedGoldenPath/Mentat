import SwiftUI
import AppKit
import UniformTypeIdentifiers

/// A native macOS composer input (NSTextView): grows from one line up to `maxHeight`
/// then **scrolls internally** (so long messages are reachable), Enter sends,
/// Shift+Enter inserts a newline, and large pastes / file drops are intercepted —
/// the behaviour Qwen/DeepSeek/Kimi/ChatGPT use.
struct ComposerTextView: NSViewRepresentable {
    @Binding var text: String
    @Binding var height: CGFloat
    var maxHeight: CGFloat = 200
    var onSend: () -> Void
    var onFiles: ([URL]) -> Void
    var onPaste: (String) -> Bool

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeNSView(context: Context) -> NSScrollView {
        let tv = ComposerNSTextView()
        tv.delegate = context.coordinator
        tv.isRichText = false
        tv.isEditable = true
        tv.isSelectable = true
        tv.allowsUndo = true
        tv.drawsBackground = false
        tv.backgroundColor = .clear
        tv.textColor = .labelColor
        tv.insertionPointColor = .labelColor
        tv.font = .systemFont(ofSize: 14)
        tv.textContainerInset = NSSize(width: 4, height: 8)
        tv.isVerticallyResizable = true
        tv.isHorizontallyResizable = false
        tv.autoresizingMask = [.width]
        tv.minSize = NSSize(width: 0, height: 0)
        tv.maxSize = NSSize(width: 0, height: CGFloat.greatestFiniteMagnitude)
        tv.textContainer?.widthTracksTextView = true
        tv.textContainer?.containerSize = NSSize(width: 0, height: CGFloat.greatestFiniteMagnitude)
        tv.onSend = onSend
        tv.onFiles = onFiles
        tv.onPaste = onPaste
        tv.string = text
        tv.registerForDraggedTypes([.fileURL])

        let scroll = NSScrollView()
        scroll.documentView = tv
        scroll.hasVerticalScroller = true
        scroll.autohidesScrollers = true
        scroll.drawsBackground = false
        scroll.borderType = .noBorder
        scroll.verticalScrollElasticity = .allowed
        return scroll
    }

    func updateNSView(_ scroll: NSScrollView, context: Context) {
        guard let tv = scroll.documentView as? ComposerNSTextView else { return }
        if tv.string != text { tv.string = text }
        tv.onSend = onSend
        tv.onFiles = onFiles
        tv.onPaste = onPaste
        if !context.coordinator.didFocus {
            context.coordinator.didFocus = true
            tv.window?.makeFirstResponder(tv)
        }
    }

    final class Coordinator: NSObject, NSTextViewDelegate {
        var parent: ComposerTextView
        var didFocus = false
        init(_ p: ComposerTextView) { parent = p }

        func textDidChange(_ notification: Notification) {
            guard let tv = notification.object as? NSTextView else { return }
            parent.text = tv.string
            recomputeHeight(tv)
        }

        func recomputeHeight(_ tv: NSTextView) {
            guard let lm = tv.layoutManager, let tc = tv.textContainer else { return }
            lm.ensureLayout(for: tc)
            let used = lm.usedRect(for: tc).height + tv.textContainerInset.height * 2
            let oneLine = (tv.font?.ascender ?? 14) - (tv.font?.descender ?? 0) + 6
            let h = min(parent.maxHeight, max(oneLine, used))
            if abs(parent.height - h) > 0.5 { parent.height = h }
        }
    }
}

/// NSTextView that supports: Enter=send / Shift+Enter=newline, paste interception,
/// and file-URL drag & drop.
final class ComposerNSTextView: NSTextView {
    var onSend: (() -> Void)?
    var onFiles: (([URL]) -> Void)?
    var onPaste: ((String) -> Bool)?

    override func insertNewline(_ sender: Any?) {
        let shift = NSApp.currentEvent?.modifierFlags.contains(.shift) ?? false
        if shift { super.insertNewline(sender) } else { onSend?() }
    }

    override func paste(_ sender: Any?) {
        let s = NSPasteboard.general.string(forType: .string) ?? ""
        if !s.isEmpty, onPaste?(s) == true { return }   // handled (converted to a file)
        super.paste(sender)
    }

    override func draggingEntered(_ sender: NSDraggingInfo) -> NSDragOperation {
        sender.draggingPasteboard.canReadObject(forClasses: [NSURL.self],
                                                options: [.urlReadingFileURLsOnly: true]) ? .copy : []
    }

    override func performDragOperation(_ sender: NSDraggingInfo) -> Bool {
        let urls = sender.draggingPasteboard.readObjects(
            forClasses: [NSURL.self], options: [.urlReadingFileURLsOnly: true]) as? [URL] ?? []
        if urls.isEmpty { return false }
        onFiles?(urls)
        return true
    }
}
