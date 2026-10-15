@_weakLinked import AlarmKit
import ActivityKit
import AVFoundation
import CoreBluetooth
import CoreLocation
import CoreMotion
import FamilyControls
import Foundation
import Intents
import LocalAuthentication
import MediaPlayer
import MusicKit
import Photos
import Speech
import UserNotifications
import WorkoutKit

/// 許可の状態: この app が iOS から受けている許可を、 種類ごとにまとめて返す (= 確認の画面は出さない。 読むだけ)。
///
/// 値は allowed (= 一番広い) / limited (= 一部だけ。 写真の一部・おおよその位置など) / denied / not asked / restricted
/// (= 機能制限などで変えられない)。 `not_max` は一番広くない種類の一覧で、 設定のどこで変えるかを添える。
enum Permissions {
    static let ops: [DeviceOperation] = [
        DeviceOp(DeviceSpec(name: "permissions.status", kind: .read,
                            summary: "what this app is allowed to use, kind by kind, and which are not at the widest")) { _ in
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
            if let homes = Homes.authorization {
                put("home", homes.contains(.authorized) ? "allowed" : homes.contains(.restricted) ? "restricted" : "denied",
                    fix: "\(app) → Home")
            } else {
                kinds["home"] = "unknown until home.list has run (asking would show the prompt)"
            }
            let health = Health.writeStatus()
            kinds["health"] = ["write": health, "read": "iOS does not tell apps; check Health → profile → Apps"]
            if health.values.contains(where: { $0 != "allowed" }) {
                notMax.append(["kind": "health", "now": "write: \(health)", "change_in": "Health → profile → Apps → this app → Turn On All"])
            }
            let context = LAContext()
            var biometricError: NSError?
            let biometric = context.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: &biometricError)
            kinds["face_id"] = biometric ? "allowed" : (biometricError?.code == LAError.biometryNotAvailable.rawValue ? "denied" : "not set up")
            if !biometric { notMax.append(["kind": "face_id", "now": "\(kinds["face_id"]!)", "change_in": "\(app) → Face ID"]) }
            if #available(iOS 16.2, *) {
                put("live_activities", ActivityAuthorizationInfo().areActivitiesEnabled ? "allowed" : "denied",
                    fix: "\(app) → Live Activities")
            }
            if #available(iOS 16.0, *) {
                put("screen_time", word(AuthorizationCenter.shared.authorizationStatus), fix: "needs a paid developer team")
            }
            if #available(iOS 17.0, *) {
                put("workouts", await workoutState(), fix: "\(app) → Workouts (Apple Watch)")
            }
            if #available(iOS 26.0, *) {
                put("alarms", word(AlarmManager.shared.authorizationState), fix: "\(app) → Alarms")
            }
            return DeviceOutput(["kinds": kinds, "not_max": notMax])
        },
    ]

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
