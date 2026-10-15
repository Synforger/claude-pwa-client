import AVFoundation
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
            do {
                try self.client?.sendClientMessage(msgType: "voice-speech", data: .object(["on": .boolean(on)]))
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

    /// 小窓の再生 / 停止: マイクを切り替え、 画面の 🎙 に知らせる。
    @MainActor private func switchMicFromPicture(_ on: Bool) {
        guard let client else { return }
        Task { @MainActor in
            do {
                try await client.enableMic(enable: on)
                CAPLog.print("[BackgroundVoice] microphone \(on ? "on" : "off") from the picture")
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

    /// backend の会話が送る小窓の会話と状態 (= `CallPicture`)。
    public func onServerMessage(data: Any) {
        guard let message = data as? Value else { return }
        Task { @MainActor in self.picture?.receive(message) }
    }
}
