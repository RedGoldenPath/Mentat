import SwiftUI

// =============================================================================
// MARK: - Material role (glass is ONE option, not the rule)
// =============================================================================

/// How a surface is painted. `material` = system blur, `tonal` = themed fill,
/// `outline` = stroke only, `solid` = opaque fill, `glass` = Liquid Glass.
enum MaterialRole: String, Codable, CaseIterable, Sendable {
    case material, tonal, outline, solid, glass

    var label: String {
        switch self {
        case .material: return "Material"
        case .tonal: return "Tonal"
        case .outline: return "Outline"
        case .solid: return "Solid"
        case .glass: return "Glass"
        }
    }
}

// =============================================================================
// MARK: - Token accessors (read live, so Design edits apply immediately)
// =============================================================================

/// The 8-pt spatial rhythm, read from `DesignTokens.space`.
enum Spacing {
    static var xxs: CGFloat { CGFloat(DesignTokens.current.space.xxs) }
    static var xs: CGFloat { CGFloat(DesignTokens.current.space.xs) }
    static var s: CGFloat { CGFloat(DesignTokens.current.space.s) }
    static var m: CGFloat { CGFloat(DesignTokens.current.space.m) }
    static var l: CGFloat { CGFloat(DesignTokens.current.space.l) }
    static var xl: CGFloat { CGFloat(DesignTokens.current.space.xl) }
    static var xxl: CGFloat { CGFloat(DesignTokens.current.space.xxl) }
    static var xxxl: CGFloat { CGFloat(DesignTokens.current.space.xxxl) }
}

/// The elevation ramp, read from `DesignTokens.elevation`.
enum Elev {
    static var flat: DesignTokens.Elevation.Shadow { DesignTokens.current.elevation.flat }
    static var low: DesignTokens.Elevation.Shadow { DesignTokens.current.elevation.low }
    static var mid: DesignTokens.Elevation.Shadow { DesignTokens.current.elevation.mid }
    static var high: DesignTokens.Elevation.Shadow { DesignTokens.current.elevation.high }
}

// =============================================================================
// MARK: - Surface primitive
// =============================================================================

/// One surface treatment for the whole app. Change `MaterialRole` and the surface
/// changes; no view hand-rolls its own blur/fill/stroke/shadow again.
/// The one place a `MaterialRole` is turned into paint. Shape-agnostic, so any
/// surface — rounded card, capsule chip, pill — resolves identically.
struct ShapeSurface<S: InsettableShape>: ViewModifier {
    var role: MaterialRole? = nil
    var shape: S
    var tint: Color? = nil
    var elevation: DesignTokens.Elevation.Shadow? = nil
    var interactive: Bool = false

    @Environment(\.palette) private var pal
    @Environment(\.design) private var design
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency

    func body(content: Content) -> some View {
        // Read the live tokens from the environment so a material change re-skins
        // the surface immediately (the static mirror is not observable).
        let role = role ?? design.material.role
        let shadow = elevation ?? Elev.flat
        Group {
            switch role {
            case .glass where !reduceTransparency:
                content.glassEffect(glassValue, in: shape)
            case .glass, .material:
                content.background(.regularMaterial, in: shape)
            case .tonal:
                content.background(fill, in: shape)
            case .solid:
                content.background(pal.bg2, in: shape)
            case .outline:
                content.background(Color.clear, in: shape)
            }
        }
        .overlay {
            if role == .outline || role == .tonal {
                shape.strokeBorder(
                    pal.isDark ? Color.white.opacity(0.14) : Color.black.opacity(0.10),
                    lineWidth: 1)
                    .allowsHitTesting(false)
            }
        }
        .shadow(color: .black.opacity(shadow.opacity), radius: shadow.radius, y: shadow.y)
    }

    private var fill: Color {
        if let tint { return tint.opacity(pal.isDark ? 0.20 : 0.24) }
        return pal.bg2.opacity(pal.isDark ? 0.55 : 0.72)
    }
    private var glassValue: Glass {
        var g: Glass = tint.map { Glass.regular.tint($0.opacity(0.5)) } ?? Glass.regular
        if interactive { g = g.interactive() }
        return g
    }
}

/// Rounded-rectangle convenience over `ShapeSurface`.
struct SurfaceStyle: ViewModifier {
    var role: MaterialRole? = nil
    var corner: CGFloat
    var tint: Color? = nil
    var elevation: DesignTokens.Elevation.Shadow? = nil
    var interactive: Bool = false

    func body(content: Content) -> some View {
        content.modifier(
            ShapeSurface(
                role: role,
                shape: RoundedRectangle(cornerRadius: corner, style: .continuous),
                tint: tint, elevation: elevation, interactive: interactive))
    }
}

extension View {
    /// Apply the app's surface treatment to a rounded rectangle. Defaults to the
    /// token material role.
    func surface(
        _ role: MaterialRole? = nil,
        corner: CGFloat,
        tint: Color? = nil,
        elevation: DesignTokens.Elevation.Shadow? = nil,
        interactive: Bool = false
    ) -> some View {
        modifier(
            SurfaceStyle(
                role: role, corner: corner, tint: tint, elevation: elevation,
                interactive: interactive))
    }

    /// Apply the app's surface treatment to any shape (capsule, circle, …).
    func surface<S: InsettableShape>(
        _ role: MaterialRole? = nil,
        shape: S,
        tint: Color? = nil,
        elevation: DesignTokens.Elevation.Shadow? = nil,
        interactive: Bool = false
    ) -> some View {
        modifier(
            ShapeSurface(
                role: role, shape: shape, tint: tint, elevation: elevation,
                interactive: interactive))
    }
}

// =============================================================================
// MARK: - Primitives
// =============================================================================

/// A compact capsule label — icon and/or text. Replaces the three near-identical
/// chip recipes that were hand-rolled across the app.
struct MentatChip: View {
    var text: String? = nil
    var system: String? = nil
    var tint: Color? = nil
    var role: MaterialRole = .tonal
    var help: String? = nil
    @Environment(\.palette) private var pal

    var body: some View {
        HStack(spacing: Spacing.xxs + 2) {
            if let system {
                Image(systemName: system).font(.system(size: TypeScale.caption, weight: .semibold))
            }
            if let text {
                Text(text).font(.system(size: TypeScale.caption, weight: .medium)).lineLimit(1)
            }
        }
        .foregroundStyle(tint ?? pal.text)
        .padding(.horizontal, Spacing.s - 1).padding(.vertical, Spacing.xxs + 1)
        .surface(role, corner: 999, tint: tint)
        .help(help ?? text ?? "")
    }
}

/// A floating container. The single panel treatment (menu panels, popovers,
/// command palette, debug cards) all route through here.
struct MentatPanel<Content: View>: View {
    var role: MaterialRole? = nil
    var corner: CGFloat = ChromeShape.radiusL
    var elevation: DesignTokens.Elevation.Shadow? = Elev.mid
    var padding: CGFloat = Spacing.m
    @ViewBuilder var content: () -> Content

    var body: some View {
        content()
            .padding(padding)
            .surface(role, corner: corner, elevation: elevation)
    }
}

/// A a row in a list/menu: leading icon, title, optional trailing accessory,
/// with a hover highlight. One implementation for history rows, command rows,
/// setting rows, and menu rows.
struct MentatListRow<Trailing: View>: View {
    var system: String? = nil
    var title: String
    var subtitle: String? = nil
    var tint: Color? = nil
    var selected: Bool = false
    @ViewBuilder var trailing: () -> Trailing
    @Environment(\.palette) private var pal
    @State private var hover = false

    var body: some View {
        HStack(spacing: Spacing.xs) {
            if let system {
                Image(systemName: system)
                    .font(.system(size: TypeScale.label, weight: .semibold))
                    .foregroundStyle(tint ?? pal.textDim)
                    .frame(width: 20)
            }
            VStack(alignment: .leading, spacing: 1) {
                Text(title)
                    .font(.system(size: TypeScale.body, weight: selected ? .semibold : .medium))
                    .foregroundStyle(tint ?? pal.text)
                    .lineLimit(1)
                if let subtitle {
                    Text(subtitle)
                        .font(.system(size: TypeScale.caption))
                        .foregroundStyle(pal.textDim).lineLimit(1)
                }
            }
            Spacer(minLength: Spacing.xs)
            trailing()
        }
        .padding(.horizontal, Spacing.s).padding(.vertical, Spacing.xs - 1)
        .background(
            RoundedRectangle(cornerRadius: ChromeShape.radiusS, style: .continuous)
                .fill(pal.text.opacity(selected ? 0.10 : (hover ? 0.06 : 0)))
        )
        .contentShape(Rectangle())
        .onHover { hover = $0 }
    }
}

extension MentatListRow where Trailing == EmptyView {
    init(system: String? = nil, title: String, subtitle: String? = nil, tint: Color? = nil, selected: Bool = false) {
        self.init(system: system, title: title, subtitle: subtitle, tint: tint, selected: selected) {
            EmptyView()
        }
    }
}

/// A tiny status pill (counts, states, movement).
struct MentatBadge: View {
    var text: String
    var color: Color
    var body: some View {
        Text(text)
            .font(.system(size: TypeScale.micro, weight: .bold))
            .foregroundStyle(color)
            .padding(.horizontal, Spacing.xs - 1).padding(.vertical, 2)
            .background(color.opacity(0.15), in: Capsule(style: .continuous))
    }
}

/// The empty state (no conversation, no results, engine offline).
struct MentatEmptyState<Action: View>: View {
    var system: String
    var title: String
    var message: String? = nil
    @ViewBuilder var action: () -> Action
    @Environment(\.palette) private var pal

    var body: some View {
        VStack(spacing: Spacing.s) {
            Image(systemName: system)
                .font(.system(size: 26, weight: .light))
                .foregroundStyle(pal.textDim)
            Text(title)
                .font(.system(size: TypeScale.title, weight: .semibold))
                .foregroundStyle(pal.text)
            if let message {
                Text(message)
                    .font(.system(size: TypeScale.body))
                    .foregroundStyle(pal.textDim)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: 320)
            }
            action()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(Spacing.xl)
    }
}

extension MentatEmptyState where Action == EmptyView {
    init(system: String, title: String, message: String? = nil) {
        self.init(system: system, title: title, message: message) { EmptyView() }
    }
}
