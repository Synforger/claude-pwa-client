import SwiftUI
import WidgetKit

/// ウィジェットの extension に入っている物 (= タブの状態と、 agent の作業の進み具合)。
@main
struct AgentWidgets: WidgetBundle {
    var body: some Widget {
        TabsWidget()
        AgentActivityWidget()
    }
}
