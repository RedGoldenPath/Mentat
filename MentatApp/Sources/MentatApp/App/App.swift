import SwiftUI
import AppKit
import CoreText

// MARK: - App

struct PaletteHost<Content: View>: View {
    @AppStorage("appearance") private var appearanceRaw = AppTheme.fallback.rawValue
    private let engine = Engine.shared
    let content: Content
    init(@ViewBuilder content: () -> Content) { self.content = content() }
    private var theme: AppTheme { AppTheme(rawValue: appearanceRaw) ?? .fallback }
    var body: some View {
        content
            .environment(\.palette,
                         Palette.forTheme(theme, colorTheme: engine.colorTheme,
                                          active: engine.useOKLCHTheme))
            .environment(\.appTheme, theme)
            // the global artwork palette — the authority for UI + text colour
            .environment(\.bgPalette, engine.bgPalette)
            // the OKLCH color system — the contrast-enforced authority
            .environment(\.colorTheme, engine.colorTheme)
            .environment(\.glassStyle, engine.glassStyle)
            // the single global ink, resampled whenever the artwork/geometry changes
            .environment(\.ink, AppInk(left: engine.adaptiveInk(.left),
                                       center: engine.adaptiveInk(.center),
                                       right: engine.adaptiveInk(.right),
                                       top: engine.titleInk()))
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        if let url = Bundle.main.url(forResource: "Quicksand", withExtension: "ttf") {
            CTFontManagerRegisterFontsForURL(url as CFURL, .process, nil)
        }
        Task { @MainActor in
            await Engine.shared.ensureEngine()
            await Engine.shared.loadConversations()
            Engine.shared.loadBackgrounds()
        }
    }
}

@main
struct MentatApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    private let engine = Engine.shared
    @AppStorage("appearance") private var appearanceRaw = AppTheme.fallback.rawValue
    @Environment(\.openWindow) private var openWindow

    init() {
        // register before any view resolves the custom font, so `.custom`
        // never falls back to a system face on first render
        if let url = Bundle.main.url(forResource: "Quicksand", withExtension: "ttf") {
            CTFontManagerRegisterFontsForURL(url as CFURL, .process, nil)
        }
    }

    private var appearance: AppTheme { AppTheme(rawValue: appearanceRaw) ?? .fallback }

    var body: some Scene {
        Window("Mentat", id: "main") {
            PaletteHost { RootView(engine: engine) }
                .applyAppearance()
                .background(WindowAppearance(theme: appearance))
                .modifier(AppearIn())
        }
        .windowStyle(.hiddenTitleBar)
        .defaultSize(width: 1040, height: 740)
        .commands {
            CommandGroup(replacing: .newItem) {
                Button("New Conversation") { Task { await engine.newConversation() } }
                    .keyboardShortcut("n", modifiers: .command)
            }
            CommandMenu("View") {
                Picker("Appearance", selection: $appearanceRaw) {
                    ForEach(AppTheme.allCases) { t in
                        Label(t.label, systemImage: t.symbol).tag(t.rawValue)
                    }
                }
                .pickerStyle(.inline)
            }
            CommandMenu("Mentat") {
                Button("Help") { Task { await engine.runCommand("help", "") } }
                Button("Status") { Task { await engine.runCommand("status", "") } }
                Divider()
                Button("Debug Panel") { engine.debugMode.toggle() }
                    .keyboardShortcut("d", modifiers: [.command, .option])
                Divider()
                Button("Shuffle Background") { engine.shuffleBackground() }
                Button("New Conversation") { Task { await engine.newConversation() } }
                    .keyboardShortcut("n", modifiers: [.command, .shift])
                Divider()
            }
        }

        // Menu-bar icon just opens the app (no popover UI).
        MenuBarExtra("Mentat", systemImage: "eye") {
            Button("Open Mentat") {
                openWindow(id: "main")
                NSApp.activate(ignoringOtherApps: true)
            }
            Divider()
            Button("Quit Mentat") { NSApp.terminate(nil) }
        }
        .menuBarExtraStyle(.menu)
    }
}
