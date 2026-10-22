#include <metal_stdlib>
using namespace metal;

// =============================================================================
// SandCore — "dust floating in a dark room, lit by soft beams".
//
// One simple model, three parts:
//
//   MOTION   Langevin force particles (Brownian):
//              v += (swirl(uv,t) + drift)·dt ; v *= exp(-drag·dt)
//              v += gaussian·brownian·√dt ; pos = fract(pos + v·dt)
//            mostly stationary, a little swirl, endless void.
//            Collides with moving solids (pointer disk + UI rects): project
//            out, cancel the inward velocity → dust parts around them.
//
//   LIGHT    one cone of light from a point above the top edge, with big shafts
//            and thin, varying filaments, tinted soft-warm at the source and
//            golden further down; a slowly drifting/rolling haze at the bottom
//            catches it. A mote is lit only inside the light → the Tyndall look.
//
//   RENDER   faint cone + haze in the air, additive layered motes (near grains
//            are bokeh), bloom, then film grain.
//
// See TRUTH.md.
// =============================================================================

constexpr sampler wrapS(coord::normalized, address::repeat, filter::linear);
constexpr sampler clampS(coord::normalized, address::clamp_to_edge, filter::linear);

static float2 uvOf(uint2 gid, uint w, uint h) {
    return (float2(gid) + 0.5) / float2(w, h);
}

static float hash21(float2 p) {
    float3 p3 = fract(float3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}

static float vnoise(float2 p) {
    float2 i = floor(p), f = fract(p);
    float2 u = f * f * (3.0 - 2.0 * f);
    float a = hash21(i);
    float b = hash21(i + float2(1.0, 0.0));
    float c = hash21(i + float2(0.0, 1.0));
    float d = hash21(i + float2(1.0, 1.0));
    return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}

static float fbm2(float2 p) {
    float s = 0.0, a = 0.5;
    for (int i = 0; i < 3; ++i) { s += a * vnoise(p); p *= 2.0; a *= 0.5; }
    return s;
}

static float2 gauss2(float2 seed) {
    float u1 = max(1e-5, hash21(seed));
    float u2 = hash21(seed + 17.0);
    float r = sqrt(-2.0 * log(u1));
    return float2(r * cos(6.2831853 * u2), r * sin(6.2831853 * u2));
}

/// Henyey–Greenstein phase function (Henyey & Greenstein 1941; as used by
/// Blender's Volume Scatter / PBRT §11 / Ocean Optics Web Book). g = mean
/// cosine of the scattering angle: 0 = isotropic, →1 = forward-peaked.
/// Normalised so g = 0 returns exactly 1.
static float hgPhase(float cosT, float g) {
    float g2 = g * g;
    float d = max(1.0 + g2 - 2.0 * g * cosT, 1e-3);
    return (1.0 - g2) / pow(d, 1.5);
}

/// The beam's colour: soft warm at the source, golden as it travels down.
static float3 beamColor(float2 uv, float sx, float sy, float3 near, float3 far, float expo) {
    float dist = length(uv - float2(sx, sy));
    return mix(near, far, clamp(dist * max(expo, 0.01), 0.0, 1.0));
}

/// A soft haze band near the bottom that slowly drifts and rolls, so it catches
/// the light intermittently. Returns density ~[0, 1].
static float hazeAt(float2 uv, float y, float thick, float scale, float drift,
                    float pulse, float time) {
    float q = (uv.y - y) / max(thick, 1e-3);
    float band = exp(-q * q);
    float n = fbm2(float2(uv.x * scale + drift * 6.0, uv.y * scale * 0.6 + time * pulse));
    return band * smoothstep(0.30, 0.85, n);
}

/// A compact warm hotspot at the source — the blown-out core in the reference.
static float sourceGlowAt(float2 uv, float sx, float sy) {
    float2 d = uv - float2(sx, sy);
    return exp(-dot(d, d) * 7.0);
}

// =============================================================================
// DUST — Langevin particles colliding with moving solids
// =============================================================================

struct DustParticle {
    float2 pos;   // domain uv
    float2 vel;   // uv / s
    float z;      // pseudo-depth 0 (near) … 1 (far)
    float age;
    float life;
    float seed;
};

struct DustUpdateUniforms {
    float dt;
    float time;
    float swirl;
    float swirlScale;
    float drift;
    float drag;
    float brownian;
    float pointerX;
    float pointerY;
    float pointerActive;
    float obstacleRadius;
    float obstaclePad;
    float obstacleCount;
    // couplings
    float parallaxDepth;
    float forceX;
    float forceY;
    float shear;
    float gust;
    float breath;
    float pointerVelX;
    float pointerVelY;
    float windDir;
    float windStrength;
    float windWander;
    float gustAmount;
    float gustRate;
};

static void resolveDisk(thread float2& pos, thread float2& vel, float2 c, float r) {
    float2 d = pos - c;
    float dist = length(d);
    if (dist < r && dist > 1e-6) {
        float2 n = d / dist;
        pos = c + n * r;
        float vn = dot(vel, n);
        if (vn < 0.0) vel -= n * vn;
    }
}

static void resolveRect(thread float2& pos, thread float2& vel, float4 rc, float pad) {
    float2 lo = rc.xy - pad;
    float2 hi = rc.xy + rc.zw + pad;
    if (pos.x > lo.x && pos.x < hi.x && pos.y > lo.y && pos.y < hi.y) {
        float dl = pos.x - lo.x, dr = hi.x - pos.x;
        float db = pos.y - lo.y, dtp = hi.y - pos.y;
        float m = min(min(dl, dr), min(db, dtp));
        if (m == dl) { pos.x = lo.x; vel.x = min(vel.x, 0.0); }
        else if (m == dr) { pos.x = hi.x; vel.x = max(vel.x, 0.0); }
        else if (m == db) { pos.y = lo.y; vel.y = min(vel.y, 0.0); }
        else { pos.y = hi.y; vel.y = max(vel.y, 0.0); }
    }
}

kernel void dust_update(device DustParticle* parts [[buffer(0)]],
                        constant DustUpdateUniforms& u [[buffer(1)]],
                        constant float4* obstacles [[buffer(2)]],
                        uint id [[thread_position_in_grid]]) {
    DustParticle d = parts[id];

    // depth speed: the closer a mote (z→0), the faster it travels across the
    // screen — the multiplane parallax cue. `parallaxDepth` blends it in.
    float ps = clamp(u.parallaxDepth, 0.0, 1.0);
    float near = 1.0 - clamp(d.z, 0.0, 1.0);
    float speedScale = (1.0 - ps) + ps * mix(0.35, 2.4, near);   // close-up (near) travels fastest

    // weak, slow swirl force (a force, never a field to be advected along) +
    // the global push from UI events (shift/shear/gust) — forces, not walls.
    float ang = fbm2(d.pos * max(u.swirlScale, 0.01) + float2(0.0, u.time * 0.05)) * 6.2831853;
    float2 F = float2(cos(ang), sin(ang)) * u.swirl * (1.0 + u.gust)
             + float2(u.drift, u.breath * 0.02)
             + float2(u.forceX, u.forceY);
    F.x += u.shear * (d.pos.y - 0.5);

    d.vel += F * speedScale * u.dt;

    d.vel *= exp(-max(u.drag, 0.0) * u.dt);
    d.vel += gauss2(float2(float(id) * 0.137 + 3.0, u.time)) * u.brownian * sqrt(max(u.dt, 1e-5));

    // pointer splat: the cursor pushes dust away, scaled by how fast it moves
    if (u.pointerActive > 0.5) {
        float2 toP = d.pos - float2(u.pointerX, u.pointerY);
        float dd = length(toP);
        float infl = exp(-dd * dd * 55.0) * speedScale;
        d.vel += (normalize(toP + 1e-5) * 0.02 + float2(u.pointerVelX, u.pointerVelY) * 2.5)
                 * infl * u.dt;
    }

    d.pos = fract(d.pos + d.vel * u.dt);

    // collide with real UI solids (panel slab, send block, cursor disk) — block,
    // keep tangential motion. Global transitions are forces now, never walls.
    int n = clamp(int(u.obstacleCount), 0, 16);
    for (int i = 0; i < n; ++i) resolveRect(d.pos, d.vel, obstacles[i], u.obstaclePad);
    if (u.pointerActive > 0.5) {
        resolveDisk(d.pos, d.vel, float2(u.pointerX, u.pointerY), u.obstacleRadius);
    }

    d.age += u.dt;
    if (d.age >= d.life) {
        d.pos = float2(hash21(float2(float(id) * 0.31, u.time + 1.0)),
                       hash21(float2(float(id) * 0.67, u.time + 2.0)));
        d.vel = float2(0.0);
        d.z = hash21(float2(float(id) * 0.91, u.time + 3.0));
        d.age = 0.0;
        d.life = 8.0 + 10.0 * hash21(float2(float(id) + 3.0, u.time + 1.0));
        d.seed = hash21(float2(float(id) + 5.0, u.time + 2.0));
    }
    parts[id] = d;
}

struct DustRenderUniforms {
    float time; float size; float fog; float base; float brightness;
    float shaftX; float shaftY; float shaftSpread; float shaftRays; float shaftFalloff;
    float shaftSourceGlow; float shaftStrength; float shaftDrift;
    float shaftVary; float shaftSpeed; float shaftWarp; float shaftPenumbra; float shaftPhaseG;
    float shaftThinRays; float shaftThinStrength; float shaftThinSharp; float shaftThinVary;
    float nearR; float nearG; float nearB; float farR; float farG; float farB; float colorExpo;
    float layers; float nearScale; float nearBrightness; float nearBlur;
    float sparkle; float sparkleSpeed;
    float domainPad;
    float sparkleR; float sparkleG; float sparkleB;
    float beamFlutter; float beamFlutterSpeed;
    float goboStrength; float goboScale; float goboDrift;
    float gustAmount; float gustRate;
    float parallaxX; float parallaxY; float parallaxDepth;
    float layerClose; float layerNear; float layerMid; float layerFar; float layerHaze;
};

struct DustVertexOut {
    float4 position [[position]];
    float size [[point_size]];
    float brightness;
    float3 color;
    float blur;
};

vertex DustVertexOut dust_vertex(uint vid [[vertex_id]],
                                 device const DustParticle* parts [[buffer(0)]],
                                 constant DustRenderUniforms& u [[buffer(1)]],
                                 texture2d<float, access::sample> lightTex [[texture(0)]]) {
    DustParticle d = parts[vid];
    DustVertexOut out;

    // depth layers: quantize z into `layers` bands
    float layers = max(u.layers, 1.0);
    float zl = layers > 1.0 ? floor(d.z * layers) / (layers - 1.0) : d.z;
    zl = clamp(zl, 0.0, 1.0);
    float near = 1.0 - zl;

    // FIVE depth layers: 0 = close-up (nearest), 1 = near, 2 = mid, 3 = far,
    // 4 = haze. Each is toggleable; the close-up is just the nearest band.
    int ln = clamp(int(u.layers), 1, 5);
    int b = clamp(int(d.z * float(ln)), 0, ln - 1);
    float enabled = b == 0 ? u.layerClose
                 : (b == 1 ? u.layerNear
                 : (b == 2 ? u.layerMid
                 : (b == 3 ? u.layerFar : u.layerHaze)));

    // parallax: closer motes slide further with the pointer (multiplane cue)
    float2 par = float2(u.parallaxX, u.parallaxY) * near * u.parallaxDepth;

    float2 vis = (d.pos - u.domainPad) / (1.0 - 2.0 * u.domainPad);
    float2 spp = vis + par;
    out.position = float4(float2(spp.x * 2.0 - 1.0, 1.0 - spp.y * 2.0), 0.0, 1.0);

    float lifeFrac = clamp(d.age / max(d.life, 0.001), 0.0, 1.0);
    float fade = sin(lifeFrac * 3.14159265) * enabled;

    // Lit by the SAME volumetric light the air uses — including the moving
    // leaves and the source sway — so the dust lights up and moves with the
    // light instead of glowing on its own (the Tyndall look, consistent).
    float3 lightRGB = lightTex.sample(clampS, vis).rgb;
    float beam = dot(lightRGB, float3(0.3333333)) * u.shaftStrength;
    float lit = u.base + beam;

    // specular glint: a mote flashes spice-orange as it crosses the light
    float glint = pow(clamp(0.5 + 0.5 * sin(u.time * u.sparkleSpeed + d.seed * 6.2831853), 0.0, 1.0), 12.0);
    float sparkle = 1.0 + u.sparkle * glint * clamp(beam, 0.0, 4.0);

    float flicker = 0.8 + 0.2 * sin(u.time * 1.5 + d.seed * 40.0);
    float fog = exp(-u.fog * d.z);

    out.brightness = fade * lit * fog * flicker * u.brightness * sparkle
                     * (1.0 + (u.nearBrightness - 1.0) * near);
    out.size = u.size * (0.6 + 0.9 * d.seed) * (1.3 - 0.6 * d.z)
               * (1.0 + (u.nearScale - 1.0) * near);
    float3 base = beamColor(vis, u.shaftX, u.shaftY,
                            float3(u.nearR, u.nearG, u.nearB),
                            float3(u.farR, u.farG, u.farB), u.colorExpo);
    float tint = clamp(u.sparkle * glint * clamp(beam, 0.0, 4.0) * 0.5, 0.0, 1.0);
    out.color = mix(base, float3(u.sparkleR, u.sparkleG, u.sparkleB), tint);
    out.blur = clamp(near * u.nearBlur, 0.0, 1.0);
    return out;
}

fragment half4 dust_fragment(DustVertexOut in [[stage_in]],
                             float2 pc [[point_coord]]) {
    float r = length(pc - 0.5) * 2.0;
    float soft = smoothstep(1.0, 0.0, r);
    soft *= soft;
    // bokeh for near motes: a rounded disc with a soft edge and a faint rim
    float disc = smoothstep(1.0, 0.62, r);
    float rim = smoothstep(0.72, 0.98, r) * 0.4 * smoothstep(1.0, 0.9, r);
    float bokeh = clamp(disc + rim, 0.0, 1.0);
    float a = mix(soft, bokeh, clamp(in.blur, 0.0, 1.0));
    float b = in.brightness * a;
    return half4(half3(in.color * b), half(a));
}

// =============================================================================
// BLOOM (multi-scale: prefilter → downsample chain → upsample add → final)
// =============================================================================

struct BloomUniforms { float2 texel; float threshold; float pad; };

kernel void bloom_prefilter(texture2d<float, access::sample> tex [[texture(0)]],
                            texture2d<float, access::write> dest [[texture(1)]],
                            constant BloomUniforms& u [[buffer(0)]],
                            uint2 gid [[thread_position_in_grid]]) {
    if (gid.x >= dest.get_width() || gid.y >= dest.get_height()) return;
    float2 uv = uvOf(gid, dest.get_width(), dest.get_height());
    float3 c = tex.sample(clampS, uv).rgb;
    float br = max(c.r, max(c.g, c.b));
    float knee = u.threshold * 0.7 + 0.0001;
    float rq = clamp(br - (u.threshold - knee), 0.0, knee * 2.0);
    rq = 0.25 / knee * rq * rq;
    c *= max(rq, br - u.threshold) / max(br, 0.0001);
    dest.write(float4(c, 1.0), gid);
}

kernel void bloom_down(texture2d<float, access::sample> tex [[texture(0)]],
                       texture2d<float, access::write> dest [[texture(1)]],
                       constant BloomUniforms& u [[buffer(0)]],
                       uint2 gid [[thread_position_in_grid]]) {
    if (gid.x >= dest.get_width() || gid.y >= dest.get_height()) return;
    float2 uv = uvOf(gid, dest.get_width(), dest.get_height());
    float2 t = 1.0 / float2(tex.get_width(), tex.get_height());
    float4 sum = tex.sample(clampS, uv + float2(-t.x, -t.y));
    sum += tex.sample(clampS, uv + float2(t.x, -t.y));
    sum += tex.sample(clampS, uv + float2(-t.x, t.y));
    sum += tex.sample(clampS, uv + float2(t.x, t.y));
    dest.write(sum * 0.25, gid);
}

kernel void bloom_up(texture2d<float, access::sample> src [[texture(0)]],
                     texture2d<float, access::sample> baseTex [[texture(1)]],
                     texture2d<float, access::write> dest [[texture(2)]],
                     constant BloomUniforms& u [[buffer(0)]],
                     uint2 gid [[thread_position_in_grid]]) {
    if (gid.x >= dest.get_width() || gid.y >= dest.get_height()) return;
    float2 uv = uvOf(gid, dest.get_width(), dest.get_height());
    float2 t = u.texel;
    float4 sum = src.sample(clampS, uv + float2(-t.x, -t.y));
    sum += src.sample(clampS, uv + float2(t.x, -t.y));
    sum += src.sample(clampS, uv + float2(-t.x, t.y));
    sum += src.sample(clampS, uv + float2(t.x, t.y));
    float3 base = baseTex.sample(clampS, uv).rgb;
    dest.write(float4(base + sum.rgb * 0.25, 1.0), gid);
}

kernel void bloom_final(texture2d<float, access::sample> tex [[texture(0)]],
                        texture2d<float, access::write> dest [[texture(1)]],
                        constant BloomUniforms& u [[buffer(0)]],
                        uint2 gid [[thread_position_in_grid]]) {
    if (gid.x >= dest.get_width() || gid.y >= dest.get_height()) return;
    float2 uv = uvOf(gid, dest.get_width(), dest.get_height());
    float2 t = 1.0 / float2(tex.get_width(), tex.get_height());
    float4 sum = tex.sample(clampS, uv + float2(-t.x, 0));
    sum += tex.sample(clampS, uv + float2(t.x, 0));
    sum += tex.sample(clampS, uv + float2(0, -t.y));
    sum += tex.sample(clampS, uv + float2(0, t.y));
    dest.write(float4(sum.rgb * 0.25 * u.threshold, 1.0), gid);
}

// =============================================================================
// DISPLAY
// =============================================================================

struct DisplayUniforms {
    float sizeX; float sizeY; float ditherScale; float time;
    float shaftX; float shaftY; float shaftSpread; float shaftRays; float shaftFalloff;
    float shaftSourceGlow; float shaftStrength; float shaftDrift; float shaftBg;
    float shaftVary; float shaftSpeed; float shaftWarp; float shaftPenumbra; float shaftPhaseG;
    float shaftThinRays; float shaftThinStrength; float shaftThinSharp; float shaftThinVary;
    float nearR; float nearG; float nearB; float farR; float farG; float farB; float colorExpo;
    float hazeStrength; float hazeY; float hazeThickness; float hazeScale; float hazeDrift;
    float hazePulse; float dither;
    float beamFlutter; float beamFlutterSpeed;
    float goboStrength; float goboScale; float goboDrift;
    float gustAmount; float gustRate; float gust;
    float exposure; float tonemap;
    float volSteps; float volDensity; float volExtinction; float volScale;
    float volDrift; float volJitter; float jitterX; float jitterY;
    float taaAlpha;
    float lightSway; float lightLean; float leanX; float leanY;
    float lightAngle; float windowWidth; float poolStrength;
    float windDir; float windStrength; float windWander;
};

static float hash1(float2 p) {
    int2 ip = int2(floor(p));
    uint2 q = as_type<uint2>(ip);
    uint n = q.x * 1597334677u ^ q.y * 3812015801u;
    n = (n ^ (n >> 15)) * 2246822519u;
    n = (n ^ (n >> 13)) * 3266489917u;
    n ^= n >> 16;
    return float(n & 0xFFFFFFu) * (1.0 / 16777216.0);
}

vertex float4 sand_bg_vertex(uint vid [[vertex_id]]) {
    float2 uv = float2((vid << 1) & 2, vid & 2);
    return float4(uv * 2.0 - 1.0, 0.0, 1.0);
}

// Illumination profile for the volumetric march: the cone from the source with
// SOFT, continuous striations (a periodic cosine — no floor() cell seams, so it
// cannot alias into hard edges), a moving gobo, the gust envelope and the soft
// source core. Applied per marched sample, so the result is an integral, not a
// painted shape.
static float beamSoft(float2 p, constant DisplayUniforms& u) {
    // Wind: a slow envelope + event gusts — the whole cloud flutters, then settles.
    float wind = u.gustAmount * (fbm2(float2(u.time * u.gustRate, 3.1)) * 2.0 - 1.0) + u.gust;

    // ONE source (with a gentle sway) — every beam radiates from here.
    float2 src = float2(u.shaftX, u.shaftY)
               + float2(sin(u.time * 0.11) + 0.5 * sin(u.time * 0.07),
                        0.4 * sin(u.time * 0.09)) * u.lightSway * 0.04;

    float2 d = p - src;
    float dist = max(length(d), 1e-4);
    float ang = atan2(d.x, d.y);                       // 0 = straight down
    float halfA = max(u.shaftSpread, 1.0) * 0.017453292;

    float cone = smoothstep(halfA, halfA * 0.5, abs(ang));
    float atten = exp(-max(u.shaftFalloff, 0.0) * dist);

    // Crepuscular rays as a moving NOISE FIELD across the angle, sampled on the
    // unit circle (seamless, radial → anchored at the source). Two octaves: a slow
    // BIG field and a quicker SMALL one, each advected independently, soft-
    // thresholded so beams bloom in and dissolve out at irregular, cloud-like
    // intervals — never a fixed rate, never a rigid laser fan.
    float2 ring = float2(cos(ang), sin(ang));
    float churn = 0.30 + u.volDrift * 10.0;            // Beam churn: how fast the cloud evolves
    float wander = u.shaftWarp;                        // sideways drift of the field
    float2 advBig   = float2(sin(u.time * 0.15 * churn), cos(u.time * 0.11 * churn))
                      * (2.5 + wander * 3.0) + wind * 1.5;
    float2 advSmall = float2(cos(u.time * 0.33 * churn), sin(u.time * 0.27 * churn))
                      * (4.0 + wander * 5.0) + wind * 2.5;
    float scale = max(u.volScale, 0.5);                // Cloud scale
    float bigN   = fbm2(ring * (scale * 1.7) + advBig);
    float smallN = fbm2(ring * (scale * 4.5) + advSmall);

    // Soft thresholds + distance softening → gentle bloom in / dissolve out.
    // (fbm2 spans ~0..0.875, so the bands sit around its mean.)
    float soft = clamp(u.shaftPenumbra * dist, 0.0, 1.0);
    float big   = smoothstep(mix(0.40, 0.10, soft), mix(0.64, 0.42, soft), bigN);
    float small = smoothstep(mix(0.44, 0.16, soft), mix(0.70, 0.48, soft), smallN);

    // big ↔ small mixture
    float mixBig = clamp(u.shaftVary, 0.0, 1.0);
    float field = mixBig * big + (1.0 - mixBig) * small;

    float gustEnv = fbm2(float2(u.time * u.gustRate, 7.7));
    float gustFactor = max(0.0, 1.0 + u.gustAmount * (gustEnv * 2.0 - 1.0) + u.gust);

    float cosT = clamp(d.y / dist, -1.0, 1.0);
    float ph = hgPhase(cosT, clamp(u.shaftPhaseG, 0.0, 0.99));

    float beams = cone * atten * field * ph * gustFactor;
    float glow = sourceGlowAt(p, src.x, src.y) * u.shaftSourceGlow;
    return beams + glow;
}

// The volumetric light: march screen-space rays through the medium, accumulating
// in-scattered light with Beer–Lambert transmittance. Rendered at supersampled
// size, then temporally accumulated. An integral → soft shafts that read as
// light in air, not a drawn cone.
fragment half4 sand_light(float4 pos [[position]],
                          constant DisplayUniforms& u [[buffer(0)]]) {
    float2 uv = pos.xy / float2(u.sizeX, u.sizeY);
    // One evaluation, once per pixel — the old 24-step march recomputed the same
    // value 24× for no reason. `volDensity` is the overall gain.
    float light = beamSoft(uv, u) * u.shaftStrength;
    float3 near = float3(u.nearR, u.nearG, u.nearB);
    float3 far = float3(u.farR, u.farG, u.farB);
    float3 tint = beamColor(uv, u.shaftX, u.shaftY, near, far, u.colorExpo);
    return half4(half3(light * tint * u.volDensity), 1.0h);
}

fragment half4 sand_display(float4 pos [[position]],
                            constant DisplayUniforms& u [[buffer(0)]],
                            texture2d<float, access::sample> dust [[texture(0)]],
                            texture2d<float, access::sample> bloom [[texture(1)]],
                            texture2d<float, access::sample> lightTex [[texture(2)]]) {
    float2 uv = pos.xy / float2(u.sizeX, u.sizeY);

    // The volumetric light, already soft (integrated through the medium) and
    // temporally accumulated — not an analytic cone painted over the scene.
    float3 lightRGB = lightTex.sample(clampS, uv).rgb;
    float lightAmt = dot(lightRGB, float3(0.3333333));
    float3 c = lightRGB;

    // haze at the bottom catches the light, tinted golden
    float haze = hazeAt(uv, u.hazeY, u.hazeThickness, u.hazeScale,
                        u.hazeDrift, u.hazePulse, u.time);
    c += float3(u.farR, u.farG, u.farB) * (haze * (0.2 + lightAmt) * u.hazeStrength);

    // dust (HDR additive) + bloom, kept linear until the single tonemap below
    c += dust.sample(clampS, uv).rgb;
    c += bloom.sample(clampS, uv).rgb;

    // one exposure + tonemap before 8-bit output — never let additive clamp to
    // white (ACES filmic approximation, Krzysztof Narkowicz)
    c = max(c * u.exposure, float3(0.0));
    float3 aces = clamp((c * (2.51 * c + 0.03)) / (c * (2.43 * c + 0.59) + 0.14), 0.0, 1.0);
    c = mix(clamp(c, 0.0, 1.0), aces, clamp(u.tonemap, 0.0, 1.0));

    // subtle static texture to hide banding — not a film-grain overlay
    float g = hash1(pos.xy * u.ditherScale + fract(u.time) * 91.0) - 0.5;
    c += g * u.dither;
    return half4(half3(max(c, 0.0)), 1.0h);
}
