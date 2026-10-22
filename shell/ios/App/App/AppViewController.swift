import Capacitor
import UIKit

/// Capacitor の画面に、 この app の中にある plugin を登録する (= npm の plugin でない物は自動では載らない)。
class AppViewController: CAPBridgeViewController {
    override open func capacitorDidLoad() {
        bridge?.registerPluginInstance(BackgroundVoicePlugin())
        bridge?.registerPluginInstance(AppLinkPlugin())
        // 開いた web の page と HTML を既定のブラウザで、 残りを「完了」 で戻れる app の中の閲覧の画面で開く (= 中身は PageSheetPlugin)
        bridge?.registerPluginInstance(PageSheetPlugin())
        // app が出した通知を、 前に出ている時も出す (= Capacitor の既定は「出さない」。 中身は NotificationPresenter)
        bridge?.notificationRouter.localNotificationHandler = NotificationPresenter.shared
    }
}
