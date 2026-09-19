import SwiftUI

/// Dev-only performance readout for `/debug`: render counters and operation
/// timings. A `TimelineView` tick refreshes it without observing anything, so it
/// can't perturb what it measures.
struct PerfHUD: View {
    @State private var snap: (counts: [String: Int], timings: [String: Double]) = ([:], [:])

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text("PERF").font(.system(size: 9, weight: .semibold)).foregroundStyle(.secondary)
                Spacer()
                Button("Reset") { Perf.reset() }
                    .controlSize(.mini)
            }
            TimelineView(.periodic(from: .now, by: 1)) { _ in
                let counts = Perf.snapshot().counts
                let timings = Perf.snapshot().timings
                VStack(alignment: .leading, spacing: 2) {
                    row("chat.body", "\(counts["chat.body"] ?? 0)")
                    row("row.assistant", "\(counts["row.assistant"] ?? 0)")
                    row("stream.flush", "\(counts["stream.flush"] ?? 0)")
                    row("analyze ms", ms(timings["analyze"]))
                    row("layout ms", ms(timings["layout"]))
                }
            }
        }
        .font(.system(size: 9.5, design: .monospaced))
    }

    private func ms(_ v: Double?) -> String {
        guard let v else { return "—" }
        return String(format: "%.1f", v)
    }

    private func row(_ label: String, _ value: String) -> some View {
        HStack {
            Text(label).foregroundStyle(.secondary)
            Spacer()
            Text(value)
        }
    }
}
