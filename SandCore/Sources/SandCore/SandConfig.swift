import simd

/// The resolved parameters of the dust system — shared between the app's
/// token-resolved style and the lab's sliders. See `TRUTH.md`.
///
/// One simple model: **Langevin dust** drifting in an endless void, lit by
/// **soft light beams**, colliding with moving solids (pointer + UI). The beams
/// are the light source for the dust (single-scatter / Tyndall), so a beam that
/// flickers brighter lights the spice it touches in sync (see `TRUTH.md` §1/§11).
public struct SandConfig: Equatable, Sendable, Codable {
    // palette
    public var shaftColor: SIMD3<Float>       // beam colour (golden, lower)
    public var shaftColorNear: SIMD3<Float>   // soft warm at the source
    public var sparkleColor: SIMD3<Float>     // spice-orange glint (own colour, not the UI accent)

    // MOTION — Langevin particles
    public var swirl: Double              // weak swirl force
    public var swirlScale: Double         // swirl noise frequency
    public var drift: Double              // constant lateral air current
    public var drag: Double               // velocity damping (higher = stiller)
    public var brownian: Double           // random shimmer
    public var parallaxDepth: Double      // how strongly closeness scales motion (0 = none, 1 = strong)

    // OBSTACLES — moving solids the dust flows around
    public var obstacleRadius: Double     // pointer disk radius
    public var obstaclePad: Double        // rect padding

    // DUST
    public var dustCount: Double
    public var dustSize: Double
    public var dustFog: Double            // depth fade
    public var dustBase: Double           // visibility outside the beams
    public var dustBrightness: Double

    // LIGHT — a cone of light from a point above the top edge (god-ray)
    public var shaftX: Double             // source x (uv)
    public var shaftY: Double             // source y (uv; negative = above the top)
    public var shaftSpread: Double        // cone half-angle (degrees)
    public var shaftRays: Double          // big-shaft striations
    public var shaftFalloff: Double       // Beer–Lambert extinction σ (higher = fades faster)
    public var shaftSourceGlow: Double    // hotspot strength at the source
    public var shaftStrength: Double
    public var shaftDrift: Double         // slow beam drift
    public var shaftBg: Double            // faint cone wash in the air
    public var shaftVary: Double          // per-ray density variance (aperture)
    public var shaftSpeed: Double         // beam breathing rate
    public var shaftWarp: Double          // irregular ray spacing (now time-varying)
    public var shaftPenumbra: Double      // edge softness growth with distance
    public var shaftPhaseG: Double        // HG anisotropy g (forward scattering)
    public var shaftThinRays: Double      // thin-filament frequency
    public var shaftThinStrength: Double  // thin-filament strength
    public var shaftThinSharp: Double     // thin-filament sharpness
    public var shaftThinVary: Double      // how much filaments vary along the beam
    public var shaftColorFalloff: Double  // how fast near→far colour shifts
    public var beamFlutter: Double         // per-ray independent brighten/dim (0 = none)
    public var beamFlutterSpeed: Double    // flutter rate
    public var goboStrength: Double        // how much leaves/window shadow the light
    public var goboScale: Double           // gobo spatial frequency
    public var goboDrift: Double           // gobo drift/wander speed
    public var gustAmount: Double          // autonomous calm↔flutter envelope depth (0 = steady)
    public var gustRate: Double            // gust envelope rate (low = long calm stretches)
    public var lightSway: Double           // how much the light source itself sways/wanders
    public var lightLean: Double           // how much the light leans toward the pointer
    // WIND — ONE shared air field that drives BOTH the dust and the light's
    // occluder (the "vorticle" idea from Ghost of Tsushima's wind): a few slow
    // vortices + a gentle dominant direction, so the whole scene is one place.
    public var windDir: Double             // dominant direction (degrees; 0 = +x)
    public var windStrength: Double        // base wind speed
    public var windWander: Double          // vortex/swirl amount
    // WINDOW LIGHT — a directional (near-parallel) god-ray: a lit band across the
    // frame with a few soft shafts, angled like sun through a window.
    public var lightAngle: Double          // beam direction in degrees (0 = straight down; negative = down-left)
    public var windowWidth: Double         // half-width of the lit window band (uv)
    public var poolStrength: Double        // brightness of the pool where the beams land

    // VOLUMETRIC LIGHT — a screen-space ray-march through the medium (a real
    // integral, so shafts are soft/volumetric, not a painted shape), with
    // temporal antialiasing of the light (jitter + history blend).
    public var volSteps: Double            // march steps (more = smoother/cleaner)
    public var volDensity: Double          // scattering σs (how much the air scatters)
    public var volExtinction: Double       // absorption σt (Beer–Lambert through the medium)
    public var volScale: Double            // medium noise scale
    public var volDrift: Double            // medium drift speed
    public var volJitter: Double           // per-frame march jitter amount (0..1)
    public var taaAlpha: Double            // temporal blend: 1 = no history, low = smoother

    // HAZE — a soft band near the bottom that drifts/rolls and catches the light
    public var hazeStrength: Double
    public var hazeY: Double
    public var hazeThickness: Double
    public var hazeScale: Double
    public var hazeDrift: Double
    public var hazePulse: Double

    // DUST depth — 4 parallax layers (far · mid · near · hero foreground)
    public var dustLayers: Double         // number of depth layers (bands)
    public var dustNearScale: Double      // near-mote size multiplier
    public var dustNearBrightness: Double // near-mote brightness multiplier
    public var dustNearBlur: Double       // near-mote bokeh amount
    public var sparkle: Double            // glint strength as motes cross the light
    public var sparkleSpeed: Double       // glint rate
    // FIVE depth layers, nearest → farthest. The nearest is the "close-up"
    // (bigger/blurrier/faster via the near scaling); no special hero layer.
    public var layerClose: Bool
    public var layerNear: Bool
    public var layerMid: Bool
    public var layerFar: Bool
    public var layerHaze: Bool

    // RENDER
    public var bloomIntensity: Double
    public var bloomThreshold: Double
    public var bloomIterations: Double
    public var dither: Double             // subtle texture (hides banding; not film grain)
    public var exposure: Double           // pre-tonemap gain
    public var tonemap: Double            // 1 = ACES filmic, 0 = clamp

    public init(
        shaftColor: SIMD3<Float> = SIMD3(1, 0.6, 0.28),
        shaftColorNear: SIMD3<Float> = SIMD3(1, 0.82, 0.62),
        sparkleColor: SIMD3<Float> = SIMD3(1, 0.55, 0.22),
        swirl: Double = 0.2844362745098039,
        swirlScale: Double = 1.2040543300653592,
        drift: Double = 0.0,
        drag: Double = 9.498008578431373,
        brownian: Double = 0.008,
        parallaxDepth: Double = 0.6,
        obstacleRadius: Double = 0.008,
        obstaclePad: Double = 0.015,
        dustCount: Double = 12000.0,
        dustSize: Double = 2.2,
        dustFog: Double = 1.6,
        dustBase: Double = 0.08,
        dustBrightness: Double = 1.0,
        shaftStrength: Double = 1.0865093954248366,
        shaftX: Double = 0.5,
        shaftY: Double = -0.07350847630718949,
        shaftSpread: Double = 90.0,
        shaftRays: Double = 7.0,
        shaftFalloff: Double = 2.6743872549019607,
        shaftSourceGlow: Double = 0.9056883169934641,
        shaftDrift: Double = 0.03,
        shaftBg: Double = 0.2,
        shaftVary: Double = 0.5622702205882353,
        shaftSpeed: Double = 0.35,
        shaftWarp: Double = 0.6,
        shaftPenumbra: Double = 0.4,
        shaftPhaseG: Double = 0.2,
        shaftThinRays: Double = 27.0,
        shaftThinStrength: Double = 0.6,
        shaftThinSharp: Double = 8.0,
        shaftThinVary: Double = 0.7,
        shaftColorFalloff: Double = 1.5,
        beamFlutter: Double = 0.6,
        beamFlutterSpeed: Double = 1.2,
        goboStrength: Double = 0.0,
        goboScale: Double = 3.0,
        goboDrift: Double = 0.06,
        gustAmount: Double = 0.5,
        gustRate: Double = 0.07,
        lightSway: Double = 0.4,
        lightLean: Double = 0.0,
        windDir: Double = 135.0,
        windStrength: Double = 0.12,
        windWander: Double = 1.0,
        lightAngle: Double = -52.0,
        windowWidth: Double = 0.85,
        poolStrength: Double = 0.8,
        volSteps: Double = 24.0,
        volDensity: Double = 1.4,
        volExtinction: Double = 0.5,
        volScale: Double = 2.2,
        volDrift: Double = 0.05,
        volJitter: Double = 1.0,
        taaAlpha: Double = 0.18,
        hazeStrength: Double = 0.9,
        hazeY: Double = 0.92,
        hazeThickness: Double = 0.14,
        hazeScale: Double = 2.5,
        hazeDrift: Double = 0.03,
        hazePulse: Double = 0.25,
        dustLayers: Double = 5.0,
        dustNearScale: Double = 1.228515625,
        dustNearBrightness: Double = 2.344055095996732,
        dustNearBlur: Double = 0.45,
        sparkle: Double = 5.0,
        sparkleSpeed: Double = 3.0,
        layerClose: Bool = true,
        layerNear: Bool = true,
        layerMid: Bool = true,
        layerFar: Bool = true,
        layerHaze: Bool = true,
        bloomIntensity: Double = 0.4209354575163399,
        bloomThreshold: Double = 0.6,
        bloomIterations: Double = 4.0,
        dither: Double = 0.012,
        exposure: Double = 0.17888327205882354,
        tonemap: Double = 1.0
    ) {
        self.shaftColor = shaftColor
        self.shaftColorNear = shaftColorNear
        self.sparkleColor = sparkleColor
        self.swirl = swirl; self.swirlScale = swirlScale
        self.drift = drift; self.drag = drag; self.brownian = brownian
        self.parallaxDepth = parallaxDepth
        self.obstacleRadius = obstacleRadius; self.obstaclePad = obstaclePad
        self.dustCount = dustCount; self.dustSize = dustSize
        self.dustFog = dustFog; self.dustBase = dustBase; self.dustBrightness = dustBrightness
        self.shaftStrength = shaftStrength
        self.shaftX = shaftX; self.shaftY = shaftY; self.shaftSpread = shaftSpread
        self.shaftRays = shaftRays; self.shaftFalloff = shaftFalloff
        self.shaftSourceGlow = shaftSourceGlow
        self.shaftDrift = shaftDrift; self.shaftBg = shaftBg
        self.shaftVary = shaftVary; self.shaftSpeed = shaftSpeed; self.shaftWarp = shaftWarp
        self.shaftPenumbra = shaftPenumbra; self.shaftPhaseG = shaftPhaseG
        self.shaftThinRays = shaftThinRays; self.shaftThinStrength = shaftThinStrength
        self.shaftThinSharp = shaftThinSharp; self.shaftThinVary = shaftThinVary
        self.shaftColorFalloff = shaftColorFalloff
        self.beamFlutter = beamFlutter; self.beamFlutterSpeed = beamFlutterSpeed
        self.goboStrength = goboStrength; self.goboScale = goboScale; self.goboDrift = goboDrift
        self.gustAmount = gustAmount; self.gustRate = gustRate
        self.lightSway = lightSway; self.lightLean = lightLean
        self.windDir = windDir; self.windStrength = windStrength; self.windWander = windWander
        self.lightAngle = lightAngle; self.windowWidth = windowWidth
        self.poolStrength = poolStrength
        self.volSteps = volSteps; self.volDensity = volDensity
        self.volExtinction = volExtinction; self.volScale = volScale
        self.volDrift = volDrift; self.volJitter = volJitter; self.taaAlpha = taaAlpha
        self.hazeStrength = hazeStrength; self.hazeY = hazeY; self.hazeThickness = hazeThickness
        self.hazeScale = hazeScale; self.hazeDrift = hazeDrift; self.hazePulse = hazePulse
        self.dustLayers = dustLayers
        self.dustNearScale = dustNearScale; self.dustNearBrightness = dustNearBrightness
        self.dustNearBlur = dustNearBlur
        self.sparkle = sparkle; self.sparkleSpeed = sparkleSpeed
        self.layerClose = layerClose; self.layerNear = layerNear; self.layerMid = layerMid
        self.layerFar = layerFar; self.layerHaze = layerHaze
        self.bloomIntensity = bloomIntensity; self.bloomThreshold = bloomThreshold
        self.bloomIterations = bloomIterations; self.dither = dither
        self.exposure = exposure; self.tonemap = tonemap
    }

    /// The house surface: dust floating in a dark room, lit by soft beams.
    public static let sand = SandConfig()
}

/// Live, per-frame inputs (cursor + obstacle rects + the couplings from UI
/// events). These used to live in `SandMotion` app-side but were never sent to
/// the GPU — now they are the renderer's per-frame input.
public struct SandInputs {
    public var pointer: SIMD2<Float>          // cursor uv (y down)
    public var hasPointer: Bool
    public var renderScale: Float
    public var obstacleRects: [SIMD4<Float>]  // (x, y, w, h) in uv
    /// Pointer offset from centre (small, uv) — drives the parallax split.
    public var parallax: SIMD2<Float>
    /// Pointer velocity (uv/s) — a real splat, not just a static poke.
    public var pointerVelocity: SIMD2<Float>
    /// Global push from UI events (uv/s) — the "force, not wall" motion.
    public var force: SIMD2<Float>
    public var shear: Float
    public var gust: Float
    public var breath: Float
    public var pulse: Float
    /// Per-frame sub-pixel/march jitter for the volumetric light + TAA.
    public var jitter: SIMD2<Float>

    public init(
        pointer: SIMD2<Float> = .zero,
        hasPointer: Bool = false,
        renderScale: Float = 1.0,
        obstacleRects: [SIMD4<Float>] = [],
        parallax: SIMD2<Float> = .zero,
        pointerVelocity: SIMD2<Float> = .zero,
        force: SIMD2<Float> = .zero,
        shear: Float = 0,
        gust: Float = 0,
        breath: Float = 0,
        pulse: Float = 0,
        jitter: SIMD2<Float> = .zero
    ) {
        self.pointer = pointer; self.hasPointer = hasPointer
        self.renderScale = renderScale; self.obstacleRects = obstacleRects
        self.parallax = parallax; self.pointerVelocity = pointerVelocity
        self.force = force; self.shear = shear
        self.gust = gust; self.breath = breath; self.pulse = pulse
        self.jitter = jitter
    }
}
