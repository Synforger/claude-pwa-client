import AVFoundation
import AudioToolbox
import Capacitor
import Foundation
import WebRTC

/// 通話のマイクとスピーカーの出入りを受け持つ部品 (= WebRTC の内蔵の部品の代わりに、 WebRTC へ渡す)。
///
/// 内蔵の部品と同じく、 iPhone の通話用の音の処理 (= VoiceProcessingIO。 エコーキャンセルもここ) を開く。 違うのは 2 つ:
///   - 他の app の音を下げる量 (= ダッキング) を最小にする (= `kAUVoiceIOProperty_OtherAudioDuckingConfiguration`、
///     iOS 17)。 内蔵の部品はこの設定を持たず、 iOS の既定 (= 大きく下げる) のままになる
///   - 🎙 がオフの間は、 マイクの入力そのものを閉じる (= 内蔵の部品は、 WebRTC の音の道を切ってもマイクを取ったまま)
///
/// WebRTC は音の設定 (= AVAudioSession) をこの部品に任せる。 種類 (= 通話・他の app と混ぜる) は Pipecat が決め、
/// 有効にする / 戻すのはここで行う。
///
/// 組み方は WebRTC の `RTCAudioDevice` の作者の見本 (= https://github.com/mstyura/RTCAudioDevice の
/// `AUAudioUnitRTCAudioDevice`、 MIT) に倣う。 状態は WebRTC の音の thread でだけ触り、 外からの切り替え
/// (= 🎙、 割り込み、 経路の変更) は `dispatchAsync` でその thread へ渡す。
final class CallAudioDevice: NSObject {
    static let shared = CallAudioDevice()

    private let session = AVAudioSession.sharedInstance()
    private let guardQueue = DispatchQueue(label: "CallAudioDevice")

    private var unit: AUAudioUnit?
    private var observers: [NSObjectProtocol] = []
    private var wantsPlayout = false
    private var wantsRecording = false
    private var interrupted = false
    private var sessionActive = false

    // 外 (= plugin の main thread) からも読み書きする 2 つは guardQueue で守る。
    private var delegate_: RTCAudioDeviceDelegate?
    private var delegate: RTCAudioDeviceDelegate? {
        get { guardQueue.sync { delegate_ } }
        set { guardQueue.sync { delegate_ = newValue } }
    }
    private var micOn_ = true
    private var micOn: Bool {
        get { guardQueue.sync { micOn_ } }
        set { guardQueue.sync { micOn_ = newValue } }
    }

    private var inputFormat: AVAudioFormat?
    private var outputFormat: AVAudioFormat?

    /// 🎙 の入 / 切 (= 切の間はマイクの入力を閉じる。 声はそのまま鳴る)。
    func setMic(_ on: Bool) {
        micOn = on
        delegate?.dispatchAsync { self.update() }
    }

    // MARK: - 音の部品を、 今欲しい形に合わせる

    private func update() {
        guard let unit else { return }
        let record = wantsRecording && micOn
        let play = wantsPlayout
        guard let delegate, record || play, !interrupted else {
            release(unit, reason: "idle")
            deactivateSession()
            return
        }
        activateSession()

        if unit.isInputEnabled != record {
            release(unit, reason: record ? "open the microphone" : "close the microphone")
            unit.isInputEnabled = record
        }
        if unit.isOutputEnabled != play {
            release(unit, reason: play ? "open the speaker" : "close the speaker")
            unit.isOutputEnabled = play
        }

        let rate = session.sampleRate
        if record {
            let format = Self.pcm16(rate: rate, channels: session.inputNumberOfChannels)
            let bus = unit.outputBusses[1]  // 入力の bus 1 の出口 = マイクの音
            if bus.format != format {
                release(unit, reason: "recording format")
                do { try bus.setFormat(format) } catch { log("recording format failed: \(error)"); return }
            }
            if inputFormat != format {
                inputFormat = format
                delegate.notifyAudioInputParametersChange()
            }
            let deliver = delegate.deliverRecordedData
            let render = unit.renderBlock
            let renderRecorded: RTCAudioDeviceRenderRecordedDataBlock = { flags, time, busNumber, frames, data, _ in
                render(flags, time, frames, busNumber, data, nil)
            }
            unit.inputHandler = { flags, time, frames, busNumber in
                _ = deliver(flags, time, busNumber, frames, nil, nil, renderRecorded)
            }
        }
        if play {
            let format = Self.pcm16(rate: rate, channels: session.outputNumberOfChannels)
            let bus = unit.inputBusses[0]  // 出力の bus 0 の入口 = 鳴らす声
            if bus.format != format {
                release(unit, reason: "playout format")
                do { try bus.setFormat(format) } catch { log("playout format failed: \(error)"); return }
            }
            if outputFormat != format {
                outputFormat = format
                delegate.notifyAudioOutputParametersChange()
            }
            if unit.outputProvider == nil {
                let pull = delegate.getPlayoutData
                unit.outputProvider = { flags, time, frames, busNumber, data in
                    pull(flags, time, busNumber, frames, data)
                }
            }
        }

        if !unit.renderResourcesAllocated {
            do { try unit.allocateRenderResources() } catch { log("allocate failed: \(error)"); return }
            applyDucking(unit)
        }
        if !unit.isRunning {
            do { try unit.startHardware() } catch { log("start failed: \(error)"); return }
            log("running (microphone \(record ? "open" : "closed"), speaker \(play ? "open" : "closed"), \(Int(rate)) Hz)")
        }
    }

    /// 止めて資源を返す (= 入出力の切り替えと形の変更は、 止めた部品にしかできない)。
    private func release(_ unit: AUAudioUnit, reason: String) {
        if unit.isRunning {
            unit.stopHardware()
            delegate?.notifyAudioInputInterrupted()
            delegate?.notifyAudioOutputInterrupted()
            log("stopped (\(reason))")
        }
        if unit.renderResourcesAllocated { unit.deallocateRenderResources() }
    }

    /// 他の app の音を下げる量を最小にする。 設定できたかは読み戻して log に出す (= 実機の確かめの手がかり)。
    private func applyDucking(_ unit: AUAudioUnit) {
        guard #available(iOS 17.0, *) else {
            log("ducking left to iOS (needs iOS 17)")
            return
        }
        guard let audioUnit = (unit as? AUAudioUnitV2Bridge)?.audioUnit else {
            log("ducking not set: no underlying audio unit")
            return
        }
        var config = AUVoiceIOOtherAudioDuckingConfiguration(
            mEnableAdvancedDucking: false, mDuckingLevel: .min)
        let size = UInt32(MemoryLayout<AUVoiceIOOtherAudioDuckingConfiguration>.size)
        let set = AudioUnitSetProperty(
            audioUnit, kAUVoiceIOProperty_OtherAudioDuckingConfiguration, kAudioUnitScope_Global, 0, &config, size)
        var readBack = AUVoiceIOOtherAudioDuckingConfiguration()
        var readSize = size
        let get = AudioUnitGetProperty(
            audioUnit, kAUVoiceIOProperty_OtherAudioDuckingConfiguration, kAudioUnitScope_Global, 0, &readBack,
            &readSize)
        log("ducking set=\(set) get=\(get) level=\(readBack.mDuckingLevel.rawValue) advanced=\(readBack.mEnableAdvancedDucking)")
    }

    private func activateSession() {
        guard !sessionActive else { return }
        do {
            try session.setActive(true)
            sessionActive = true
        } catch {
            log("session activation failed: \(error)")
        }
    }

    /// 通話が終わったら戻す (= 他の app に音を戻してよいと知らせる)。
    private func deactivateSession() {
        guard sessionActive else { return }
        sessionActive = false
        do { try session.setActive(false, options: .notifyOthersOnDeactivation) } catch {
            log("session deactivation failed: \(error)")
        }
    }

    private static func pcm16(rate: Double, channels: Int) -> AVAudioFormat {
        AVAudioFormat(
            commonFormat: .pcmFormatInt16, sampleRate: rate, channels: AVAudioChannelCount(max(1, min(2, channels))),
            interleaved: true)!
    }

    private func log(_ message: String) {
        CAPLog.print("[CallAudio] \(message)")
    }

    // MARK: - 音の設定の知らせ (= 電話の着信などの割り込み、 イヤホンの抜き差し、 音の仕組みの作り直し)

    private func observeSession() {
        let center = NotificationCenter.default
        observers = [
            center.addObserver(forName: AVAudioSession.interruptionNotification, object: session, queue: nil) {
                [weak self] note in
                guard let self, let raw = note.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt,
                      let type = AVAudioSession.InterruptionType(rawValue: raw) else { return }
                let reason = (note.userInfo?[AVAudioSessionInterruptionReasonKey] as? UInt)
                    .flatMap(AVAudioSession.InterruptionReason.init(rawValue:))
                // app が裏で止められていた事の知らせは、 割り込みではない (= 見本と同じ扱い)
                if type == .began, reason == .appWasSuspended { return }
                self.log("interruption \(type == .began ? "began" : "ended")")
                self.delegate?.dispatchAsync {
                    self.interrupted = type == .began
                    if self.interrupted { self.sessionActive = false }
                    self.update()
                }
            },
            center.addObserver(forName: AVAudioSession.routeChangeNotification, object: session, queue: nil) {
                [weak self] _ in
                guard let self else { return }
                self.delegate?.dispatchAsync { self.update() }
            },
            center.addObserver(forName: AVAudioSession.mediaServicesWereResetNotification, object: session, queue: nil) {
                [weak self] _ in
                guard let self else { return }
                self.log("media services were reset")
                self.delegate?.dispatchAsync {
                    self.sessionActive = false
                    self.update()
                }
            },
        ]
    }
}

extension CallAudioDevice: RTCAudioDevice {
    var deviceInputSampleRate: Double { inputFormat?.sampleRate ?? session.sampleRate }
    var deviceOutputSampleRate: Double { outputFormat?.sampleRate ?? session.sampleRate }
    var inputIOBufferDuration: TimeInterval { session.ioBufferDuration }
    var outputIOBufferDuration: TimeInterval { session.ioBufferDuration }
    var inputNumberOfChannels: Int { Int(inputFormat?.channelCount ?? 1) }
    var outputNumberOfChannels: Int { Int(outputFormat?.channelCount ?? 1) }
    var inputLatency: TimeInterval { session.inputLatency }
    var outputLatency: TimeInterval { session.outputLatency }

    var isInitialized: Bool { delegate != nil && unit != nil }

    func initialize(with delegate: RTCAudioDeviceDelegate) -> Bool {
        guard self.delegate == nil else { return false }
        let description = AudioComponentDescription(
            componentType: kAudioUnitType_Output, componentSubType: kAudioUnitSubType_VoiceProcessingIO,
            componentManufacturer: kAudioUnitManufacturer_Apple, componentFlags: 0, componentFlagsMask: 0)
        let unit: AUAudioUnit
        do { unit = try AUAudioUnit(componentDescription: description) } catch {
            log("could not open voice processing: \(error)")
            return false
        }
        unit.isInputEnabled = false
        unit.isOutputEnabled = false
        unit.maximumFramesToRender = 4096
        self.unit = unit
        self.delegate = delegate
        if observers.isEmpty { observeSession() }
        log("initialized")
        return true
    }

    func terminateDevice() -> Bool {
        observers.forEach(NotificationCenter.default.removeObserver)
        observers = []
        wantsPlayout = false
        wantsRecording = false
        update()
        unit = nil
        inputFormat = nil
        outputFormat = nil
        delegate = nil
        log("terminated")
        return true
    }

    var isPlayoutInitialized: Bool { isInitialized }
    func initializePlayout() -> Bool { isPlayoutInitialized }
    var isPlaying: Bool { wantsPlayout }

    func startPlayout() -> Bool {
        wantsPlayout = true
        update()
        return true
    }

    func stopPlayout() -> Bool {
        wantsPlayout = false
        update()
        return true
    }

    var isRecordingInitialized: Bool { isInitialized }
    func initializeRecording() -> Bool { isRecordingInitialized }
    var isRecording: Bool { wantsRecording }

    func startRecording() -> Bool {
        wantsRecording = true
        update()
        return true
    }

    func stopRecording() -> Bool {
        wantsRecording = false
        update()
        return true
    }
}
