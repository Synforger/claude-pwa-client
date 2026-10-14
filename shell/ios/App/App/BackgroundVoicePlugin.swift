import AVFoundation
import AVKit
import Capacitor
import Foundation
import PipecatClientIOS
import PipecatClientIOSSmallWebrtc
import UIKit

/// マイクと声を、 画面が裏に回っても止めずに持つ plugin (= 画面の 🔊 と 🎙 から呼ぶ)。
///
/// iOS の Web の画面 (= WKWebView) は、 アプリが裏に回るとマイクと音と JavaScript が止まる。 native の音の仕組みは
/// `UIBackgroundModes` (= audio・voip) の下で裏でも動き続けるので、 マイクと声はここで持ち、 backend の電話の口
/// (= `POST /sessions/<sid>/voice/call`) と WebRTC でつなぐ。 声の区間・言い終えの判定・聞き取り・タブへの送信・
/// 返事の声は、 全部 backend の中で回る (= `backend/voice_call/`)。
///
/// 画面から呼ぶ口:
///   start({ url, mic })   電話の口の URL へつなぐ (= mic が false ならマイクを切った状態で始める)
///   setMic({ on })        マイクを入れる / 切る (= 声はそのまま鳴る)
///   stop()                切る
/// 画面へ知らせる event:
///   state { state }       connecting / connected / disconnected / error (= error の時は message も)
@objc(BackgroundVoicePlugin)
public class BackgroundVoicePlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "BackgroundVoicePlugin"
    public let jsName = "BackgroundVoice"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "start", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "setMic", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "stop", returnType: CAPPluginReturnPromise),
    ]

    private var client: PipecatClient?
    private var picture: CallPicture?

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
                call.resolve()
            } catch {
                call.reject("could not switch the microphone: \(error)")
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
                self.picture = picture
            }
        } catch {
            self.client = nil
            notify("error", message: "\(error)")
        }
    }

    @MainActor private func disconnect() async {
        picture?.stop()
        picture = nil
        guard let client else { return }
        self.client = nil
        try? await client.disconnect()
        client.release()
    }

    fileprivate func notify(_ state: String, message: String? = nil) {
        var data: [String: Any] = ["state": state]
        if let message { data["message"] = message }
        CAPLog.print("[BackgroundVoice] \(state)\(message.map { " \($0)" } ?? "")")
        notifyListeners("state", data: data)
    }
}

extension BackgroundVoicePlugin: PipecatClientDelegate {
    public func onConnected() { notify("connected") }
    public func onDisconnected() { notify("disconnected") }
    public func onError(message: RTVIMessageInbound) { notify("error", message: "\(message)") }
}

/// 通話の間、 app を抜けたら PiP の小さな窓に文字を出す (= iOS 15 からの通話の PiP。 カメラは使わない)。
///
/// 試しの段: 窓には固定の文と、 1 秒ごとに進む時刻を出す (= 裏に回っている間も中身が書き換わるかを見る)。
@MainActor final class CallPicture: NSObject, AVPictureInPictureControllerDelegate {
    private var controller: AVPictureInPictureController?
    private let content = AVPictureInPictureVideoCallViewController()
    private let label = UILabel()
    private var timer: Timer?

    func start(over screen: UIView) {
        guard AVPictureInPictureController.isPictureInPictureSupported() else {
            CAPLog.print("[CallPicture] PiP is not supported on this device")
            return
        }
        content.preferredContentSize = CGSize(width: 900, height: 1200)
        content.view.backgroundColor = .black
        label.numberOfLines = 0
        label.textColor = .white
        label.font = .systemFont(ofSize: 44, weight: .medium)
        label.frame = content.view.bounds.insetBy(dx: 40, dy: 40)
        label.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        content.view.addSubview(label)
        tick()
        let source = AVPictureInPictureController.ContentSource(
            activeVideoCallSourceView: screen, contentViewController: content)
        let controller = AVPictureInPictureController(contentSource: source)
        controller.canStartPictureInPictureAutomaticallyFromInline = true
        controller.delegate = self
        self.controller = controller
        timer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.tick() }
        }
        CAPLog.print("[CallPicture] ready (starts when the app goes to the background)")
    }

    func stop() {
        timer?.invalidate()
        timer = nil
        controller?.stopPictureInPicture()
        controller = nil
    }

    private func tick() {
        let time = DateFormatter.localizedString(from: Date(), dateStyle: .none, timeStyle: .medium)
        label.text = "PiP の試し\n\(time)"
    }

    nonisolated func pictureInPictureControllerDidStartPictureInPicture(_ controller: AVPictureInPictureController) {
        CAPLog.print("[CallPicture] started")
    }

    nonisolated func pictureInPictureController(
        _ controller: AVPictureInPictureController, failedToStartPictureInPictureWithError error: Error
    ) {
        CAPLog.print("[CallPicture] failed to start: \(error)")
    }
}
