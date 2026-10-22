import Capacitor
import SafariServices
import UIKit
import WebKit

/// 画面が開く web の page を、 app の中の閲覧の画面 (= `SFSafariViewController`。 上の「完了」 で閉じて元の画面に戻る)
/// で開く plugin。
///
/// Capacitor の既定では、 新しい窓 (= `window.open(…, '_blank')`・`<a target="_blank">`) と app の外の host への遷移は
/// Safari (= 別の app) に渡り、 app へ戻る × が無い。 backend の file の口 (= `/file/…`。 HTML・画像) へ主の画面が移ると、
/// app の画面そのものが置き換わって戻れない。 Capacitor は遷移を決める前に plugin へ訊く (= `shouldOverrideLoad`) ので、
/// そこで取り消して閲覧の画面で開く。
///
/// ただし HTML のページ (= backend の `/file/open` の `path` が `.html` / `.htm`) だけは、 閲覧の画面でなく OS の既定の
/// ブラウザ (= `UIApplication.open`) へ渡す。 資料 (= pdf・Office・tif)・画像・Markdown は画面がプレビューで開くので、
/// ここへは来ない。
///
/// 取り消すのは http(s) の遷移で、 新しい窓か、 主の画面が app の画面の外 (= 別の host か `/file/` の下) へ移る物だけ。
/// http(s) でない物 (= `slack://`・`tel:`・`mailto:`) と、 app 自身の画面の遷移は、 Capacitor の既定に任せる。
@objc(PageSheetPlugin)
public class PageSheetPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "PageSheetPlugin"
    public let jsName = "PageSheet"
    public let pluginMethods: [CAPPluginMethod] = []

    override public func shouldOverrideLoad(_ navigationAction: WKNavigationAction) -> NSNumber? {
        guard let url = navigationAction.request.url, ["http", "https"].contains(url.scheme?.lowercased() ?? "") else {
            return nil
        }
        let newWindow = navigationAction.targetFrame == nil
        guard newWindow || navigationAction.targetFrame?.isMainFrame == true, leavesApp(url) || newWindow else {
            return nil
        }
        DispatchQueue.main.async { [weak self] in
            if Self.opensInDefaultBrowser(url) {
                UIApplication.shared.open(url)
            } else {
                self?.present(url)
            }
        }
        return NSNumber(value: true)
    }

    /// 既定のブラウザで開くべき行き先か (= `/file/open?path=<….html | ….htm>`。 画面が HTML のタップで開く窓の URL)
    static func opensInDefaultBrowser(_ url: URL) -> Bool {
        guard url.path.hasSuffix("/file/open"),
              let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems,
              let path = items.first(where: { $0.name == "path" })?.value?.lowercased()
        else {
            return false
        }
        return path.hasSuffix(".html") || path.hasSuffix(".htm")
    }

    /// 主の画面が移ると app の画面が無くなる行き先 (= 別の host か、 backend の file の口)
    private func leavesApp(_ url: URL) -> Bool {
        guard let server = bridge?.config.serverURL else { return false }
        if url.host?.lowercased() != server.host?.lowercased() || url.port != server.port {
            return true
        }
        return url.path.hasPrefix("/file/")
    }

    private func present(_ url: URL) {
        guard var top = bridge?.viewController else { return }
        while let shown = top.presentedViewController {
            top = shown
        }
        let sheet = SFSafariViewController(url: url)
        sheet.dismissButtonStyle = .close
        top.present(sheet, animated: true)
    }
}
