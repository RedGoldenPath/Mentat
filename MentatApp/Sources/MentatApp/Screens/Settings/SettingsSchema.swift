import Foundation

/// The one place setting specs are grouped into ordered sections — used by both
/// the everyday Settings panel and the Developer panel, so the grouping rule is
/// defined once instead of copied per surface.
enum SettingSection {
    static func group(
        _ specs: [SettingSpec],
        where predicate: (SettingSpec) -> Bool = { _ in true }
    ) -> [(String, [SettingSpec])] {
        var order: [String] = []
        var map: [String: [SettingSpec]] = [:]
        for s in specs where predicate(s) {
            let sec = s.section ?? "Other"
            if map[sec] == nil {
                order.append(sec)
                map[sec] = []
            }
            map[sec, default: []].append(s)
        }
        return order.map { ($0, map[$0] ?? []) }
    }
}
