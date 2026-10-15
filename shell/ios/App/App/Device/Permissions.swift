@_weakLinked import AlarmKit
import ActivityKit
import AVFoundation
import Capacitor
import CoreBluetooth
import CoreLocation
import CoreMotion
import FamilyControls
import Foundation
import HomeKit
import Intents
import LocalAuthentication
import MediaPlayer
import MusicKit
import Photos
import Speech
import UserNotifications
import WorkoutKit

/// 許可の状態と確認: この app が iOS から受けている許可を種類ごとにまとめて返し (= `permissions.status`。 読むだけ)、
/// まだ訊いていない種類の確認を順に出す (= `permissions.request` と、 app が前に出た時。 `askAll`)。
///
/// 値は allowed (= 一番広い) / limited (= 一部だけ。 写真の一部・おおよその位置など) / denied / not asked / restricted
/// (= 機能制限などで変えられない)。 `not_max` は一番広くない種類の一覧で、 設定のどこで変えるかを添える。
enum Permissions {
    static let ops: [DeviceOperation] = [
        DeviceOp(DeviceSpec(name: "permissions.status", kind: .read,
                            summary: "what this app is allowed to use, kind by kind, and which are not at the widest")) { _ in
            DeviceOutput(await snapshot())
        },
        DeviceOp(DeviceSpec(name: "permissions.request", kind: .act,
                            summary: "show the prompt for every kind not asked yet, one after another, then the status",
                            timeout: 600, foreground: true)) { _ in
            try requireForeground("Asking for permissions")
            let asked = await askAll()
            var out = await snapshot()
            out["asked"] = asked
            out["not_possible"] = notPossible + Signature.missing.map { ["kind": $0.kind, "why": Signature.why($0.kind)] }
            return DeviceOutput(out)
        },
    ]

    /// 無料の Apple ID (= Personal Team) の署名では iOS が断る種類 (= 許可の確認より前に、 app に権利を付けられない)
    static let notPossible: [[String: String]] = [
        ["kind": "screen_time", "why": "Family Controls needs a paid developer team"],
        ["kind": "push_notifications", "why": "remote push needs a paid developer team (notifications made on the iPhone work)"],
        ["kind": "nfc", "why": "reading NFC tags needs a paid developer team"],
        ["kind": "wifi_name", "why": "the Wi-Fi network name needs a paid developer team"],
        ["kind": "journaling_suggestions", "why": "Journaling Suggestions needs a paid developer team"],
        ["kind": "communication_notifications", "why": "communication notifications need a paid developer team"],
    ]

    /// 種類ごとの許可の今 (= `kinds` と `not_max`)
    @MainActor static func snapshot() async -> [String: Any] {
        var kinds: [String: Any] = [:]
        var notMax: [[String: String]] = []
        func put(_ name: String, _ value: String, fix: String) {
            kinds[name] = value
            if value != "allowed" { notMax.append(["kind": name, "now": value, "change_in": fix]) }
        }
        let app = "Settings → \(Bundle.main.object(forInfoDictionaryKey: "CFBundleDisplayName") as? String ?? "the app")"

        let location = CLLocationManager()
        var where_ = word(location.authorizationStatus)
        if where_ == "allowed", location.accuracyAuthorization == .reducedAccuracy { where_ = "limited" }
        put("location", where_, fix: "\(app) → Location → While Using the App, with Precise Location on")
        put("photos", word(PHPhotoLibrary.authorizationStatus(for: .readWrite)), fix: "\(app) → Photos → Full Access")
        put("camera", word(AVCaptureDevice.authorizationStatus(for: .video)), fix: "\(app) → Camera")
        put("microphone", microphone(), fix: "\(app) → Microphone")
        put("speech_recognition", word(SFSpeechRecognizer.authorizationStatus()), fix: "\(app) → Speech Recognition")
        put("motion", word(CMMotionActivityManager.authorizationStatus()), fix: "\(app) → Motion & Fitness")
        put("bluetooth", word(CBManager.authorization), fix: "\(app) → Bluetooth")
        put("music_library", word(MPMediaLibrary.authorizationStatus()), fix: "\(app) → Media & Apple Music")
        put("apple_music", word(MusicAuthorization.currentStatus), fix: "\(app) → Media & Apple Music")
        put("notifications", word(await UNUserNotificationCenter.current().notificationSettings().authorizationStatus),
            fix: "\(app) → Notifications")
        put("focus", word(INFocusStatusCenter.default.authorizationStatus), fix: "\(app) → Focus")
        if !Signature.allows("home") {
            kinds["home"] = Signature.why("home")
        } else if let homes = Homes.authorization ?? HomeAsk.status {
            put("home", homes.contains(.authorized) ? "allowed" : homes.contains(.restricted) ? "restricted" : "denied",
                fix: "\(app) → Home")
        } else {
            kinds["home"] = "unknown until home.list has run (asking would show the prompt)"
        }
        let health = Signature.allows("health") ? Health.writeStatus() : [:]
        kinds["health"] = Signature.allows("health")
            ? ["write": health, "read": "iOS does not tell apps; check Health → profile → Apps"] as [String: Any]
            : Signature.why("health")
        if health.values.contains(where: { $0 != "allowed" }) {
            notMax.append(["kind": "health", "now": "write: \(health)", "change_in": "Health → profile → Apps → this app → Turn On All"])
        }
        let context = LAContext()
        var biometricError: NSError?
        let biometric = context.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: &biometricError)
        kinds["face_id"] = biometric
            ? (UserDefaults.standard.bool(forKey: faceIDAsked) ? "allowed" : "not asked")
            : (biometricError?.code == LAError.biometryNotAvailable.rawValue ? "denied" : "not set up")
        if kinds["face_id"] as? String != "allowed" {
            notMax.append(["kind": "face_id", "now": "\(kinds["face_id"]!)", "change_in": "\(app) → Face ID"])
        }
        if #available(iOS 16.2, *) {
            put("live_activities", ActivityAuthorizationInfo().areActivitiesEnabled ? "allowed" : "denied",
                fix: "\(app) → Live Activities")
        }
        if #available(iOS 16.0, *) {
            put("screen_time", word(AuthorizationCenter.shared.authorizationStatus), fix: "needs a paid developer team")
        }
        if #available(iOS 17.0, *) {
            if WorkoutScheduler.isSupported {
                put("workouts", await workoutState(), fix: "\(app) → Workouts (Apple Watch)")
            } else {
                kinds["workouts"] = "no Apple Watch paired"   // (= 訊く物が無い。 一番広くない種類にも数えない)
            }
        }
        if #available(iOS 26.0, *) {
            put("alarms", word(AlarmManager.shared.authorizationState), fix: "\(app) → Alarms")
        }
        return ["kinds": kinds, "not_max": notMax]
    }

    /// Face ID の確認を出したか (= iOS は「まだ訊いていない」 を app に教えない。 訊くと覚える)
    static let faceIDAsked = "permissions.face_id.asked"
    /// 走っている確認 (= 前に出た時と `permissions.request` が重なっても、 確認の列は 1 本)
    @MainActor private static var asking: Task<[String], Never>?

    /// まだ訊いていない種類の確認を、 1 つずつ順に出す (= 答えを待ってから次へ)。 訊いた種類の名前を返す。
    ///
    /// 答えた種類はもう訊かないので、 app が前に出るたびに呼んでも、 確認が出るのは初めて開いた時と、 新しい版で
    /// 種類が増えた時だけになる。
    @MainActor static func askAll() async -> [String] {
        if let asking { return await asking.value }
        let task = Task { @MainActor in await askEach() }
        asking = task
        defer { asking = nil }
        return await task.value
    }

    @MainActor private static func askEach() async -> [String] {
        var asked: [String] = []
        func ask(_ name: String, when notAsked: Bool, _ body: () async throws -> Void) async {
            guard notAsked, Signature.allows(name) else { return }
            do { try await body() } catch { CAPLog.print("[Permissions] asking for \(name) failed: \(error)") }
            asked.append(name)
        }
        let center = UNUserNotificationCenter.current()
        await ask("notifications", when: await center.notificationSettings().authorizationStatus == .notDetermined) {
            _ = try await center.requestAuthorization(options: [.alert, .sound, .badge])
        }
        await ask("microphone", when: microphone() == "not asked") {
            if #available(iOS 17.0, *) {
                _ = await AVAudioApplication.requestRecordPermission()
            } else {
                _ = await withCheckedContinuation { done in
                    AVAudioSession.sharedInstance().requestRecordPermission { done.resume(returning: $0) }
                }
            }
        }
        await ask("speech_recognition", when: SFSpeechRecognizer.authorizationStatus() == .notDetermined) {
            _ = await withCheckedContinuation { done in SFSpeechRecognizer.requestAuthorization { done.resume(returning: $0) } }
        }
        await ask("location", when: CLLocationManager().authorizationStatus == .notDetermined) {
            await LocationAsk().run()
        }
        await ask("camera", when: AVCaptureDevice.authorizationStatus(for: .video) == .notDetermined) {
            _ = await AVCaptureDevice.requestAccess(for: .video)
        }
        await ask("photos", when: PHPhotoLibrary.authorizationStatus(for: .readWrite) == .notDetermined) {
            _ = await PHPhotoLibrary.requestAuthorization(for: .readWrite)
        }
        await ask("motion", when: CMMotionActivityManager.isActivityAvailable()
                  && CMMotionActivityManager.authorizationStatus() == .notDetermined) {
            let activity = CMMotionActivityManager()
            await withCheckedContinuation { done in
                activity.queryActivityStarting(from: Date(timeIntervalSinceNow: -60), to: Date(), to: .main) { _, _ in
                    done.resume()
                }
            }
        }
        await ask("bluetooth", when: CBManager.authorization == .notDetermined) {
            await BluetoothAsk().run()
        }
        await ask("apple_music", when: MusicAuthorization.currentStatus == .notDetermined) {
            _ = await MusicAuthorization.request()
        }
        await ask("music_library", when: MPMediaLibrary.authorizationStatus() == .notDetermined) {
            _ = await withCheckedContinuation { done in MPMediaLibrary.requestAuthorization { done.resume(returning: $0) } }
        }
        await ask("focus", when: INFocusStatusCenter.default.authorizationStatus == .notDetermined) {
            _ = await withCheckedContinuation { done in
                INFocusStatusCenter.default.requestAuthorization { done.resume(returning: $0) }
            }
        }
        await ask("home", when: !HomeAsk.asked) {
            await HomeAsk.run()
        }
        await ask("health", when: await Health.shouldAsk()) {
            try await Health.askAll()
        }
        if #available(iOS 17.0, *) {
            let workouts = WorkoutScheduler.isSupported ? await workoutState() : "not supported"
            await ask("workouts", when: workouts == "not asked") {
                _ = await WorkoutScheduler.shared.requestAuthorization()
            }
        }
        if #available(iOS 26.0, *) {
            await ask("alarms", when: AlarmManager.shared.authorizationState == .notDetermined) {
                _ = try await AlarmManager.shared.requestAuthorization()
            }
        }
        let context = LAContext()
        await ask("face_id", when: !UserDefaults.standard.bool(forKey: faceIDAsked)
                  && context.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: nil)) {
            UserDefaults.standard.set(true, forKey: faceIDAsked)
            _ = try await context.evaluatePolicy(.deviceOwnerAuthenticationWithBiometrics,
                                                 localizedReason: "Allow Face ID so the agent can ask you to confirm")
        }
        if !asked.isEmpty { CAPLog.print("[Permissions] asked: \(asked.joined(separator: ", "))") }
        return asked
    }

    /// ワークアウトの予定の許可 (= 状態の型は main の外で読み、 文字にしてから返す)
    @available(iOS 17.0, *)
    nonisolated private static func workoutState() async -> String {
        word(await WorkoutScheduler.shared.authorizationState)
    }

    private static func microphone() -> String {
        if #available(iOS 17.0, *) {
            switch AVAudioApplication.shared.recordPermission {
            case .granted: return "allowed"
            case .denied: return "denied"
            default: return "not asked"
            }
        }
        switch AVAudioSession.sharedInstance().recordPermission {
        case .granted: return "allowed"
        case .denied: return "denied"
        default: return "not asked"
        }
    }

    /// Swift の型の状態 (= 名前の綴りで分ける。 Objective-C の型は文字にすると型の名前しか出ないので、 下で 1 つずつ書く)
    private static func word<T>(_ status: T) -> String {
        let name = "\(status)".lowercased()
        if name.contains("authorized") || name.contains("approved") { return "allowed" }
        if name.contains("denied") { return "denied" }
        if name.contains("restricted") { return "restricted" }
        return "not asked"
    }

    private static func word(_ status: CLAuthorizationStatus) -> String {
        switch status {
        case .authorizedAlways, .authorizedWhenInUse: return "allowed"
        case .denied: return "denied"
        case .restricted: return "restricted"
        default: return "not asked"
        }
    }

    private static func word(_ status: PHAuthorizationStatus) -> String {
        switch status {
        case .authorized: return "allowed"
        case .limited: return "limited"
        case .denied: return "denied"
        case .restricted: return "restricted"
        default: return "not asked"
        }
    }

    private static func word(_ status: AVAuthorizationStatus) -> String {
        switch status {
        case .authorized: return "allowed"
        case .denied: return "denied"
        case .restricted: return "restricted"
        default: return "not asked"
        }
    }

    private static func word(_ status: SFSpeechRecognizerAuthorizationStatus) -> String {
        switch status {
        case .authorized: return "allowed"
        case .denied: return "denied"
        case .restricted: return "restricted"
        default: return "not asked"
        }
    }

    private static func word(_ status: CMAuthorizationStatus) -> String {
        switch status {
        case .authorized: return "allowed"
        case .denied: return "denied"
        case .restricted: return "restricted"
        default: return "not asked"
        }
    }

    private static func word(_ status: CBManagerAuthorization) -> String {
        switch status {
        case .allowedAlways: return "allowed"
        case .denied: return "denied"
        case .restricted: return "restricted"
        default: return "not asked"
        }
    }

    private static func word(_ status: MPMediaLibraryAuthorizationStatus) -> String {
        switch status {
        case .authorized: return "allowed"
        case .denied: return "denied"
        case .restricted: return "restricted"
        default: return "not asked"
        }
    }

    private static func word(_ status: UNAuthorizationStatus) -> String {
        switch status {
        case .authorized: return "allowed"
        case .provisional, .ephemeral: return "limited"
        case .denied: return "denied"
        default: return "not asked"
        }
    }

    private static func word(_ status: INFocusStatusAuthorizationStatus) -> String {
        switch status {
        case .authorized: return "allowed"
        case .denied: return "denied"
        case .restricted: return "restricted"
        default: return "not asked"
        }
    }
}

/// 位置の確認を出し、 答えが出るまで待つ (= 係は作った時にも今の状態を知らせてくるので、 「まだ」 の知らせは見送る)。
@MainActor private final class LocationAsk: NSObject, CLLocationManagerDelegate {
    private let manager = CLLocationManager()
    private var waiting: CheckedContinuation<Void, Never>?

    func run() async {
        await withCheckedContinuation { done in
            waiting = done
            manager.delegate = self
            manager.requestWhenInUseAuthorization()
        }
    }

    nonisolated func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        let status = manager.authorizationStatus
        Task { @MainActor in
            guard status != .notDetermined else { return }
            self.waiting?.resume()
            self.waiting = nil
        }
    }
}

/// Bluetooth の確認を出し、 答えが出るまで待つ (= 係を作ると iOS が訊く。 切れている時の「入れて」 の知らせは出さない)。
@MainActor private final class BluetoothAsk: NSObject, CBCentralManagerDelegate {
    private var manager: CBCentralManager?
    private var waiting: CheckedContinuation<Void, Never>?

    func run() async {
        await withCheckedContinuation { done in
            waiting = done
            manager = CBCentralManager(delegate: self, queue: .main, options: [CBCentralManagerOptionShowPowerAlertKey: false])
        }
    }

    nonisolated func centralManagerDidUpdateState(_ central: CBCentralManager) {
        Task { @MainActor in
            guard CBManager.authorization != .notDetermined else { return }
            self.waiting?.resume()
            self.waiting = nil
            self.manager = nil
        }
    }
}

/// 家の確認を出し、 答えが出るまで待つ (= 係を作ると iOS が訊く。 答えは覚えて、 次からは訊かない)。
@MainActor final class HomeAsk: NSObject, HMHomeManagerDelegate {
    private static let key = "permissions.home.asked"
    private static var shared: HomeAsk?
    private let manager = HMHomeManager()
    private var waiting: CheckedContinuation<Void, Never>?

    static var asked: Bool { UserDefaults.standard.bool(forKey: key) }
    /// この起動で訊いた後の状態 (= 家の一覧を読む前の `permissions.status` に出す)
    static var status: HMHomeManagerAuthorizationStatus? { shared?.manager.authorizationStatus }

    static func run() async {
        let ask = shared ?? HomeAsk()
        shared = ask
        UserDefaults.standard.set(true, forKey: key)
        if ask.manager.authorizationStatus.contains(.determined) { return }
        await withCheckedContinuation { ask.waiting = $0 }
    }

    override init() {
        super.init()
        manager.delegate = self
    }

    nonisolated func homeManager(_ manager: HMHomeManager, didUpdate status: HMHomeManagerAuthorizationStatus) {
        Task { @MainActor in
            guard status.contains(.determined) else { return }
            self.finish()
        }
    }

    /// 家の一覧が届いた (= 答えが出た後に来る。 状態の知らせが来ない版でも、 ここで待ちを終える)
    nonisolated func homeManagerDidUpdateHomes(_ manager: HMHomeManager) {
        Task { @MainActor in self.finish() }
    }

    private func finish() {
        waiting?.resume()
        waiting = nil
    }
}

/// この app の署名が持つ権利 (= 署名に付いた `embedded.mobileprovision` の中の一覧)。
///
/// 権利の要る種類は、 署名に権利が無いと iOS が断る。 iPhone の上で署名し直して入れる道具は、 App ID に付けられる
/// 機能が限られていて、 ヘルスケアとホームの権利を持たないことがある (= Xcode で組んで入れた app は持つ)。
enum Signature {
    /// 権利が要る種類と、 その権利
    private static let needs = ["health": "com.apple.developer.healthkit", "home": "com.apple.developer.homekit"]

    private static let entitlements: [String: Any]? = {
        guard let url = Bundle.main.url(forResource: "embedded", withExtension: "mobileprovision"),
              let data = try? Data(contentsOf: url),
              let start = data.range(of: Data("<?xml".utf8)),
              let end = data.range(of: Data("</plist>".utf8), in: start.lowerBound..<data.endIndex),
              let profile = try? PropertyListSerialization.propertyList(
                  from: data[start.lowerBound..<end.upperBound], format: nil) as? [String: Any]
        else { return nil }
        return profile["Entitlements"] as? [String: Any]
    }()

    /// その種類を使える署名か (= 権利の要らない種類と、 署名の一覧が読めない時は使えるとみなす)
    static func allows(_ kind: String) -> Bool {
        guard let key = needs[kind], let entitlements else { return true }
        return entitlements[key] != nil
    }

    /// 権利が無くて使えない種類
    static var missing: [(kind: String, entitlement: String)] {
        needs.filter { !allows($0.key) }.map { ($0.key, $0.value) }.sorted { $0.kind < $1.kind }
    }

    static func why(_ kind: String) -> String {
        "not in this app's signature (\(needs[kind] ?? kind)); install a build signed from Xcode to use it"
    }
}
