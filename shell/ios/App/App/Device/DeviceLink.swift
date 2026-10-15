import Capacitor
import Foundation
import UIKit

/// この Mac の agent の手 (= backend の `/device/ws` と、 そこから来た頼みを動かす操作の一覧)。
///
/// app が起きている間 (= 前に出ているか、 通話で裏でも動いている間) backend につなぎ、 最初に操作の一覧を送る
/// (= hello)。 頼み `{"type": "call", "id", "op", "args"}` が来たら名前で操作を探して動かし、
/// `{"type": "result", "id", "ok", "result" | "error", "files"}` を返す。 対になる backend の中身は
/// `backend/device/hub.py`、 Mac で打つ命令は `cpc device`。
final class DeviceLink: NSObject {
    static let shared = DeviceLink()

    /// 切れた後につなぎ直すまでの間 (= 失敗が続くほど延ばす)
    private static let retrySeconds: [Double] = [1, 3, 10, 30]
    /// 生きているかを確かめる間隔 (= backend の WebSocket の決まりと同じ)
    private static let pingSeconds: Double = 25

    private var url: URL?
    private var task: URLSessionWebSocketTask?
    private var failures = 0
    private var pinger: Timer?
    private lazy var session = URLSession(configuration: .default, delegate: nil, delegateQueue: .main)
    private let operations: [String: DeviceOperation] = Dictionary(
        uniqueKeysWithValues: DeviceCatalog.all.map { ($0.spec.name, $0) })

    /// app の起動時に呼ぶ (= 画面と同じ backend へつなぐ)。
    func start() {
        guard url == nil, let server = Self.serverURL() else { return }
        var parts = URLComponents(url: server, resolvingAgainstBaseURL: false)
        parts?.scheme = server.scheme == "https" ? "wss" : "ws"
        parts?.path = "/device/ws"
        url = parts?.url
        NotificationCenter.default.addObserver(self, selector: #selector(becameActive),
                                               name: UIApplication.didBecomeActiveNotification, object: nil)
        connect()
    }

    @objc private func becameActive() {
        // iOS が止めていた間に切れていたら、 すぐつなぎ直す
        if task == nil || task?.state != .running { failures = 0; connect() }
    }

    private func connect() {
        guard let url else { return }
        task?.cancel(with: .goingAway, reason: nil)
        let task = session.webSocketTask(with: url)
        self.task = task
        task.resume()
        send(["type": "hello", "device": UIDevice.current.name, "app": Self.appVersion(),
              "catalog": operations.values.map { $0.spec.json }.sorted { "\($0["name"]!)" < "\($1["name"]!)" }])
        receive(on: task)
        pinger?.invalidate()
        pinger = Timer.scheduledTimer(withTimeInterval: Self.pingSeconds, repeats: true) { [weak self] _ in
            self?.task?.sendPing { _ in }
        }
        CAPLog.print("[Device] \(stamp()) connecting to \(url.absoluteString)")
    }

    private func receive(on task: URLSessionWebSocketTask) {
        task.receive { [weak self] outcome in
            guard let self, task === self.task else { return }
            switch outcome {
            case .success(let message):
                self.failures = 0
                if case .string(let text) = message { self.handle(text) }
                self.receive(on: task)
            case .failure(let error):
                CAPLog.print("[Device] \(stamp()) disconnected: \(error.localizedDescription)")
                self.retry()
            }
        }
    }

    private func retry() {
        task = nil
        pinger?.invalidate()
        let wait = Self.retrySeconds[min(failures, Self.retrySeconds.count - 1)]
        failures += 1
        DispatchQueue.main.asyncAfter(deadline: .now() + wait) { [weak self] in
            guard let self, self.task == nil else { return }
            self.connect()
        }
    }

    private func handle(_ text: String) {
        guard let data = text.data(using: .utf8),
              let message = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              message["type"] as? String == "call", let id = message["id"] as? String,
              let name = message["op"] as? String else { return }
        let args = message["args"] as? [String: Any] ?? [:]
        CAPLog.print("[Device] \(stamp()) \(name) asked")
        Task { @MainActor in
            guard let operation = self.operations[name] else {
                self.send(["type": "result", "id": id, "ok": false, "error": "unknown operation \(name)"])
                return
            }
            do {
                let output = try await operation.run(DeviceArgs(args))
                var reply: [String: Any] = ["type": "result", "id": id, "ok": true, "result": output.value]
                if !output.files.isEmpty {
                    reply["files"] = output.files.map {
                        ["name": $0.name, "mime": $0.mime, "data": $0.data.base64EncodedString()]
                    }
                }
                self.send(reply)
                CAPLog.print("[Device] \(stamp()) \(name) answered")
            } catch {
                self.send(["type": "result", "id": id, "ok": false, "error": "\(error.localizedDescription)"])
                CAPLog.print("[Device] \(stamp()) \(name) failed: \(error.localizedDescription)")
            }
        }
    }

    private func send(_ message: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: message),
              let text = String(data: data, encoding: .utf8) else { return }
        task?.send(.string(text)) { _ in }
    }

    /// 画面を読み込む backend の URL (= `npx cap sync` が capacitor.config.json の server.url に書く)。
    private static func serverURL() -> URL? {
        guard let file = Bundle.main.url(forResource: "capacitor.config", withExtension: "json"),
              let data = try? Data(contentsOf: file),
              let config = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let server = config["server"] as? [String: Any], let raw = server["url"] as? String else { return nil }
        return URL(string: raw)
    }

    private static func appVersion() -> String {
        let info = Bundle.main.infoDictionary ?? [:]
        return "\(info["CFBundleShortVersionString"] ?? "?") (\(info["CFBundleVersion"] ?? "?"))"
    }
}

// MARK: - 操作の形

/// 操作の種類 (= read: 読む / add: 足す / change: 変える / delete: 消す / act: 何かを起こす)。
enum DeviceKind: String { case read, add, change, delete, act }

/// 引数 1 つの説明 (= `cpc device <種類>` が出す)。
struct DeviceParam {
    enum Kind: String { case string, int, number, bool, json }
    let name: String
    let kind: Kind
    let required: Bool
    let description: String

    static func string(_ name: String, _ description: String, required: Bool = false) -> DeviceParam {
        DeviceParam(name: name, kind: .string, required: required, description: description)
    }
    static func int(_ name: String, _ description: String, required: Bool = false) -> DeviceParam {
        DeviceParam(name: name, kind: .int, required: required, description: description)
    }
    static func number(_ name: String, _ description: String, required: Bool = false) -> DeviceParam {
        DeviceParam(name: name, kind: .number, required: required, description: description)
    }
    static func bool(_ name: String, _ description: String, required: Bool = false) -> DeviceParam {
        DeviceParam(name: name, kind: .bool, required: required, description: description)
    }
}

/// 操作 1 つの説明 (= backend へ送る一覧の 1 行)。
struct DeviceSpec {
    let name: String
    let kind: DeviceKind
    let summary: String
    var params: [DeviceParam] = []
    /// 答えを待つ長さ (= 人が操作する物は長く)
    var timeout: Double = 30
    /// app が前に出ていないとできない (= カメラ・NFC・ショートカットなど)
    var foreground = false

    var json: [String: Any] {
        ["name": name, "kind": kind.rawValue, "summary": summary, "timeout_s": timeout, "foreground": foreground,
         "params": params.map { ["name": $0.name, "type": $0.kind.rawValue, "required": $0.required,
                                 "description": $0.description] }]
    }
}

/// 答えに付ける file (= backend が data/device-files/ に書く)。
struct DeviceFile {
    let name: String
    let mime: String
    let data: Data
}

/// 操作の答え (= JSON にできる値と、 付ける file)。
struct DeviceOutput {
    let value: Any
    var files: [DeviceFile] = []

    init(_ value: Any, files: [DeviceFile] = []) {
        self.value = value
        self.files = files
    }
}

/// 頼みの引数 (= 型を直して取り出す)。
struct DeviceArgs {
    private let raw: [String: Any]
    init(_ raw: [String: Any]) { self.raw = raw }

    func string(_ name: String) -> String? { raw[name].map { "\($0)" } }
    func int(_ name: String) -> Int? {
        if let value = raw[name] as? Int { return value }
        return (raw[name] as? Double).map { Int($0) } ?? string(name).flatMap { Int($0) }
    }
    func number(_ name: String) -> Double? {
        if let value = raw[name] as? Double { return value }
        return (raw[name] as? Int).map { Double($0) } ?? string(name).flatMap { Double($0) }
    }
    func bool(_ name: String) -> Bool? { raw[name] as? Bool }

    func required(_ name: String) throws -> String {
        guard let value = string(name), !value.isEmpty else { throw DeviceError("\(name) is required") }
        return value
    }
}

/// 操作 1 つ。
protocol DeviceOperation {
    var spec: DeviceSpec { get }
    @MainActor func run(_ args: DeviceArgs) async throws -> DeviceOutput
}

/// 名前と中身を並べて書くための操作 (= 種類ごとの file はこれで一覧を作る)。
struct DeviceOp: DeviceOperation {
    let spec: DeviceSpec
    let body: @MainActor (DeviceArgs) async throws -> DeviceOutput

    init(_ spec: DeviceSpec, _ body: @escaping @MainActor (DeviceArgs) async throws -> DeviceOutput) {
        self.spec = spec
        self.body = body
    }

    @MainActor func run(_ args: DeviceArgs) async throws -> DeviceOutput { try await body(args) }
}

/// 操作ができなかった理由 (= そのまま Mac の命令に出る)。
struct DeviceError: LocalizedError {
    let message: String
    init(_ message: String) { self.message = message }
    var errorDescription: String? { message }
}

/// 日時を ISO 8601 の文字にする (= 答えの日時はこの形でそろえる)。
func iso(_ date: Date) -> String { ISO8601DateFormatter().string(from: date) }

/// 一番手前の画面 (= カメラなどを出す所)。
@MainActor func frontController() -> UIViewController? {
    let scene = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
        .first { $0.activationState == .foregroundActive }
    var top = scene?.windows.first { $0.isKeyWindow }?.rootViewController
    while let presented = top?.presentedViewController { top = presented }
    return top
}

/// app が前に出ているか (= 出ていないとできない操作で確かめる)。
@MainActor func requireForeground(_ what: String) throws {
    guard UIApplication.shared.applicationState == .active else {
        throw DeviceError("\(what) needs the app on screen; open the app and ask again")
    }
}
