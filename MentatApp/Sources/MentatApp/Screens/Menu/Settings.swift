import SwiftUI

// MARK: - Settings

struct SettingsMenu: View {
    var engine: Engine
    @Environment(\.palette) private var pal
    @Environment(DesignStore.self) private var designStore: DesignStore?
    @AppStorage("appearance") private var appearanceRaw = AppTheme.fallback.rawValue

    private func ins<T>(_ kp: WritableKeyPath<DesignTokens.Inspector, T>, _ fallback: T) -> Binding<
        T
    > {
        Binding(
            get: { designStore?.tokens.inspector[keyPath: kp] ?? fallback },
            set: { designStore?.tokens.inspector[keyPath: kp] = $0 })
    }

    private var sections: [(String, [SettingSpec])] {
        var order: [String] = []
        var map: [String: [SettingSpec]] = [:]
        for s in engine.settingsSpec {
            let sec = s.section ?? "Other"
            if map[sec] == nil {
                order.append(sec)
                map[sec] = []
            }
            map[sec]?.append(s)
        }
        return order.map { ($0, map[$0] ?? []) }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                VStack(alignment: .leading, spacing: 8) {
                    Text("APPEARANCE").font(.caption2).tracking(2).foregroundStyle(pal.terracotta)
                    Picker("", selection: $appearanceRaw) {
                        ForEach(AppTheme.allCases) { t in
                            Label(t.label, systemImage: t.symbol).tag(t.rawValue)
                        }
                    }
                    .pickerStyle(.segmented).labelsHidden()
                    Toggle("Layout grid", isOn: ins(\.showGrid, false))
                    Toggle("Grid numbers", isOn: ins(\.numbers, true))
                }
                ForEach(sections, id: \.0) { section, specs in
                    VStack(alignment: .leading, spacing: 8) {
                        Text(section.uppercased())
                            .font(.caption2).tracking(2).foregroundStyle(pal.terracotta)
                        ForEach(specs) { spec in
                            SettingRow(engine: engine, spec: spec)
                        }
                    }
                }
            }
            .padding(16)
        }
        .frame(width: 380, height: 520)
        .task { await engine.loadSettings() }
    }
}

struct SettingsSheet: View {
    var engine: Engine
    @Environment(\.dismiss) private var dismiss
    @Environment(\.palette) private var pal
    @AppStorage("appearance") private var appearanceRaw = AppTheme.fallback.rawValue
    @AppStorage("shuffleBackgrounds") private var shuffleOnLaunch = false

    private var theme: AppTheme { AppTheme(rawValue: appearanceRaw) ?? .fallback }

    private var sections: [(String, [SettingSpec])] {
        var order: [String] = []
        var map: [String: [SettingSpec]] = [:]
        for s in engine.settingsSpec {
            let sec = s.section ?? "Other"
            if map[sec] == nil {
                order.append(sec)
                map[sec] = []
            }
            map[sec]?.append(s)
        }
        return order.map { ($0, map[$0] ?? []) }
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text("Settings").font(.headline).foregroundStyle(engine.accentColor(.center))
                Spacer()
                Button("Done") { dismiss() }
            }
            .padding(.horizontal, 16).padding(.vertical, 10)
            .liquid(corner: 18)
            .padding(.horizontal, 12).padding(.top, 12).padding(.bottom, 4)
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    VStack(alignment: .leading, spacing: 10) {
                        Text("APPEARANCE")
                            .font(.caption2).tracking(2).foregroundStyle(pal.terracotta)
                        HStack(spacing: 10) {
                            Text("Theme").foregroundStyle(pal.text).frame(
                                width: 170, alignment: .leading)
                            Picker("", selection: $appearanceRaw) {
                                ForEach(AppTheme.allCases) { t in
                                    Label(t.label, systemImage: t.symbol).tag(t.rawValue)
                                }
                            }
                            .pickerStyle(.segmented)
                            .labelsHidden().frame(minWidth: 150, maxWidth: 200)
                            Spacer()
                        }
                        Text("Light — natural colour. Noir — contrasty black & white.")
                            .font(.caption2).foregroundStyle(pal.textDim).padding(.leading, 180)
                    }
                    VStack(alignment: .leading, spacing: 10) {
                        HStack {
                            Text("BACKGROUNDS")
                                .font(.caption2).tracking(2).foregroundStyle(pal.terracotta)
                            Spacer()
                            Button {
                                engine.shuffleBackground()
                            } label: {
                                Label("Shuffle", systemImage: "shuffle")
                            }
                            .buttonStyle(.plain).foregroundStyle(engine.accentColor(.center)).font(
                                .caption)
                        }
                        LazyVGrid(
                            columns: [GridItem(.adaptive(minimum: 108), spacing: 8)], spacing: 8
                        ) {
                            ForEach(engine.backgrounds, id: \.self) { name in
                                Button {
                                    engine.selectBackground(name)
                                } label: {
                                    AsyncThumbnail(name: name)
                                        .modifier(DesertGrade(theme: theme))
                                        .frame(height: 60).frame(maxWidth: .infinity).clipped()
                                        .clipShape(
                                            RoundedRectangle(cornerRadius: 10, style: .continuous)
                                        )
                                        .overlay(
                                            RoundedRectangle(cornerRadius: 10, style: .continuous)
                                                .strokeBorder(
                                                    engine.backgroundName == name
                                                        ? engine.accentColor(.center)
                                                        : pal.rim.opacity(0.12),
                                                    lineWidth: engine.backgroundName == name ? 2 : 1
                                                )
                                        )
                                }
                                .buttonStyle(.plain)
                            }
                        }
                        Toggle("Shuffle on launch", isOn: $shuffleOnLaunch)
                            .font(.caption).foregroundStyle(pal.text)
                    }
                    ForEach(sections, id: \.0) { section, specs in
                        VStack(alignment: .leading, spacing: 10) {
                            Text(section.uppercased())
                                .font(.caption2).tracking(2).foregroundStyle(pal.terracotta)
                            ForEach(specs) { spec in
                                SettingRow(engine: engine, spec: spec)
                            }
                        }
                    }
                }
                .padding(16)
            }
        }
        .frame(width: 560, height: 620)
        .background(.regularMaterial)
        .task { await engine.loadSettings() }
    }
}

struct SettingRow: View {
    var engine: Engine
    let spec: SettingSpec
    var chrome: ChromePalette? = nil
    @State private var text: String = ""
    @State private var lensSel = "- none -"
    @Environment(\.palette) private var pal

    private var value: Any? { engine.settingsValues[spec.key] }
    private var options: [String]? { engine.settingsOptions[spec.key] }
    // When a chrome palette is supplied the row borrows the artwork's ink;
    // otherwise it falls back to the fixed palette (other settings surfaces).
    private var isLight: Bool { chrome?.isLight ?? !pal.isDark }
    private var ink: Color { chrome?.ink ?? (pal.isDark ? .white : Color(white: 0.06)) }
    private var dim: Color { chrome?.dim ?? (pal.isDark ? Color(white: 0.72) : Color(white: 0.34)) }
    private var valueInk: Color { ink.opacity(0.92) }

    private var label: String { spec.key.replacingOccurrences(of: "_", with: " ").capitalized }
    private var selectedOption: String {
        if spec.key == "lens" { return lensSel.isEmpty ? "- none -" : lensSel }
        return stringValue(value)
    }
    /// Short, snappy option names become tappable pills; longer lists (model,
    /// voice) use a menu so they can't overflow the panel.
    private var pillOptions: [String]? {
        guard let o = options, o.count > 1, o.count <= 5,
            o.allSatisfy({ $0.count <= 8 })
        else { return nil }
        return o
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 14) {
                Text(label)
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(ink)
                    .lineLimit(1)
                    .fixedSize(horizontal: true, vertical: false)
                if spec.key == "thinking", let opts = options, opts.count > 1 {
                    Spacer(minLength: 10)
                    OptionSlider(
                        options: opts, selection: selectedOption,
                        tint: valueInk, onSelect: select)
                } else if let opts = pillOptions {
                    Spacer(minLength: 10)
                    OptionPills(
                        options: opts, selection: selectedOption,
                        ink: valueInk, dim: dim, isLight: isLight, onSelect: select)
                } else {
                    Spacer(minLength: 12)
                    control
                }
            }
            .padding(.horizontal, 18)
            .frame(minHeight: 46)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(SettingPill(isLight: isLight))
            if let help = spec.help {
                Text(help)
                    .font(.system(size: 10))
                    .foregroundStyle(dim)
                    .padding(.horizontal, 22)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .onAppear { syncFromValue() }
        // values arrive asynchronously (settings fetch); keep the field and the
        // lens picker in step with them once they land
        .onChange(of: stringValue(value)) { _, _ in syncFromValue() }
    }

    private func syncFromValue() {
        text = stringValue(value)
        if spec.key == "lens" {
            let v = stringValue(value)
            lensSel = v.isEmpty ? "- none -" : v
        }
    }

    private func select(_ v: String) {
        if spec.key == "lens" {
            lensSel = v
            Task { await engine.runCommand("lens", v == "- none -" ? "--clear" : v) }
        } else {
            Task { await engine.setSetting(spec.key, v) }
        }
    }

    @ViewBuilder private var control: some View {
        if let opts = options {
            Menu {
                ForEach(opts, id: \.self) { o in
                    Button(o) { select(o) }
                }
            } label: {
                HStack(spacing: 5) {
                    Text(selectedOption.isEmpty ? "—" : selectedOption)
                        .font(.system(size: 13, weight: .medium)).lineLimit(1)
                    Image(systemName: "chevron.up.chevron.down")
                        .font(.system(size: 8, weight: .bold)).opacity(0.55)
                }
                .foregroundStyle(valueInk)
            }
            .menuStyle(.borderlessButton)
            .menuIndicator(.hidden)
            .fixedSize()
        } else if let b = value as? Bool {
            PillToggle(isOn: b, ink: ink, dim: dim, isLight: isLight) { v in
                Task { await engine.setSetting(spec.key, v) }
            }
        } else {
            TextField("", text: $text)
                .textFieldStyle(.plain)
                .multilineTextAlignment(.trailing)
                .font(.system(size: 13, weight: .medium, design: .monospaced))
                .foregroundStyle(valueInk)
                .frame(minWidth: 90, maxWidth: 180, alignment: .trailing)
                .onSubmit { Task { await engine.setSetting(spec.key, text) } }
        }
    }

    private func stringValue(_ v: Any?) -> String {
        switch v {
        case let s as String: return s
        case let n as NSNumber:
            if CFGetTypeID(n) == CFBooleanGetTypeID() { return n.boolValue ? "on" : "off" }
            return n.stringValue
        case .none: return ""
        default: return "\(v!)"
        }
    }
}

/// The wide glass capsule a setting floats in: frosted, faintly tinted, with a
/// specular rim along the top edge and a soft ambient shadow — no hard border.
struct SettingPill: View {
    let isLight: Bool
    var body: some View {
        Capsule(style: .continuous)
            .fill(.ultraThinMaterial)
            .overlay(
                Capsule(style: .continuous)
                    .fill(isLight ? Color.white.opacity(0.22) : Color.black.opacity(0.30))
            )
            .overlay(
                Capsule(style: .continuous)
                    .stroke(
                        LinearGradient(
                            colors: [Color.white.opacity(isLight ? 0.55 : 0.18), .clear],
                            startPoint: .top, endPoint: .bottom), lineWidth: 1
                    )
                    .allowsHitTesting(false)
            )
            .shadow(color: .black.opacity(isLight ? 0.16 : 0.35), radius: 12, y: 6)
    }
}

/// A discrete slider over ordered options. Uses the native `Slider`, whose knob
/// becomes Liquid Glass while you drag it on macOS 26; the current value is
/// shown alongside.
struct OptionSlider: View {
    let options: [String]
    let selection: String
    let tint: Color
    let onSelect: (String) -> Void

    private var binding: Binding<Double> {
        Binding(
            get: { Double(options.firstIndex(of: selection) ?? 0) },
            set: { v in
                let i = min(options.count - 1, max(0, Int(v.rounded())))
                if options.indices.contains(i), options[i] != selection { onSelect(options[i]) }
            }
        )
    }

    var body: some View {
        HStack(spacing: 10) {
            Slider(value: binding, in: 0...Double(max(1, options.count - 1)), step: 1)
                .tint(tint)
                .frame(width: 148)
                .accessibilityLabel("Value")
            Text(selection.isEmpty ? "—" : selection)
                .font(.system(size: TypeScale.body, weight: .medium))
                .foregroundStyle(tint)
                .lineLimit(1)
                .fixedSize()
                .frame(minWidth: 54, alignment: .trailing)
        }
    }
}

struct OptionPills: View {
    let options: [String]
    let selection: String
    let ink: Color
    let dim: Color
    let isLight: Bool
    let onSelect: (String) -> Void

    var body: some View {
        // Flow (wrap) instead of a compressing HStack, and never truncate the
        // option label — long lists wrap to a second line rather than clip.
        FlowRow(spacing: 4) {
            ForEach(options, id: \.self) { o in
                let active = o == selection
                Button {
                    onSelect(o)
                } label: {
                    Text(o)
                        .font(.system(size: TypeScale.label, weight: .medium))
                        .lineLimit(1)
                        .fixedSize()
                        .padding(.horizontal, 9).padding(.vertical, 6)
                        .background(Capsule(style: .continuous).fill(active ? ink : Color.clear))
                        .overlay(
                            Capsule(style: .continuous)
                                .stroke(active ? Color.clear : dim.opacity(0.35), lineWidth: 1)
                        )
                        .foregroundStyle(active ? (isLight ? Color.white : Color.black) : ink)
                        .contentShape(Capsule())
                }
                .buttonStyle(.pressable)
                .help(o)
            }
        }
        .animation(Anim.snappy, value: selection)
    }
}

/// A minimal capsule switch that inverts like the reference's play button:
/// on it fills with ink and shows a cut-out knob, off it recedes into glass.
struct PillToggle: View {
    let isOn: Bool
    let ink: Color
    let dim: Color
    let isLight: Bool
    let onChange: (Bool) -> Void

    var body: some View {
        Button {
            onChange(!isOn)
        } label: {
            ZStack(alignment: isOn ? .trailing : .leading) {
                Capsule(style: .continuous)
                    .fill(isOn ? ink : dim.opacity(0.28))
                    .frame(width: 44, height: 24)
                Circle()
                    .fill(isOn ? (isLight ? Color.white : Color(white: 0.08)) : ink.opacity(0.9))
                    .frame(width: 18, height: 18)
                    .padding(3)
            }
            .contentShape(Capsule())
        }
        .buttonStyle(.plain)
        .animation(Anim.snappy, value: isOn)
        .help(isOn ? "On" : "Off")
    }
}
