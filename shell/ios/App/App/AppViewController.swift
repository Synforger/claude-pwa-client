import Capacitor
import UIKit

/// Capacitor の画面に、 この app の中にある plugin を登録する (= npm の plugin でない物は自動では載らない)。
class AppViewController: CAPBridgeViewController {
    override open func capacitorDidLoad() {
        bridge?.registerPluginInstance(BackgroundVoicePlugin())
        bridge?.registerPluginInstance(AppLinkPlugin())
    }
}
