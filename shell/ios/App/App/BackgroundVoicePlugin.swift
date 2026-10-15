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
/// 画面から呼ぶ口:
///   start({ url, mic })   電話の口の URL へつなぐ (= mic が false ならマイクを切った状態で始める)
///   setMic({ on })        マイクを入れる / 切る (= 声はそのまま鳴る)
///   setSpeech({ on })     返事を声にする / しない (= backend の会話へ知らせる。 マイクと小窓はそのまま)
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
        CAPPluginMethod(name: "showPicture", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "stop", returnType: CAPPluginReturnPromise),
    ]

    private var client: PipecatClient? {
        didSet { Self.inCall = client != nil }
    }
    /// 声の会話がつながっている (= 端末の操作のうちマイクやスピーカーを使う物は、 その間は断る。
    /// 通話の途中で音の設定を変えると、 その通話の残りはエコー消しが切れる)
    static private(set) var inCall = false
    private var picture: CallPicture?
    private var audioWatch: AudioSessionWatch?
    /// つながって相手の準備ができる前に頼まれた、 返事の声の入 / 切 (= 準備ができた所で送る)
    private var pendingSpeech: Bool?

    @objc func start(_ call: CAPPluginCall) {
        guard let raw = call.getString("url"), let url = URL(string: raw) else {
            call.reject("url is required")
            return
        }
        let mic = call.getBool("mic") ?? true
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
            guard let client = self.client else {
                call.resolve()
                return
            }
            do {
                try await client.enableMic(enable: on)
                self.picture?.setMic(on)
                call.resolve()
            } catch {
                call.reject("could not switch the microphone: \(error)")
            }
        }
    }

    @objc func setSpeech(_ call: CAPPluginCall) {
        let on = call.getBool("on") ?? true
        Task { @MainActor in
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

    @MainActor private func connect(_ url: URL, mic: Bool) async {
        await disconnect()
        #if DEBUG
        // 試しの build だけ: WebRTC 自身の log (= 音の部品の作り直しや経路の変化) も出す
        RTCSetMinDebugLogLevel(.info)
        #endif
        useOneAudioSession()
        audioWatch = AudioSessionWatch()
        let client = PipecatClient(
            options: PipecatClientOptions(transport: SmallWebRTCTransport(iceConfig: nil), enableMic: mic))
        client.delegate = self
        self.client = client
        notify("connecting")
        do {
            try await client.connect(
                transportParams: SmallWebRTCTransportConnectionParams(webrtcRequestParams: APIRequest(endpoint: url)))
            if let screen = bridge?.webView {
                let picture = CallPicture()
                picture.start(over: screen)
                picture.setMic(mic)
                picture.onMic = { [weak self] on in self?.switchMicFromPicture(on) }
                self.picture = picture
            }
        } catch {
            self.client = nil
            notify("error", message: "\(error)")
        }
    }

    @MainActor private func sendSpeech(_ on: Bool) throws {
        try client?.sendClientMessage(msgType: "voice-speech", data: .object(["on": .boolean(on)]))
    }

    /// 小窓の再生 / 停止: マイクを切り替え、 画面の 🎙 に知らせる。
    @MainActor private func switchMicFromPicture(_ on: Bool) {
        guard let client else { return }
        Task { @MainActor in
            do {
                try await client.enableMic(enable: on)
                CAPLog.print("[BackgroundVoice] \(stamp()) microphone \(on ? "on" : "off") from the picture")
                notifyListeners("mic", data: ["on": on])
            } catch {
                CAPLog.print("[BackgroundVoice] could not switch the microphone from the picture: \(error)")
                self.picture?.setMic(!on)
            }
        }
    }

    @MainActor private func disconnect() async {
        picture?.stop()
        picture = nil
        audioWatch = nil
        pendingSpeech = nil
        guard let client else { return }
        self.client = nil
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
    public func onDisconnected() { notify("disconnected") }
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
