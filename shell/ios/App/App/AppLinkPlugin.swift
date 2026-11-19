import Capacitor
import Foundation

/// app を開く URL (= `claudepwa://open?ses=<sid>`、 通話も始めるなら `&call=1`) を受けて、 開くタブを画面へ渡す plugin。
/// 頼みの票の URL (= `claudepwa://open?ticket=<id>`) なら、 開く票を画面へ渡す。
///
/// URL を出すのはホーム画面のウィジェット (= `Widgets/TabsWidget.swift`) と、 Siri の「通話」 (= `Intents/AskAgent.swift`
/// の `CallAgentIntent`)。 画面の受け手は `frontend/src/features/session-drawer/appLinks.js`。 URL の型は `Info.plist`
/// の `CFBundleURLTypes` が登録する。 票の URL を出す物は今は無い (= backend の通知は app の通知へは届かず、 app の通知は
/// `cpc device notify post` だけ)。 出す物ができた時にそのまま開けるよう、 受け手だけ先に持つ。
///
/// app が閉じていた時は、 画面の読み込みより先に URL が届く (= Capacitor は plugin が載った後の最初の
/// `capacitorViewDidAppear` で配る)。 受け手がまだ居ない知らせは、 画面が受け手を付けるまで取っておく
/// (= `retainUntilConsumed`)。
///
/// 画面へ知らせる event:
///   openSession { sid, call }   そのタブを開く (= call が true なら、 声とマイクの会話も始める)
///   openTicket { ticket }       その票の画面を開く
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
        guard let url = notification.userInfo?["url"] as? URL else { return }
        if let ticket = Self.ticketId(in: url) {
            notifyListeners("openTicket", data: ["ticket": ticket], retainUntilConsumed: true)
            return
        }
        guard let sid = Self.sessionId(in: url) else { return }
        let call = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems?
            .contains { $0.name == "call" && $0.value == "1" } == true
        notifyListeners("openSession", data: ["sid": sid, "call": call], retainUntilConsumed: true)
    }

    /// そのタブを開いて通話も始める URL (= Siri の「通話」 が自分の app へ開く)
    static func callURL(sid: String) -> URL? {
        var parts = URLComponents()
        parts.scheme = scheme
        parts.host = "open"
        parts.queryItems = [URLQueryItem(name: "ses", value: sid), URLQueryItem(name: "call", value: "1")]
        return parts.url
    }

    /// `claudepwa://open?ticket=<id>` の票。 型か形が違う URL は nil。
    static func ticketId(in url: URL) -> String? {
        guard url.scheme == scheme, url.host == "open",
              let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems,
              let ticket = items.first(where: { $0.name == "ticket" })?.value, !ticket.isEmpty else { return nil }
        return ticket
    }

    /// `claudepwa://open?ses=<sid>` のタブ。 型か形が違う URL は nil (= 他の経路の URL には触らない)。
    static func sessionId(in url: URL) -> String? {
        guard url.scheme == scheme, url.host == "open",
              let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems,
              let sid = items.first(where: { $0.name == "ses" })?.value, !sid.isEmpty else { return nil }
        return sid
    }
}
