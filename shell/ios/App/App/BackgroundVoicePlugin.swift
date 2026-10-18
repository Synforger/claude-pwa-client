import AVFoundation
import Capacitor
import Foundation
import PipecatClientIOS
import PipecatClientIOSSmallWebrtc
import UIKit
import WebRTC

/// マイクと声を、 画面が裏に回っても止めずに持つ plugin (= 画面の 🔊 と 🎙 から呼ぶ)。
///
/// iOS の Web の画面 (= WKWebView) は、 アプリが裏に回るとマイクと音と JavaScript が止まる。 native の音の仕組みは
/// `UIBackgroundModes` (= audio・voip) の下で裏でも動き続けるので、 マイクと声はここで持ち、 backend の電話の口
/// (= `POST /sessions/<sid>/voice/call`) と WebRTC でつなぐ。 声の区間・言い終えの判定・聞き取り・タブへの送信・
/// 返事の声は、 全部 backend の中で回る (= `backend/voice_call/`)。
///
/// 音の設定: iPhone のエコー消し (= Voice-Processing I/O) は、 通話の途中で音の設定 (= category / mode) が変わると
/// 作り直され、 それまでに覚えた消し方を失う。 この通話では Pipecat の部品 (= SmallWebRTC の AudioManager) と
/// WebRTC が別々に音の設定を持ち、 Pipecat は経路が変わるたびに自分の設定を、 WebRTC は音の部品を作る時に自分の
/// 設定を掛けていた。 WebRTC の設定を Pipecat が掛ける物と同じにして、 どちらが掛けても何も変わらないようにする
/// (= 掛ける前に今の値と比べ、 同じなら掛けない作りは WebRTC の側にある)。
///
/// マイクを切った通話: 声を流すだけの部品 (= `ListenOnlyAudioDevice`) でつなぎ、 マイクを一度も開かない。 既定の
/// 部品は声を流すだけでもマイクを回すので、 iOS がオレンジの光を点け、 他の音を下げ、 音量ボタンを通話の音量にして
/// いた。 マイクの入 / 切は通話の部品を替えるので、 その度に同じタブへ掛け直す (= 1〜2 秒途切れる。 小窓は閉じない)。
///
/// 画面から呼ぶ口:
///   start({ url, mic })   電話の口の URL へつなぐ (= mic が false ならマイクを切った状態で始める)
///   setMic({ on })        マイクを入れる / 切る (= 通話を掛け直す。 下の「マイクを切った通話」)
///   setSpeech({ on })     返事を声にする / しない (= backend の会話へ知らせる。 マイクと小窓はそのまま)
///   setVolume({ volume }) 声の大きさの倍率を覚える (= 通話を掛け直す時に使う。 鳴っている声へは backend が掛ける)
///   showPicture()         小窓を今出す (= 自動で出なかった時。 出せなければ reject)
///   stop()                切る
/// 画面へ知らせる event:
///   state { state }       connecting / connected / disconnected / error (= error の時は message も)
///   mic { on }            小窓の再生 / 停止でマイクを入れた / 切った (= 画面の 🎙 を合わせる)
@objc(BackgroundVoicePlugin)
public class BackgroundVoicePlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "BackgroundVoicePlugin"
    public let jsName = "BackgroundVoice"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "start", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "setMic", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "setSpeech", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "setVolume", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "showPicture", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "stop", returnType: CAPPluginReturnPromise),
    ]

    private var client: PipecatClient?
    /// 今の通話を持つ plugin (= 端末の操作が、 マイクやスピーカーを使う間だけ通話を外す。 `withCallPaused`)
    @MainActor private static weak var current: BackgroundVoicePlugin?
    /// 掛け直す時の値 (= 始めた時の URL に、 その後に変わったマイク・返事の声の入 / 切・声の大きさを重ねる)。
    /// 通話を切ると URL を忘れる (= 外している間に切られたら、 掛け直さない)
    private var callURL: URL?
    private var micOn = true
    private var speechOn = true
    private var volume: Double?
    /// 端末の操作のために通話を外している間 (= 切れたことを画面へ知らせない。 知らせると画面が会話を閉じる)
    private var pausing = false
    private var picture: CallPicture?
    private var audioWatch: AudioSessionWatch?
    /// つながって相手の準備ができる前に頼まれた、 返事の声の入 / 切 (= 準備ができた所で送る)
    private var pendingSpeech: Bool?
    /// 今の通話をマイクありでつないだか (= 通話していなければ nil)
    private var connectedMic: Bool?
    /// マイクの入 / 切で掛け直している間
    private var redialing = false

    @objc func start(_ call: CAPPluginCall) {
        guard let raw = call.getString("url"), let url = URL(string: raw) else {
            call.reject("url is required")
            return
        }
        let mic = call.getBool("mic") ?? true
        let query = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
        callURL = url
        micOn = mic
        speechOn = query.first { $0.name == "speech" }?.value != "0"
        volume = query.first { $0.name == "volume" }?.value.flatMap(Double.init)
        requestMicrophone { [weak self] granted in
            guard let self else { return }
            guard granted else {
                self.notify("error", message: "microphone denied")
                call.reject("microphone denied")
                return
            }
            Task { @MainActor in
                await self.connect(url, mic: mic)
                call.resolve()
            }
        }
    }

    @objc func setMic(_ call: CAPPluginCall) {
        let on = call.getBool("on") ?? true
        Task { @MainActor in
            await self.switchMic(on)
            call.resolve()
        }
    }

    /// マイクを入れる / 切る: 通話の部品を替えて、 同じタブへ掛け直す (= 小窓はそのまま。 通話していなければ覚えるだけ)。
    /// 掛け直しは 1 本ずつ (= 掛け直す間に また切り替えられたら、 終わった後に今のマイクと比べて、 もう 1 度)。
    @MainActor private func switchMic(_ on: Bool) async {
        guard on != micOn else { return }
        micOn = on
        picture?.setMic(on)
        guard client != nil, !redialing else { return }
        redialing = true
        defer { redialing = false }
        while client != nil, let connected = connectedMic, connected != micOn {
            CAPLog.print("[BackgroundVoice] \(stamp()) microphone \(micOn ? "on" : "off"): the call is redialed")
            await redial(keepPicture: true)
        }
    }

    @objc func setSpeech(_ call: CAPPluginCall) {
        let on = call.getBool("on") ?? true
        Task { @MainActor in
            self.speechOn = on
            guard let client = self.client else {
                call.resolve()
                return
            }
            // 準備ができる前の知らせは Pipecat が断る (= BotNotReadyError。 🎙 で始めて、 つながる前に 🔊 を押した時)
            if client.state != .ready {
                self.pendingSpeech = on
                CAPLog.print("[BackgroundVoice] \(stamp()) voice \(on ? "on" : "off") is sent once the call is ready")
                call.resolve()
                return
            }
            do {
                try self.sendSpeech(on)
                call.resolve()
            } catch {
                call.reject("could not switch the voice: \(error)")
            }
        }
    }

    @objc func setVolume(_ call: CAPPluginCall) {
        let volume = call.getDouble("volume")
        Task { @MainActor in
            if let volume { self.volume = volume }
            call.resolve()
        }
    }

    @objc func showPicture(_ call: CAPPluginCall) {
        Task { @MainActor in
            if self.picture?.show() == true {
                call.resolve()
            } else {
                call.reject("picture in picture is not possible now")
            }
        }
    }

    @objc func stop(_ call: CAPPluginCall) {
        Task { @MainActor in
            self.callURL = nil
            self.pausing = false
            await self.disconnect()
            call.resolve()
        }
    }

    private func requestMicrophone(_ done: @escaping (Bool) -> Void) {
        if #available(iOS 17.0, *) {
            AVAudioApplication.requestRecordPermission { granted in DispatchQueue.main.async { done(granted) } }
        } else {
            AVAudioSession.sharedInstance().requestRecordPermission { granted in
                DispatchQueue.main.async { done(granted) }
            }
        }
    }

    /// つなぐ。 マイクを切っているなら、 声を流すだけの部品でつなぐ (= マイクを開かない)。 keepPicture なら、 出ている
    /// 小窓をそのまま使う (= 裏に回っている間は、 閉じた小窓を出し直せない)。
    @MainActor private func connect(_ url: URL, mic: Bool, keepPicture: Bool = false) async {
        await disconnect(keepPicture: keepPicture)
        Self.current = self
        #if DEBUG
        // 試しの build だけ: WebRTC 自身の log (= 音の部品の作り直しや経路の変化) も出す
        RTCSetMinDebugLogLevel(.info)
        #endif
        if mic { useOneAudioSession() }
        audioWatch = AudioSessionWatch()
        let transport = SmallWebRTCTransport(iceConfig: nil, audioDevice: mic ? nil : ListenOnlyAudioDevice.shared)
        let client = PipecatClient(options: PipecatClientOptions(transport: transport, enableMic: mic))
        client.delegate = self
        self.client = client
        connectedMic = mic
        notify("connecting")
        do {
            try await client.connect(
                transportParams: SmallWebRTCTransportConnectionParams(webrtcRequestParams: APIRequest(endpoint: url)))
            if let picture {
                picture.setMic(mic)
            } else if let screen = bridge?.webView {
                let picture = CallPicture()
                picture.start(over: screen)
                picture.setMic(mic)
                picture.onMic = { [weak self] on in self?.switchMicFromPicture(on) }
                picture.onStop = { [weak self] in self?.stopFromPicture() }
                self.picture = picture
            }
        } catch {
            self.client = nil
            notify("error", message: "\(error)")
        }
    }

    /// 通話中に、 マイクかスピーカーを使う端末の操作を頼まれた: 通話を一旦外して操作し、 終わったら同じタブへ掛け直す。
    ///
    /// 通話の途中で音の設定を変えると、 その通話の残りはエコー消しが切れる (= iPhone の音声処理が作り直される)。
    /// 音の設定は通話の外で変え、 掛け直した通話は音の部品を作り直すので、 エコー消しも初めから効く。 body は、 自分で
    /// 変えた音の設定を戻し終えてから返す (= 掛け直した後に戻すと、 掛け直した通話の音を止める)。 通話していなければ、
    /// そのまま body を動かす。
    @MainActor static func withCallPaused<T>(_ body: @MainActor () async throws -> T) async throws -> T {
        guard let plugin = current, plugin.client != nil, plugin.callURL != nil else { return try await body() }
        plugin.pausing = true
        CAPLog.print("[BackgroundVoice] \(stamp()) the call is paused for a device operation")
        await plugin.disconnect()
        do {
            let result = try await body()
            await plugin.resume()
            return result
        } catch {
            await plugin.resume()
            throw error
        }
    }

    /// 外した通話を、 外した時のマイク・返事の声の入 / 切・声の大きさで掛け直す (= 外している間に切られていたら、 しない)。
    @MainActor private func resume() async {
        defer { pausing = false }
        guard let url = redialURL() else { return }
        CAPLog.print("[BackgroundVoice] \(stamp()) the call is resumed after a device operation")
        await connect(url, mic: micOn)
    }

    /// 今の通話を切って、 今のマイク・返事の声の入 / 切・声の大きさで掛け直す。 裏に回っていても掛け直し終えるまで
    /// iOS に止めさせない (= 切った瞬間に音が止まり、 app が眠らされる)。
    @MainActor private func redial(keepPicture: Bool) async {
        guard let url = redialURL() else { return }
        pausing = true
        let hold = UIApplication.shared.beginBackgroundTask(withName: "redial the call")
        defer {
            pausing = false
            if hold != .invalid { UIApplication.shared.endBackgroundTask(hold) }
        }
        await disconnect(keepPicture: keepPicture)
        await connect(url, mic: micOn, keepPicture: keepPicture)
    }

    /// 掛け直す先 (= 始めた時の URL に、 その後に変わった返事の声の入 / 切と声の大きさを重ねる)。 つなぎ直しの印
    /// (= resume) を付けるので、 backend は切れた通話で鳴り終えていなかった文から言い直す。
    private func redialURL() -> URL? {
        guard let callURL, var parts = URLComponents(url: callURL, resolvingAgainstBaseURL: false) else { return nil }
        var query = (parts.queryItems ?? []).filter { !["volume", "speech", "resume"].contains($0.name) }
        if let volume { query.append(URLQueryItem(name: "volume", value: String(volume))) }
        if !speechOn { query.append(URLQueryItem(name: "speech", value: "0")) }
        query.append(URLQueryItem(name: "resume", value: "1"))
        parts.queryItems = query
        return parts.url
    }

    @MainActor private func sendSpeech(_ on: Bool) throws {
        try client?.sendClientMessage(msgType: "voice-speech", data: .object(["on": .boolean(on)]))
    }

    /// 小窓の停止 (= agent が考えている / 話している間): 声と turn を止めるよう backend の会話へ知らせる。
    @MainActor private func stopFromPicture() {
        CAPLog.print("[BackgroundVoice] \(stamp()) stop from the picture")
        do {
            try client?.sendClientMessage(msgType: "voice-stop")
        } catch {
            CAPLog.print("[BackgroundVoice] \(stamp()) could not send the stop: \(error)")
        }
    }

    /// 小窓の再生 / 停止: マイクを切り替え、 画面の 🎙 に知らせる。
    @MainActor private func switchMicFromPicture(_ on: Bool) {
        guard client != nil else { return }
        Task { @MainActor in
            CAPLog.print("[BackgroundVoice] \(stamp()) microphone \(on ? "on" : "off") from the picture")
            notifyListeners("mic", data: ["on": on])
            await self.switchMic(on)   // (= 画面が 🎙 で呼び返しても、 その前にここでマイクの値が変わっている)
        }
    }

    /// 切る。 keepPicture なら小窓を残し、 切れた知らせも受けない (= 掛け直す間。 古い通話の知らせが、 掛け直した
    /// 後に届いて画面が会話を閉じないように)。
    @MainActor private func disconnect(keepPicture: Bool = false) async {
        if !keepPicture {
            picture?.stop()
            picture = nil
        }
        audioWatch = nil
        pendingSpeech = nil
        connectedMic = nil
        guard let client else { return }
        self.client = nil
        if keepPicture { client.delegate = nil }
        try? await client.disconnect()
        client.release()
    }

    fileprivate func notify(_ state: String, message: String? = nil) {
        var data: [String: Any] = ["state": state]
        if let message { data["message"] = message }
        CAPLog.print("[BackgroundVoice] \(stamp()) \(state)\(message.map { " \($0)" } ?? "")")
        if state == "connected" { audioWatch?.report("connected") }
        notifyListeners("state", data: data)
    }
}

extension BackgroundVoicePlugin: PipecatClientDelegate {
    public func onConnected() { notify("connected") }

    public func onBotReady(botReadyData: BotReadyData) {
        Task { @MainActor in
            guard let on = self.pendingSpeech else { return }
            self.pendingSpeech = nil
            do {
                try self.sendSpeech(on)
                CAPLog.print("[BackgroundVoice] \(stamp()) voice \(on ? "on" : "off") sent now that the call is ready")
            } catch {
                self.notify("error", message: "could not switch the voice: \(error)")
            }
        }
    }
    public func onDisconnected() {
        Task { @MainActor in
            if !self.pausing { self.notify("disconnected") }
        }
    }
    public func onError(message: RTVIMessageInbound) { notify("error", message: "\(message)") }

    /// backend の会話が送る小窓の会話と状態 (= `CallPicture`)。
    public func onServerMessage(data: Any) {
        guard let message = data as? Value else { return }
        Task { @MainActor in self.picture?.receive(message) }
    }
}

/// log の時刻 (= backend の通話の log と突き合わせる。 時:分:秒.ミリ秒)
func stamp() -> String {
    let format = DateFormatter()
    format.dateFormat = "HH:mm:ss.SSS"
    return format.string(from: Date())
}

/// 通話の間、 iPhone の音の設定が変わった時を log に出す (= 経路の変化・中断・音の仕組みの作り直し)。
///
/// iPhone のエコー消しは流れた音から消し方を覚えるので、 音の部品が作り直されると覚えた物を失う。 返事の声がマイクに
/// 入った時に、 その前に何が起きていたかを backend の log の時刻と並べて読むための物。
final class AudioSessionWatch {
    private var observers: [NSObjectProtocol] = []

    init() {
        let center = NotificationCenter.default
        let session = AVAudioSession.sharedInstance()
        observers.append(center.addObserver(forName: AVAudioSession.routeChangeNotification, object: session,
                                            queue: .main) { [weak self] note in
            let raw = note.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt
            let reason = raw.flatMap(AVAudioSession.RouteChangeReason.init).map(Self.name) ?? "\(raw ?? 0)"
            self?.report("route changed (\(reason))")
        })
        observers.append(center.addObserver(forName: AVAudioSession.interruptionNotification, object: session,
                                            queue: .main) { [weak self] note in
            let raw = note.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt
            let kind = raw.flatMap(AVAudioSession.InterruptionType.init) == .began ? "began" : "ended"
            self?.report("interruption \(kind)")
        })
        observers.append(center.addObserver(forName: AVAudioSession.mediaServicesWereResetNotification,
                                            object: session, queue: .main) { [weak self] _ in
            self?.report("media services were reset")
        })
    }

    deinit {
        observers.forEach(NotificationCenter.default.removeObserver)
    }

    /// 今の音の設定を 1 行で (= 何が起きたかと一緒に)。
    func report(_ what: String) {
        let session = AVAudioSession.sharedInstance()
        let route = session.currentRoute
        let outputs = route.outputs.map { $0.portType.rawValue }.joined(separator: "+")
        let inputs = route.inputs.map { $0.portType.rawValue }.joined(separator: "+")
        CAPLog.print("[AudioSession] \(stamp()) \(what): category=\(session.category.rawValue) " +
                     "mode=\(session.mode.rawValue) out=\(outputs) in=\(inputs) rate=\(Int(session.sampleRate)) " +
                     "io=\(String(format: "%.3f", session.ioBufferDuration)) " +
                     "options=\(session.categoryOptions.rawValue)")
    }

    private static func name(_ reason: AVAudioSession.RouteChangeReason) -> String {
        switch reason {
        case .newDeviceAvailable: return "new device"
        case .oldDeviceUnavailable: return "old device gone"
        case .categoryChange: return "category change"
        case .override: return "override"
        case .wakeFromSleep: return "wake from sleep"
        case .noSuitableRouteForCategory: return "no route for category"
        case .routeConfigurationChange: return "route configuration change"
        case .unknown: return "unknown"
        @unknown default: return "reason \(reason.rawValue)"
        }
    }
}

/// WebRTC が掛ける音の設定を、 Pipecat の部品が掛ける物にそろえる (= 機器の指定が無い時の、 スピーカーで話す形)。
/// Pipecat の値は `pipecat-client-ios-small-webrtc` の `AudioManager.applyConfiguration()`: playAndRecord /
/// videoChat / allowBluetooth (= 今の名前は allowBluetoothHFP。 値は同じ) + mixWithOthers (= 他の app の音と一緒に鳴らせる)。
func useOneAudioSession() {
    let config = RTCAudioSessionConfiguration.webRTC()
    config.category = AVAudioSession.Category.playAndRecord.rawValue
    config.mode = AVAudioSession.Mode.videoChat.rawValue
    config.categoryOptions = [.allowBluetoothHFP, .mixWithOthers]
    RTCAudioSessionConfiguration.setWebRTC(config)
}
