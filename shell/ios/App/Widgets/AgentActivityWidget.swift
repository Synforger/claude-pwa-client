import ActivityKit
import SwiftUI
import WidgetKit

/// agent の作業の進み具合 (= app の `progress.start / update / end` が出す Live Activity) の見た目。
struct AgentActivityWidget: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: AgentActivityAttributes.self) { context in
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Image(systemName: Self.symbol(context.state.done))
                    Text(context.attributes.title).font(.headline).lineLimit(1)
                }
                Text(context.state.detail).font(.subheadline).lineLimit(2)
                if let fraction = context.state.fraction {
                    ProgressView(value: fraction)
                }
            }
            .padding()
        } dynamicIsland: { context in
            DynamicIsland {
                DynamicIslandExpandedRegion(.leading) {
                    Image(systemName: Self.symbol(context.state.done))
                }
                DynamicIslandExpandedRegion(.center) {
                    Text(context.attributes.title).font(.headline).lineLimit(1)
                }
                DynamicIslandExpandedRegion(.bottom) {
                    VStack(alignment: .leading) {
                        Text(context.state.detail).font(.subheadline).lineLimit(2)
                        if let fraction = context.state.fraction {
                            ProgressView(value: fraction)
                        }
                    }
                }
            } compactLeading: {
                Image(systemName: Self.symbol(context.state.done))
            } compactTrailing: {
                Text(context.state.fraction.map { "\(Int($0 * 100))%" } ?? "")
            } minimal: {
                Image(systemName: Self.symbol(context.state.done))
            }
        }
    }

    static func symbol(_ done: Bool) -> String { done ? "checkmark.circle.fill" : "gearshape.2" }
}
