import AVFoundation
import Capacitor
import WebRTC

/// マイクを切った通話の音の部品: 返事の声を流すだけで、 マイクを一度も開かない。
///
/// WebRTC が既定で使う iPhone の音の部品は、 声を流すだけの時もマイクを回す (= 通話の音声処理は、 流す音と録る音を
/// 一緒に扱う)。 すると iOS はマイクを使う通話と見なし、 画面の隅にオレンジの光を点け、 他の app の音を下げ、 音量
/// ボタンを通話の音量にする。 この部品は音の設定を「再生だけ」 (= `.playback`、 他の app の音と混ぜる) にして、
/// WebRTC が渡す声を AVAudioEngine で鳴らす。 録音を頼まれても始めない (= マイクを入れる時は、 通話を既定の部品で
/// 掛け直す。 `BackgroundVoicePlugin`)。
///
/// WebRTC はこの部品の操作を、 自分の 1 本の thread からだけ呼ぶ (= `RTCAudioDevice` の約束)。 声を求める
/// `getPlayoutData` は、 AVAudioEngine の再生の thread から呼ぶ。
final class ListenOnlyAudioDevice: NSObject, RTCAudioDevice {
    static let shared = ListenOnlyAudioDevice()

    /// WebRTC から受け取る声の形 (= 16 bit の整数、 1 チャンネル)。 機器の速さは音の設定が決める
    private static let channels: AVAudioChannelCount = 1
    /// 1 回に求められる長さの上限 (= 速さ 48000 で 85 ms。 iPhone の 1 回は数 ms〜数十 ms)
    private static let maxFrames = 4096
    /// WebRTC の声を受ける皿 (= 再生の thread で毎回作らない)
    private let scratch = UnsafeMutablePointer<Int16>.allocate(capacity: maxFrames)

    private var delegate: RTCAudioDeviceDelegate?
    private var engine: AVAudioEngine?
    private var source: AVAudioSourceNode?
    private var observers: [NSObjectProtocol] = []
    private(set) var isPlayoutInitialized = false
    private(set) var isPlaying = false

    // MARK: 機器の値 (= 録音はしないので、 入力の値は出力と同じ形を名乗るだけ)

    var deviceInputSampleRate: Double { deviceOutputSampleRate }
    var inputIOBufferDuration: TimeInterval { outputIOBufferDuration }
    var inputNumberOfChannels: Int { Int(Self.channels) }
    var inputLatency: TimeInterval { 0 }
    var deviceOutputSampleRate: Double { AVAudioSession.sharedInstance().sampleRate }
    var outputIOBufferDuration: TimeInterval { AVAudioSession.sharedInstance().ioBufferDuration }
    var outputNumberOfChannels: Int { Int(Self.channels) }
    var outputLatency: TimeInterval { AVAudioSession.sharedInstance().outputLatency }

    var isInitialized: Bool { delegate != nil }

    func initialize(with delegate: RTCAudioDeviceDelegate) -> Bool {
        self.delegate = delegate
        return true
    }

    func terminateDevice() -> Bool {
        _ = stopPlayout()
        teardown()
        delegate = nil
        return true
    }

    // MARK: 再生

    func initializePlayout() -> Bool {
        guard let delegate else { return false }
        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(.playback, mode: .spokenAudio, options: [.mixWithOthers])
            try session.setActive(true)
        } catch {
            CAPLog.print("[ListenOnlyAudio] \(stamp()) could not set the playback session: \(error)")
            return false
        }
        teardown()
        let rate = session.sampleRate
        guard let format = AVAudioFormat(standardFormatWithSampleRate: rate, channels: Self.channels) else { return false }
        let getPlayoutData = delegate.getPlayoutData
        let scratch = scratch
        let source = AVAudioSourceNode(format: format) { _, timestamp, frameCount, outputData in
            // WebRTC は 16 bit の整数で渡す。 受け皿に受けてから、 engine の形 (= 小数) に直す
            let frames = min(Int(frameCount), Self.maxFrames)
            var flags = AudioUnitRenderActionFlags()
            var pcm = AudioBufferList(mNumberBuffers: 1, mBuffers: AudioBuffer(
                mNumberChannels: UInt32(Self.channels), mDataByteSize: UInt32(frames * MemoryLayout<Int16>.size),
                mData: UnsafeMutableRawPointer(scratch)))
            let status = getPlayoutData(&flags, timestamp, 0, UInt32(frames), &pcm)
            let out = UnsafeMutableAudioBufferListPointer(outputData)
            guard let floats = out.first?.mData?.assumingMemoryBound(to: Float.self) else { return status }
            for i in 0..<Int(frameCount) {
                floats[i] = status == noErr && i < frames ? Float(scratch[i]) / 32768 : 0
            }
            return noErr
        }
        let engine = AVAudioEngine()
        engine.attach(source)
        engine.connect(source, to: engine.mainMixerNode, format: format)
        engine.prepare()
        self.engine = engine
        self.source = source
        watchSession()
        delegate.dispatchSync { delegate.notifyAudioOutputParametersChange() }
        isPlayoutInitialized = true
        CAPLog.print("[ListenOnlyAudio] \(stamp()) playout ready: rate=\(Int(rate)) category=\(session.category.rawValue)")
        return true
    }

    func startPlayout() -> Bool {
        guard let engine else { return false }
        do {
            try engine.start()
        } catch {
            CAPLog.print("[ListenOnlyAudio] \(stamp()) could not start: \(error)")
            return false
        }
        isPlaying = true
        return true
    }

    func stopPlayout() -> Bool {
        engine?.stop()
        isPlaying = false
        return true
    }

    // MARK: 録音 (= しない。 WebRTC が頼んでも断る)

    var isRecordingInitialized: Bool { false }
    var isRecording: Bool { false }
    func initializeRecording() -> Bool { false }
    func startRecording() -> Bool { false }
    func stopRecording() -> Bool { true }

    // MARK: 中断と経路

    /// 電話や他の app で音が止められた後と、 イヤホンの抜き差しの後に、 鳴らし直す (= 速さが変わったら WebRTC に知らせる)
    private func watchSession() {
        let center = NotificationCenter.default
        let session = AVAudioSession.sharedInstance()
        observers.append(center.addObserver(forName: AVAudioSession.interruptionNotification, object: session,
                                            queue: nil) { [weak self] note in
            let raw = note.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt
            guard raw.flatMap(AVAudioSession.InterruptionType.init) == .ended else { return }
            self?.restart(because: "interruption ended")
        })
        observers.append(center.addObserver(forName: AVAudioSession.routeChangeNotification, object: session,
                                            queue: nil) { [weak self] _ in
            self?.restart(because: "route changed")
        })
    }

    private func restart(because reason: String) {
        guard let delegate else { return }
        delegate.dispatchAsync { [weak self] in
            guard let self, self.isPlaying, let engine = self.engine else { return }
            delegate.notifyAudioOutputParametersChange()
            if !engine.isRunning {
                try? AVAudioSession.sharedInstance().setActive(true)
                try? engine.start()
            }
            CAPLog.print("[ListenOnlyAudio] \(stamp()) \(reason): running=\(engine.isRunning)")
        }
    }

    private func teardown() {
        observers.forEach(NotificationCenter.default.removeObserver)
        observers = []
        engine?.stop()
        if let source { engine?.detach(source) }
        engine = nil
        source = nil
        isPlayoutInitialized = false
    }
}
