import Foundation
import WidgetKit

/// ホーム画面とロック画面のウィジェットを描き直させる (= backend が Board を書き換えた時に頼む。 中身は Widgets/)。
///
/// ウィジェットは iOS が決める間隔でしか自分では引き直さない。 app が起きている間なら、 ここから今すぐ引き直させられる。
enum WidgetsOps {
    static let ops: [DeviceOperation] = [
        DeviceOp(DeviceSpec(name: "widget.reload", kind: .act,
                            summary: "redraw the home and lock screen widgets now (cpc device widget set does this itself)",
                            timeout: 5)) { _ in
            WidgetCenter.shared.reloadAllTimelines()
            return DeviceOutput(["reloaded": true])
        },
    ]
}
