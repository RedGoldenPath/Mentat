import SwiftUI

// MARK: - Glass style

/// Whether the Liquid Glass carries the theme's stained-glass tint (colour-
/// forward) or stays clearer so more of the artwork shows through.
enum GlassStyle: String, Codable, Sendable {
    case tinted, clear
}

private struct GlassStyleKey: EnvironmentKey {
    static let defaultValue = GlassStyle.tinted
}

extension EnvironmentValues {
    var glassStyle: GlassStyle {
        get { self[GlassStyleKey.self] }
        set { self[GlassStyleKey.self] = newValue }
    }
}

// MARK: - Glass surfaces

/// Floating glass panel built from a material, an optional tint, a specular top
/// sheen and a rim stroke. Honors Reduce Transparency with a solid fill.
// Hand-rolled glass removed — everything standardizes on system `glassEffect`.

/// Liquid Glass surface. Per the HIG, `regular` carries text (blurs/luminosity-
/// adjusts for legibility); `clear` is only for icon-only controls over media.
struct LiquidSurface: ViewModifier {
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.palette) private var pal
    @Environment(\.glassStyle) private var glassStyle
    @Environment(\.colorTheme) private var colorTheme
    var corner: CGFloat
    var tint: Color?
    var interactive: Bool
    /// Use the highly-translucent `clear` variant (icon controls over media).
    var clear: Bool = false

    private var glassValue: Glass {
        var g = clear ? Glass.clear : Glass.regular
        if let tint {
            g = g.tint(tint)
        } else if colorTheme != .placeholder {
            // Both glass styles carry the image hue; Clear simply carries less.
            g = g.tint((clear || glassStyle == .clear) ? colorTheme.clearTint : colorTheme.accentTint)
        }
        if interactive { g = g.interactive() }
        return g
    }

    func body(content: Content) -> some View {
        let shape = RoundedRectangle(cornerRadius: corner, style: .continuous)
        if reduceTransparency {
            return AnyView(
                content.background(
                    (tint ?? pal.bg2).opacity(pal.isDark ? 0.92 : 0.94),
                    in: shape))
        }
        return AnyView(content.glassEffect(glassValue, in: shape))
    }
}

/// The history rail's backdrop: real system Liquid Glass, tinted with the theme
/// surface so the rail takes the image hue while the artwork still reads faintly
/// through it. `SidebarArtwork` sits behind it.
struct SidebarGlass: ViewModifier {
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.glassStyle) private var glassStyle
    var solid: Color
    var tint: Color?

    func body(content: Content) -> some View {
        if reduceTransparency {
            return AnyView(content.background(solid.ignoresSafeArea()))
        }
        var glass = Glass.regular
        if let tint { glass = glass.tint(glassStyle == .clear ? tint.opacity(0.6) : tint) }
        return AnyView(
            content.background(
                Rectangle().fill(.clear)
                    .glassEffect(glass, in: Rectangle())
                    .ignoresSafeArea()
            ))
    }
}

extension View {
    func sidebarGlass(solid: Color, tint: Color? = nil) -> some View {
        modifier(SidebarGlass(solid: solid, tint: tint))
    }
}

/// Message bubbles: the *clear* Liquid Glass variant (thin, no dark rim).
struct BubbleSurface: ViewModifier {
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.glassStyle) private var glassStyle
    @Environment(\.colorTheme) private var colorTheme
    var corner: CGFloat
    var tint: Color?

    private var glassValue: Glass {
        if let tint { return Glass.clear.tint(tint) }
        if colorTheme != .placeholder {
            return glassStyle == .clear
                ? Glass.clear.tint(colorTheme.clearTint)
                : Glass.regular.tint(colorTheme.accentTint)
        }
        return Glass.clear
    }

    func body(content: Content) -> some View {
        let shape = RoundedRectangle(cornerRadius: corner, style: .continuous)
        if reduceTransparency {
            return AnyView(content.background((tint ?? Color.black.opacity(0.55)), in: shape))
        }
        return AnyView(content.glassEffect(glassValue, in: shape))
    }
}

/// Combines sibling Liquid Glass effects in one container — the Apple-recommended
/// way to render multiple custom glass elements (better performance, shapes can
/// merge/morph).
struct GlassContainer: ViewModifier {
    var spacing: CGFloat
    func body(content: Content) -> some View {
        GlassEffectContainer(spacing: spacing) { content }
    }
}

extension View {
    /// Standard Liquid Glass button style (Apple's recommended control treatment).
    func glassButton() -> some View {
        buttonStyle(.glass)
    }
    /// Group sibling glass controls so they render in one Liquid Glass container.
    func glassContainer(spacing: CGFloat = 14) -> some View {
        modifier(GlassContainer(spacing: spacing))
    }
    func liquid(corner: CGFloat = 16, tint: Color? = nil, interactive: Bool = false) -> some View {
        modifier(LiquidSurface(corner: corner, tint: tint, interactive: interactive))
    }
    func bubble(corner: CGFloat = 20, tint: Color? = nil) -> some View {
        modifier(BubbleSurface(corner: corner, tint: tint))
    }
    /// Apple's scroll edge effect: keeps floating controls legible over content.
    func softScrollEdges() -> some View { modifier(ScrollEdgeEffect()) }
    func hideWindowToolbar() -> some View { modifier(HideWindowToolbar()) }
    /// Liquid Glass appears/disappears with the system's materialize transition.
    func glassMaterialize() -> some View { modifier(GlassMaterialize()) }
}

struct GlassMaterialize: ViewModifier {
    func body(content: Content) -> some View {
        content.glassEffectTransition(.materialize)
    }
}
