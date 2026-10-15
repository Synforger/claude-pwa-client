import ActivityKit
import Foundation

/// ロック画面と Dynamic Island に出す、 agent の作業の進み具合 (= Live Activity)。
///
/// app が `cpc device progress.start / progress.update / progress.end` で出して書き換え、 見た目はウィジェットの
/// extension (= `Widgets/AgentActivityWidget.swift`) が描く。
@available(iOS 16.2, *)
struct AgentActivityAttributes: ActivityAttributes {
    struct ContentState: Codable, Hashable {
        /// 今していること (= 1 行)
        var detail: String
        /// 0〜1 の進み (= 無ければ進み具合の棒を出さない)
        var fraction: Double?
        /// 終わった (= 印を変えて、 しばらく残す)
        var done: Bool
    }

    /// 何の作業か (= 出した時に決まる)
    var title: String
}
