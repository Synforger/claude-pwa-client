import Capacitor
import UIKit
import UserNotifications

/// app が出した通知 (= `cpc device notify post`) を、 app が前に出ている時もバナーと通知センターに出す。
///
/// Capacitor は通知の受け手を自分で引き受け、 local notification の plugin が居ない時は「出さない」 と答える
/// (= `NotificationRouter.willPresent` が `[]` を返す)。 iOS が app を前と見ている間 (= 画面に出ている時など) は、
/// その答えで通知がどこにも出なかった。 ここが plugin の代わりに出し方を答える。 呼ばれた時の app の状態は
/// backend の記録 (= `logs/backend.error.log` の `sw-log` の `notify:` の行) に残す。
final class NotificationPresenter: NSObject, NotificationHandlerProtocol {
    static let shared = NotificationPresenter()

    func willPresent(notification: UNNotification) -> UNNotificationPresentationOptions {
        Self.report("present", ["id": notification.request.identifier, "app": Self.appState()])
        return [.banner, .list, .sound]
    }

    func didReceive(response: UNNotificationResponse) {
        Self.report("opened", ["id": response.notification.request.identifier, "app": Self.appState()])
    }

    /// 通知の設定 (= 許可とは別に、 バナー・通知センター・ロック画面の 1 つずつ。 `notify.post` の答えにも載せる)
    static func settings() async -> [String: Any] {
        let current = await UNUserNotificationCenter.current().notificationSettings()
        func word(_ setting: UNNotificationSetting) -> String {
            switch setting {
            case .enabled: return "on"
            case .disabled: return "off"
            case .notSupported: return "not supported"
            @unknown default: return "unknown"
            }
        }
        let style: String
        switch current.alertStyle {
        case .banner: style = "banner"
        case .alert: style = "alert"
        case .none: style = "none"
        @unknown default: style = "unknown"
        }
        return ["alerts": word(current.alertSetting), "style": style,
                "notification_center": word(current.notificationCenterSetting),
                "lock_screen": word(current.lockScreenSetting), "sound": word(current.soundSetting)]
    }

    /// 今の app の状態 (= 前に出ている / 前だが触れない / 裏)
    private static func appState() -> String {
        let read = {
            switch UIApplication.shared.applicationState {
            case .active: return "active"
            case .inactive: return "inactive"
            case .background: return "background"
            @unknown default: return "unknown"
            }
        }
        return Thread.isMainThread ? read() : DispatchQueue.main.sync(execute: read)
    }

    /// 通知の出来事を、 app の log と backend の log の両方に出す (= 裏で起きた事は backend にしか残らない)。
    static func report(_ event: String, _ detail: [String: Any] = [:]) {
        CAPLog.print("[Notify] \(stamp()) \(event) \(detail)")
        guard let url = try? ServerAddress.url("/log/sw") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        var payload = detail
        payload["stage"] = "notify:\(event)"
        payload["at"] = stamp()
        request.httpBody = try? JSONSerialization.data(withJSONObject: payload)
        URLSession.shared.dataTask(with: request).resume()
    }
}
