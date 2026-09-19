import SwiftUI

/// A background thumbnail that decodes off the main thread and fades in. The
/// gallery grid must never decode an image on the render thread — a grid of
/// tiles doing that was why later tiles failed to appear while scrolling.
struct AsyncThumbnail: View {
    let name: String
    var max: CGFloat = 240
    @State private var image: NSImage?

    var body: some View {
        ZStack {
            if let image {
                Image(nsImage: image).resizable().scaledToFill()
                    .transition(.opacity)
            } else {
                Rectangle().fill(.quaternary)
            }
        }
        .task(id: name) {
            if image != nil { return }
            let name = name
            let max = max
            let img = await Task.detached(priority: .userInitiated) {
                BackgroundAnalysis.fastThumb(name, max: max)
            }.value
            guard !Task.isCancelled else { return }
            withAnimation(.easeOut(duration: 0.18)) { image = img }
        }
    }
}
