import AppKit
import Metal
import MetalKit
import QuartzCore
import simd

// Uniform structs — layout must match SandShaders.metal (floats only, so the
// Swift and Metal layouts agree without alignment surprises).

struct BloomUniforms { var texel: SIMD2<Float>; var threshold: Float; var pad: Float }
struct DustParticle {
    var pos: SIMD2<Float>; var vel: SIMD2<Float>
    var z: Float; var age: Float; var life: Float; var seed: Float
}
struct DustUpdateUniforms {
    var dt: Float; var time: Float
    var swirl: Float; var swirlScale: Float; var drift: Float
    var drag: Float; var brownian: Float
    var pointerX: Float; var pointerY: Float; var pointerActive: Float
    var obstacleRadius: Float; var obstaclePad: Float; var obstacleCount: Float
    // couplings (were computed app-side but never sent before)
    var parallaxDepth: Float
    var forceX: Float; var forceY: Float; var shear: Float
    var gust: Float; var breath: Float
    var pointerVelX: Float; var pointerVelY: Float
    var windDir: Float; var windStrength: Float; var windWander: Float
    var gustAmount: Float; var gustRate: Float
}
struct DustRenderUniforms {
    var time: Float; var size: Float; var fog: Float; var base: Float; var brightness: Float
    var shaftX: Float; var shaftY: Float; var shaftSpread: Float; var shaftRays: Float
    var shaftFalloff: Float; var shaftSourceGlow: Float; var shaftStrength: Float
    var shaftDrift: Float
    var shaftVary: Float; var shaftSpeed: Float; var shaftWarp: Float
    var shaftPenumbra: Float; var shaftPhaseG: Float
    var shaftThinRays: Float; var shaftThinStrength: Float; var shaftThinSharp: Float
    var shaftThinVary: Float
    var nearR: Float; var nearG: Float; var nearB: Float
    var farR: Float; var farG: Float; var farB: Float; var colorExpo: Float
    var layers: Float; var nearScale: Float; var nearBrightness: Float; var nearBlur: Float
    var sparkle: Float; var sparkleSpeed: Float
    var domainPad: Float
    // beam life + colour (must match SandShaders.metal DustRenderUniforms)
    var sparkleR: Float; var sparkleG: Float; var sparkleB: Float
    var beamFlutter: Float; var beamFlutterSpeed: Float
    var goboStrength: Float; var goboScale: Float; var goboDrift: Float
    var gustAmount: Float; var gustRate: Float
    var parallaxX: Float; var parallaxY: Float; var parallaxDepth: Float
    var layerClose: Float; var layerNear: Float; var layerMid: Float; var layerFar: Float
    var layerHaze: Float
}
struct DisplayUniforms {
    var sizeX: Float; var sizeY: Float; var ditherScale: Float; var time: Float
    var shaftX: Float; var shaftY: Float; var shaftSpread: Float; var shaftRays: Float
    var shaftFalloff: Float; var shaftSourceGlow: Float; var shaftStrength: Float
    var shaftDrift: Float; var shaftBg: Float
    var shaftVary: Float; var shaftSpeed: Float; var shaftWarp: Float
    var shaftPenumbra: Float; var shaftPhaseG: Float
    var shaftThinRays: Float; var shaftThinStrength: Float; var shaftThinSharp: Float
    var shaftThinVary: Float
    var nearR: Float; var nearG: Float; var nearB: Float
    var farR: Float; var farG: Float; var farB: Float; var colorExpo: Float
    var hazeStrength: Float; var hazeY: Float; var hazeThickness: Float; var hazeScale: Float
    var hazeDrift: Float; var hazePulse: Float; var dither: Float
    var beamFlutter: Float; var beamFlutterSpeed: Float
    var goboStrength: Float; var goboScale: Float; var goboDrift: Float
    var gustAmount: Float; var gustRate: Float; var gust: Float
    var exposure: Float; var tonemap: Float
    var volSteps: Float; var volDensity: Float; var volExtinction: Float; var volScale: Float
    var volDrift: Float; var volJitter: Float; var jitterX: Float; var jitterY: Float
    var taaAlpha: Float
    var lightSway: Float; var lightLean: Float; var leanX: Float; var leanY: Float
    var lightAngle: Float; var windowWidth: Float; var poolStrength: Float
    var windDir: Float; var windStrength: Float; var windWander: Float
}

/// Dust floating in a dark room, lit by soft beams. Langevin particles collide
/// with moving solids (pointer + UI rects). See TRUTH.md.
@MainActor
public final class SandPipeline: NSObject, MTKViewDelegate {
    public let device: MTLDevice
    private let queue: MTLCommandQueue

    private var pDustUpdate: MTLComputePipelineState!
    private var pPrefilter: MTLComputePipelineState!
    private var pDown: MTLComputePipelineState!
    private var pUp: MTLComputePipelineState!
    private var pFinal: MTLComputePipelineState!
    private var pDisplay: MTLRenderPipelineState!
    private var pDustRender: MTLRenderPipelineState!
    private var pLight: MTLRenderPipelineState!

    private var bloomDown: [MTLTexture] = []
    private var bloomUp: [MTLTexture] = []
    private var bloomOut: MTLTexture?
    // The light is a soft wash sampled linearly by dust + display, so it's
    // rendered at a fraction of the drawable and upscaled — ~4× cheaper, no
    // visible loss. (This single pass was the dominant GPU cost.)
    private var lightNow: MTLTexture?
    private let lightScale: Float = 0.5
    private var dustTarget: MTLTexture?
    private var dither: MTLTexture?
    private var dustBuffer: MTLBuffer?
    private var obstacleBuffer: MTLBuffer?
    private var dustCount = 0

    private var drawSize = (w: 0, h: 0)
    private var bloomLevelsBuilt = -1
    private var lastTime = CACurrentMediaTime()
    private var elapsed: Float = 0
    private var fpsTimer: Double = 0
    private var fpsFrames = 0

    private let maxObstacles = 16

    public var config = SandConfig()
    public var inputs = SandInputs()
    public var inputsProvider: (@MainActor () -> SandInputs)?
    public private(set) var fps: Double = 0
    public private(set) var ready = false

    public static var metalAvailable: Bool {
        Bundle.main.url(forResource: "default", withExtension: "metallib") != nil
    }

    public init?(device: MTLDevice) {
        guard let q = device.makeCommandQueue() else { return nil }
        self.device = device
        self.queue = q
        super.init()
        dither = makeNoiseTexture(device, side: 64)
        obstacleBuffer = device.makeBuffer(length: maxObstacles * MemoryLayout<SIMD4<Float>>.stride,
                                           options: .storageModeShared)
        ready = buildPipelines()
    }

    private func buildPipelines() -> Bool {
        let lib: MTLLibrary
        if let l = try? device.makeDefaultLibrary(bundle: Bundle.main) { lib = l }
        else if let l = device.makeDefaultLibrary() { lib = l }
        else { return false }
        func comp(_ n: String) -> MTLComputePipelineState? {
            guard let f = lib.makeFunction(name: n) else { return nil }
            return try? device.makeComputePipelineState(function: f)
        }
        guard let du = comp("dust_update"),
              let pre = comp("bloom_prefilter"),
              let down = comp("bloom_down"), let up = comp("bloom_up"),
              let fin = comp("bloom_final")
        else { return false }
        pDustUpdate = du
        pPrefilter = pre; pDown = down; pUp = up; pFinal = fin

        guard let vf = lib.makeFunction(name: "sand_bg_vertex"),
              let ff = lib.makeFunction(name: "sand_display") else { return false }
        let d = MTLRenderPipelineDescriptor()
        d.vertexFunction = vf; d.fragmentFunction = ff
        d.colorAttachments[0].pixelFormat = .bgra8Unorm
        guard let display = try? device.makeRenderPipelineState(descriptor: d) else { return false }
        pDisplay = display

        // volumetric light pass (renders the march into an rgba16Float target)
        guard let lf = lib.makeFunction(name: "sand_light") else { return false }
        let lpd = MTLRenderPipelineDescriptor()
        lpd.vertexFunction = vf; lpd.fragmentFunction = lf
        lpd.colorAttachments[0].pixelFormat = .rgba16Float
        guard let light = try? device.makeRenderPipelineState(descriptor: lpd) else { return false }
        pLight = light   // one pass, evaluated once per pixel (no march / TAA)

        guard let dvert = lib.makeFunction(name: "dust_vertex"),
              let dfrag = lib.makeFunction(name: "dust_fragment") else { return false }
        let dr = MTLRenderPipelineDescriptor()
        dr.vertexFunction = dvert; dr.fragmentFunction = dfrag
        let a = dr.colorAttachments[0]!
        a.pixelFormat = .rgba16Float
        a.isBlendingEnabled = true
        a.rgbBlendOperation = .add
        a.alphaBlendOperation = .add
        a.sourceRGBBlendFactor = .one
        a.destinationRGBBlendFactor = .one
        a.sourceAlphaBlendFactor = .one
        a.destinationAlphaBlendFactor = .one
        guard let dustRender = try? device.makeRenderPipelineState(descriptor: dr) else { return false }
        pDustRender = dustRender
        return true
    }

    private func makeNoiseTexture(_ device: MTLDevice, side: Int) -> MTLTexture? {
        let d = MTLTextureDescriptor.texture2DDescriptor(
            pixelFormat: .rgba8Unorm, width: side, height: side, mipmapped: false)
        d.usage = [.shaderRead]
        guard let tex = device.makeTexture(descriptor: d) else { return nil }
        var bytes = [UInt8](repeating: 0, count: side * side * 4)
        for i in stride(from: 0, to: bytes.count, by: 4) {
            let v = UInt8(Int.random(in: 0...255))
            bytes[i] = v; bytes[i + 1] = v; bytes[i + 2] = v; bytes[i + 3] = 255
        }
        tex.replace(region: MTLRegionMake2D(0, 0, side, side), mipmapLevel: 0,
                    withBytes: bytes, bytesPerRow: side * 4)
        return tex
    }

    private func makeTex(_ w: Int, _ h: Int, _ f: MTLPixelFormat) -> MTLTexture? {
        let d = MTLTextureDescriptor.texture2DDescriptor(
            pixelFormat: f, width: max(1, w), height: max(1, h), mipmapped: false)
        d.usage = [.shaderRead, .shaderWrite]
        d.storageMode = .private
        return device.makeTexture(descriptor: d)
    }

    private func makeRenderTex(_ w: Int, _ h: Int, _ f: MTLPixelFormat) -> MTLTexture? {
        let d = MTLTextureDescriptor.texture2DDescriptor(
            pixelFormat: f, width: max(1, w), height: max(1, h), mipmapped: false)
        d.usage = [.shaderRead, .renderTarget]
        d.storageMode = .private
        return device.makeTexture(descriptor: d)
    }

    private func syncTextures(drawableSize: CGSize) {
        let w = max(1, Int(drawableSize.width))
        let h = max(1, Int(drawableSize.height))
        let levels = max(1, min(6, Int(config.bloomIterations)))
        guard w != drawSize.w || h != drawSize.h || levels != bloomLevelsBuilt else { return }
        let sizeChanged = w != drawSize.w || h != drawSize.h
        drawSize = (w, h)
        bloomLevelsBuilt = levels
        if sizeChanged { dustTarget = makeRenderTex(w, h, .rgba16Float) }

        let aspect = max(1.0, Double(w) / Double(h))
        let bH = 192
        let bW = max(32, Int(Double(bH) * aspect))
        bloomDown.removeAll(); bloomUp.removeAll()
        var bw = bW, bh = bH
        for _ in 0...levels {
            guard bw >= 2, bh >= 2 else { break }
            bloomDown.append(makeTex(bw, bh, .rgba16Float)!)
            bloomUp.append(makeTex(bw, bh, .rgba16Float)!)
            bw >>= 1; bh >>= 1
        }
        bloomOut = makeTex(bW, bH, .rgba16Float)

        // Half-res light (soft, upscaled) — the dominant GPU pass, ~4× cheaper.
        let lw = max(1, Int(Float(w) * lightScale))
        let lh = max(1, Int(Float(h) * lightScale))
        if sizeChanged || lightNow == nil {
            lightNow = makeRenderTex(lw, lh, .rgba16Float)
        }
    }

    public nonisolated func mtkView(_ view: MTKView, drawableSizeWillChange size: CGSize) {}
    public nonisolated func draw(in view: MTKView) {
        MainActor.assumeIsolated { self.render(view) }
    }

    private func render(_ view: MTKView) {
        if let provider = inputsProvider { inputs = provider() }
        syncTextures(drawableSize: view.drawableSize)
        syncDust()
        guard ready,
              let dustT = dustTarget, let bOut = bloomOut, let lNow = lightNow,
              let drawable = view.currentDrawable, let rpd = view.currentRenderPassDescriptor,
              let cmd = queue.makeCommandBuffer()
        else { return }

        let now = CACurrentMediaTime()
        let dt = Float(min(0.05, max(0.0, now - lastTime)))
        lastTime = now
        elapsed += dt

        fpsFrames += 1; fpsTimer += Double(dt)
        if fpsTimer >= 0.5 { fps = Double(fpsFrames) / fpsTimer; fpsFrames = 0; fpsTimer = 0 }

        updateDust(cmd, dt: dt)
        encodeLight(cmd, into: lNow)                       // one pass, once per pixel
        encodeDust(cmd, into: dustT, light: lNow)          // dust lit by the light
        encodeBloom(cmd, source: lNow, into: bOut)         // bloom the light (soft glow)
        encodeDisplay(cmd, rpd: rpd, dust: dustT, bloom: bOut, light: lNow)
        cmd.present(drawable)
        cmd.commit()
    }

    // MARK: - dust

    private func syncDust() {
        let count = max(0, Int(config.dustCount))
        guard count != dustCount else { return }
        dustCount = count
        guard count > 0 else { dustBuffer = nil; return }
        var parts = [DustParticle](repeating: DustParticle(pos: .zero, vel: .zero, z: 0,
                                                           age: 0, life: 8, seed: 0), count: count)
        for i in 0..<count {
            parts[i].pos = SIMD2(Float.random(in: 0...1), Float.random(in: 0...1))
            parts[i].z = Float.random(in: 0...1)
            parts[i].age = Float.random(in: 0...1) * 18
            parts[i].life = Float.random(in: 8...18)
            parts[i].seed = Float.random(in: 0...1)
        }
        dustBuffer = device.makeBuffer(bytes: parts,
                                       length: count * MemoryLayout<DustParticle>.stride,
                                       options: .storageModeShared)
    }

    private func updateDust(_ cmd: MTLCommandBuffer, dt: Float) {
        guard dustCount > 0, let buf = dustBuffer,
              let obs = obstacleBuffer, let enc = cmd.makeComputeCommandEncoder() else { return }

        let rects = Array(inputs.obstacleRects.prefix(maxObstacles))
        let ptr = obs.contents().bindMemory(to: SIMD4<Float>.self, capacity: maxObstacles)
        for i in 0..<maxObstacles { ptr[i] = i < rects.count ? rects[i] : SIMD4<Float>(0, 0, 0, 0) }

        var u = DustUpdateUniforms(
            dt: dt, time: elapsed,
            swirl: Float(config.swirl), swirlScale: Float(config.swirlScale),
            drift: Float(config.drift), drag: Float(config.drag), brownian: Float(config.brownian),
            pointerX: inputs.pointer.x, pointerY: inputs.pointer.y,
            pointerActive: inputs.hasPointer ? 1 : 0,
            obstacleRadius: Float(config.obstacleRadius), obstaclePad: Float(config.obstaclePad),
            obstacleCount: Float(rects.count),
            parallaxDepth: Float(config.parallaxDepth),
            forceX: inputs.force.x, forceY: inputs.force.y, shear: inputs.shear,
            gust: inputs.gust, breath: inputs.breath,
            pointerVelX: inputs.pointerVelocity.x, pointerVelY: inputs.pointerVelocity.y,
            windDir: Float(config.windDir), windStrength: Float(config.windStrength),
            windWander: Float(config.windWander),
            gustAmount: Float(config.gustAmount), gustRate: Float(config.gustRate))
        enc.setComputePipelineState(pDustUpdate)
        enc.setBuffer(buf, offset: 0, index: 0)
        enc.setBytes(&u, length: MemoryLayout<DustUpdateUniforms>.stride, index: 1)
        enc.setBuffer(obs, offset: 0, index: 2)
        enc.dispatchThreads(MTLSize(width: dustCount, height: 1, depth: 1),
                            threadsPerThreadgroup: MTLSize(width: 64, height: 1, depth: 1))
        enc.endEncoding()
    }

    private func encodeDust(_ cmd: MTLCommandBuffer, into target: MTLTexture, light: MTLTexture) {
        guard dustCount > 0, let buf = dustBuffer else { return }
        let rpd = MTLRenderPassDescriptor()
        rpd.colorAttachments[0].texture = target
        rpd.colorAttachments[0].loadAction = .clear
        rpd.colorAttachments[0].clearColor = MTLClearColor(red: 0, green: 0, blue: 0, alpha: 1)
        rpd.colorAttachments[0].storeAction = .store
        guard let enc = cmd.makeRenderCommandEncoder(descriptor: rpd) else { return }
        let near = config.shaftColorNear
        let far = config.shaftColor
        var u = DustRenderUniforms(
            time: elapsed, size: Float(config.dustSize), fog: Float(config.dustFog),
            base: Float(config.dustBase), brightness: Float(config.dustBrightness),
            shaftX: Float(config.shaftX), shaftY: Float(config.shaftY),
            shaftSpread: Float(config.shaftSpread), shaftRays: Float(config.shaftRays),
            shaftFalloff: Float(config.shaftFalloff), shaftSourceGlow: Float(config.shaftSourceGlow),
            shaftStrength: Float(config.shaftStrength), shaftDrift: Float(config.shaftDrift),
            shaftVary: Float(config.shaftVary), shaftSpeed: Float(config.shaftSpeed),
            shaftWarp: Float(config.shaftWarp), shaftPenumbra: Float(config.shaftPenumbra),
            shaftPhaseG: Float(config.shaftPhaseG),
            shaftThinRays: Float(config.shaftThinRays), shaftThinStrength: Float(config.shaftThinStrength),
            shaftThinSharp: Float(config.shaftThinSharp), shaftThinVary: Float(config.shaftThinVary),
            nearR: near.x, nearG: near.y, nearB: near.z,
            farR: far.x, farG: far.y, farB: far.z,
            colorExpo: Float(config.shaftColorFalloff),
            layers: Float(config.dustLayers), nearScale: Float(config.dustNearScale),
            nearBrightness: Float(config.dustNearBrightness), nearBlur: Float(config.dustNearBlur),
            sparkle: Float(config.sparkle), sparkleSpeed: Float(config.sparkleSpeed),
            domainPad: 0,
            sparkleR: config.sparkleColor.x, sparkleG: config.sparkleColor.y,
            sparkleB: config.sparkleColor.z,
            beamFlutter: Float(config.beamFlutter), beamFlutterSpeed: Float(config.beamFlutterSpeed),
            goboStrength: Float(config.goboStrength), goboScale: Float(config.goboScale),
            goboDrift: Float(config.goboDrift),
            gustAmount: Float(config.gustAmount), gustRate: Float(config.gustRate),
            parallaxX: inputs.parallax.x, parallaxY: inputs.parallax.y,
            parallaxDepth: Float(config.parallaxDepth),
            layerClose: config.layerClose ? 1 : 0, layerNear: config.layerNear ? 1 : 0,
            layerMid: config.layerMid ? 1 : 0, layerFar: config.layerFar ? 1 : 0,
            layerHaze: config.layerHaze ? 1 : 0)
        enc.setRenderPipelineState(pDustRender)
        enc.setVertexBuffer(buf, offset: 0, index: 0)
        enc.setVertexBytes(&u, length: MemoryLayout<DustRenderUniforms>.stride, index: 1)
        enc.setVertexTexture(light, index: 0)   // dust is lit by the volumetric light
        enc.drawPrimitives(type: .point, vertexStart: 0, vertexCount: dustCount)
        enc.endEncoding()
    }

    private func encodeBloom(_ cmd: MTLCommandBuffer, source: MTLTexture, into out: MTLTexture) {
        guard bloomDown.count > 1 else { return }
        if let enc = cmd.makeComputeCommandEncoder() {
            var u = BloomUniforms(texel: .zero, threshold: Float(config.bloomThreshold), pad: 0)
            enc.setTexture(source, index: 0)
            enc.setTexture(bloomDown[0], index: 1)
            enc.setBytes(&u, length: MemoryLayout<BloomUniforms>.stride, index: 0)
            dispatch(enc, pPrefilter, bloomDown[0].width, bloomDown[0].height)
            enc.endEncoding()
        }
        for i in 1..<bloomDown.count {
            if let enc = cmd.makeComputeCommandEncoder() {
                var u = BloomUniforms(texel: .zero, threshold: 0, pad: 0)
                enc.setTexture(bloomDown[i - 1], index: 0)
                enc.setTexture(bloomDown[i], index: 1)
                enc.setBytes(&u, length: MemoryLayout<BloomUniforms>.stride, index: 0)
                dispatch(enc, pDown, bloomDown[i].width, bloomDown[i].height)
                enc.endEncoding()
            }
        }
        let last = bloomDown.count - 1
        copyTexture(cmd, from: bloomDown[last], to: bloomUp[last])
        for i in stride(from: last - 1, through: 0, by: -1) {
            if let enc = cmd.makeComputeCommandEncoder() {
                var u = BloomUniforms(texel: SIMD2(1.0 / Float(bloomDown[i + 1].width),
                                                   1.0 / Float(bloomDown[i + 1].height)),
                                      threshold: 0, pad: 0)
                enc.setTexture(bloomUp[i + 1], index: 0)
                enc.setTexture(bloomDown[i], index: 1)
                enc.setTexture(bloomUp[i], index: 2)
                enc.setBytes(&u, length: MemoryLayout<BloomUniforms>.stride, index: 0)
                dispatch(enc, pUp, bloomUp[i].width, bloomUp[i].height)
                enc.endEncoding()
            }
        }
        if let enc = cmd.makeComputeCommandEncoder() {
            var u = BloomUniforms(texel: .zero, threshold: Float(config.bloomIntensity), pad: 0)
            enc.setTexture(bloomUp[0], index: 0)
            enc.setTexture(out, index: 1)
            enc.setBytes(&u, length: MemoryLayout<BloomUniforms>.stride, index: 0)
            dispatch(enc, pFinal, out.width, out.height)
            enc.endEncoding()
        }
    }

    private func dispatch(_ enc: MTLComputeCommandEncoder, _ pipe: MTLComputePipelineState,
                          _ w: Int, _ h: Int) {
        enc.setComputePipelineState(pipe)
        enc.dispatchThreads(MTLSize(width: w, height: h, depth: 1),
                            threadsPerThreadgroup: MTLSize(width: 8, height: 8, depth: 1))
    }

    private func copyTexture(_ cmd: MTLCommandBuffer, from: MTLTexture, to: MTLTexture) {
        guard let blit = cmd.makeBlitCommandEncoder() else { return }
        let w = min(from.width, to.width), h = min(from.height, to.height)
        blit.copy(from: from, sourceSlice: 0, sourceLevel: 0,
                  sourceOrigin: MTLOrigin(x: 0, y: 0, z: 0),
                  sourceSize: MTLSize(width: w, height: h, depth: 1),
                  to: to, destinationSlice: 0, destinationLevel: 0,
                  destinationOrigin: MTLOrigin(x: 0, y: 0, z: 0))
        blit.endEncoding()
    }

    /// One uniform block shared by the light pass, its temporal accumulation and
    /// the display composite (they read different subsets).
    private func displayUniforms(sizeX: Float, sizeY: Float, taa: Float) -> DisplayUniforms {
        let col = config.shaftColor
        let near = config.shaftColorNear
        return DisplayUniforms(
            sizeX: sizeX, sizeY: sizeY, ditherScale: 1.0, time: elapsed,
            shaftX: Float(config.shaftX), shaftY: Float(config.shaftY),
            shaftSpread: Float(config.shaftSpread), shaftRays: Float(config.shaftRays),
            shaftFalloff: Float(config.shaftFalloff), shaftSourceGlow: Float(config.shaftSourceGlow),
            shaftStrength: Float(config.shaftStrength), shaftDrift: Float(config.shaftDrift),
            shaftBg: Float(config.shaftBg),
            shaftVary: Float(config.shaftVary), shaftSpeed: Float(config.shaftSpeed),
            shaftWarp: Float(config.shaftWarp), shaftPenumbra: Float(config.shaftPenumbra),
            shaftPhaseG: Float(config.shaftPhaseG),
            shaftThinRays: Float(config.shaftThinRays), shaftThinStrength: Float(config.shaftThinStrength),
            shaftThinSharp: Float(config.shaftThinSharp), shaftThinVary: Float(config.shaftThinVary),
            nearR: near.x, nearG: near.y, nearB: near.z,
            farR: col.x, farG: col.y, farB: col.z,
            colorExpo: Float(config.shaftColorFalloff),
            hazeStrength: Float(config.hazeStrength), hazeY: Float(config.hazeY),
            hazeThickness: Float(config.hazeThickness), hazeScale: Float(config.hazeScale),
            hazeDrift: Float(config.hazeDrift), hazePulse: Float(config.hazePulse),
            dither: Float(config.dither),
            beamFlutter: Float(config.beamFlutter), beamFlutterSpeed: Float(config.beamFlutterSpeed),
            goboStrength: Float(config.goboStrength), goboScale: Float(config.goboScale),
            goboDrift: Float(config.goboDrift),
            gustAmount: Float(config.gustAmount), gustRate: Float(config.gustRate),
            gust: inputs.gust,
            exposure: Float(config.exposure), tonemap: Float(config.tonemap),
            volSteps: Float(config.volSteps), volDensity: Float(config.volDensity),
            volExtinction: Float(config.volExtinction), volScale: Float(config.volScale),
            volDrift: Float(config.volDrift), volJitter: Float(config.volJitter),
            jitterX: inputs.jitter.x, jitterY: inputs.jitter.y,
            taaAlpha: taa,
            lightSway: Float(config.lightSway), lightLean: Float(config.lightLean),
            leanX: inputs.parallax.x, leanY: inputs.parallax.y,
            lightAngle: Float(config.lightAngle), windowWidth: Float(config.windowWidth),
            poolStrength: Float(config.poolStrength),
            windDir: Float(config.windDir), windStrength: Float(config.windStrength),
            windWander: Float(config.windWander))
    }

    /// The volumetric light march, rendered at supersampled size.
    private func encodeLight(_ cmd: MTLCommandBuffer, into target: MTLTexture) {
        let rpd = MTLRenderPassDescriptor()
        rpd.colorAttachments[0].texture = target
        rpd.colorAttachments[0].loadAction = .clear
        rpd.colorAttachments[0].clearColor = MTLClearColor(red: 0, green: 0, blue: 0, alpha: 1)
        rpd.colorAttachments[0].storeAction = .store
        guard let enc = cmd.makeRenderCommandEncoder(descriptor: rpd) else { return }
        var u = displayUniforms(sizeX: Float(target.width), sizeY: Float(target.height), taa: 1)
        enc.setRenderPipelineState(pLight)
        enc.setFragmentBytes(&u, length: MemoryLayout<DisplayUniforms>.stride, index: 0)
        enc.drawPrimitives(type: .triangle, vertexStart: 0, vertexCount: 3)
        enc.endEncoding()
    }

    private func encodeDisplay(_ cmd: MTLCommandBuffer, rpd: MTLRenderPassDescriptor,
                               dust: MTLTexture, bloom: MTLTexture, light: MTLTexture) {
        guard let enc = cmd.makeRenderCommandEncoder(descriptor: rpd) else { return }
        let w = Float(rpd.colorAttachments[0].texture?.width ?? 1)
        let h = Float(rpd.colorAttachments[0].texture?.height ?? 1)
        var u = displayUniforms(sizeX: w, sizeY: h, taa: Float(config.taaAlpha))
        enc.setRenderPipelineState(pDisplay)
        enc.setFragmentBytes(&u, length: MemoryLayout<DisplayUniforms>.stride, index: 0)
        enc.setFragmentTexture(dust, index: 0)
        enc.setFragmentTexture(bloom, index: 1)
        enc.setFragmentTexture(light, index: 2)
        enc.drawPrimitives(type: .triangle, vertexStart: 0, vertexCount: 3)
        enc.endEncoding()
    }
}
