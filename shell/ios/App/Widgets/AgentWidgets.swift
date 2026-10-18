import SwiftUI
import WidgetKit

/// ウィジェットの extension に入っている物 (= タブの状態、 agent が置く Board、 agent の作業の進み具合)。
///
/// 選べる Tabs と Board は iOS 17 から (= ウィジェットの編集が AppIntents で書けるのは iOS 17 から)。 それより前の
/// iOS では、 選べない Tabs だけが出る。
@main
struct AgentWidgets: WidgetBundle {
    var body: some Widget {
        if #available(iOS 17.0, *) {
            TabsWidget()
        }
        if #available(iOS 17.0, *) {
            BoardWidget()
        }
        TabsWidgetFixed()
        AgentActivityWidget()
    }
}
