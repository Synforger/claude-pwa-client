import Capacitor
import Foundation

/// app を開く URL (= `claudepwa://open?ses=<sid>`) を受けて、 開くタブを画面へ渡す plugin。
///
/// app には iPhone の通知 (= APNs) が届かないので、 通知はホーム画面の PWA が受ける。 PWA で「通知を app で開く」
/// をオンにした端末では、 通知を押して開いた PWA がこの URL を開き、 iOS が app へ移す (= `frontend/src/features/
/// push-notify/openInApp.js`)。 URL の型は `Info.plist` の `CFBundleURLTypes` が登録する。
///
/// app が閉じていた時は、 画面の読み込みより先に URL が届く (= Capacitor は plugin が載った後の最初の
/// `capacitorViewDidAppear` で配る)。 受け手がまだ居ない知らせは、 画面が受け手を付けるまで取っておく
/// (= `retainUntilConsumed`)。
///
/// 画面へ知らせる event:
///   openSession { sid }   そのタブを開く
@objc(AppLinkPlugin)
public class AppLinkPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "AppLinkPlugin"
    public let jsName = "AppLink"
    public let pluginMethods: [CAPPluginMethod] = []

    static let scheme = "claudepwa"

    override public func load() {
        NotificationCenter.default.addObserver(
            self, selector: #selector(handleOpenURL(_:)), name: .capacitorSceneOpenURL, object: nil)
    }

    @objc private func handleOpenURL(_ notification: Notification) {
        guard let url = notification.userInfo?["url"] as? URL, let sid = Self.sessionId(in: url) else { return }
        notifyListeners("openSession", data: ["sid": sid], retainUntilConsumed: true)
    }

    /// `claudepwa://open?ses=<sid>` のタブ。 型か形が違う URL は nil (= 他の経路の URL には触らない)。
    static func sessionId(in url: URL) -> String? {
        guard url.scheme == scheme, url.host == "open",
              let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems,
              let sid = items.first(where: { $0.name == "ses" })?.value, !sid.isEmpty else { return nil }
        return sid
    }
}
