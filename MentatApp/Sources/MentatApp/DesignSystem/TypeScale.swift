import CoreGraphics

/// Semantic type scale, read live from `DesignTokens.typography`, so font sizes
/// are data (editable via the Design panel) instead of scattered literals.
enum TypeScale {
    static var micro: CGFloat { CGFloat(DesignTokens.current.typography.micro) }
    static var meta: CGFloat { CGFloat(DesignTokens.current.typography.meta) }
    static var caption: CGFloat { CGFloat(DesignTokens.current.typography.caption) }
    static var label: CGFloat { CGFloat(DesignTokens.current.typography.label) }
    static var body: CGFloat { CGFloat(DesignTokens.current.typography.body) }
    static var bodyMono: CGFloat { CGFloat(DesignTokens.current.typography.bodyMono) }
    static var emphasis: CGFloat { CGFloat(DesignTokens.current.typography.emphasis) }
}
