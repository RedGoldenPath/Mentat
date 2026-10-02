import SwiftUI
import AppKit
import CoreText

// MARK: - App

struct PaletteHost<Content: View>: View {
    private let engine = Engine.shared
    let content: Content
    init(@ViewBuilder content: () -> Content) { self.content = content() }
    var body: some View {
        content
            .environment(\.palette, Palette.from(engine.colorTheme))
            // the single colour authority — the contrast-enforced look theme
            .environment(\.colorTheme, engine.colorTheme)
            .environment(\.glassStyle, engine.glassStyle)
            // the one global ink, resolved from the look (never a photo)
            .environment(\.ink, AppInk(left: engine.colorTheme.ink,
                                       center: engine.colorTheme.ink,
                                       right: engine.colorTheme.ink,
                                       top: engine.colorTheme.ink))
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        if let url = Bundle.main.url(forResource: "Quicksand", withExtension: "ttf") {
            CTFontManagerRegisterFontsForURL(url as CFURL, .process, nil)
        }
        Task { @MainActor in
            await Engine.shared.ensureEngine()
            // restore the thread the user was last in, so continuity survives a relaunch
            if !Engine.shared.currentConv.isEmpty {
                await Engine.shared.openConversation(Engine.shared.currentConv)
            }
            await Engine.shared.loadConversations()
            if UserDefaults.standard.bool(forKey: "mentatDemoScene") {
                Engine.shared.appendDemoScene()
            }
            if UserDefaults.standard.bool(forKey: "mentatDemoMarkdown") {
                Engine.shared.appendDemoMarkdown()
            }
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        // stop the engine this app started, so quitting the app frees the port + RAM
        // (the engine also reaps any predecessor on the next launch via the same pidfile)
        let pidfile = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Everything/mentat/app/mentat2_data/engine.pid")
        if let s = try? String(contentsOf: pidfile, encoding: .utf8),
           let pid = Int32(s.trimmingCharacters(in: .whitespacesAndNewlines)) {
            kill(pid, SIGTERM)
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
                .applyAppearance(isDark: !engine.colorTheme.isLight)
                .background(WindowAppearance(isDark: !engine.colorTheme.isLight))
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
                Button("New Conversation") { Task { await engine.newConversation() } }
                    .keyboardShortcut("n", modifiers: [.command, .shift])
                Divider()
                // Generated from the one command registry, so the menu bar can
                // never drift from the ⌘K palette or the `/` menu.
                ForEach(CommandRegistry.all(debug: false).filter { $0.isSlash }) { c in
                    Button(c.title) { Task { await engine.runCommand(c.slash ?? "", "") } }
                }
                Divider()
                Button("Debug Panel") { engine.debugMode.toggle() }
                    .keyboardShortcut("d", modifiers: [.command, .shift])
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
