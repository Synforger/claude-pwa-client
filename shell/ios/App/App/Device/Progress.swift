import ActivityKit
import Foundation

/// ロック画面と Dynamic Island に、 agent の作業の進み具合を出す (= Live Activity。 見た目は Widgets/ が描く)。
///
/// 出しておけるのは 1 つ (= 新しく出すと前の物は閉じる)。 iOS は 8 時間で自動で閉じる。
enum Progress {
    static var ops: [DeviceOperation] {
        guard #available(iOS 16.2, *) else { return [] }
        return [
            DeviceOp(DeviceSpec(name: "progress.start", kind: .act,
                                summary: "show the agent's progress on the lock screen and the Dynamic Island",
                                params: [.string("title", "what the work is", required: true),
                                         .string("detail", "what is happening now"),
                                         .number("fraction", "progress from 0 to 1 (no bar without it)")])) { args in
                try await start(title: try args.required("title"), detail: args.string("detail") ?? "",
                                fraction: args.number("fraction"))
            },
            DeviceOp(DeviceSpec(name: "progress.update", kind: .change, summary: "change the progress shown on the lock screen",
                                params: [.string("detail", "what is happening now"),
                                         .number("fraction", "progress from 0 to 1")])) { args in
                try await update(detail: args.string("detail"), fraction: args.number("fraction"), done: false)
            },
            DeviceOp(DeviceSpec(name: "progress.end", kind: .act, summary: "mark the progress done and take it off the lock screen",
                                params: [.string("detail", "the last line (default: the current one)"),
                                         .int("linger", "seconds to keep it on screen after (default 300)")])) { args in
                try await end(detail: args.string("detail"), linger: args.int("linger") ?? 300)
            },
        ]
    }

    @available(iOS 16.2, *)
    private static var current: Activity<AgentActivityAttributes>? {
        Activity<AgentActivityAttributes>.activities.first { $0.activityState == .active }
    }

    @available(iOS 16.2, *)
    @MainActor private static func start(title: String, detail: String, fraction: Double?) async throws -> DeviceOutput {
        guard ActivityAuthorizationInfo().areActivitiesEnabled else {
            throw DeviceError("Live Activities are off for this app (Settings → the app → Live Activities)")
        }
        for old in Activity<AgentActivityAttributes>.activities {
            await old.end(nil, dismissalPolicy: .immediate)
        }
        let state = AgentActivityAttributes.ContentState(detail: detail, fraction: clamp(fraction), done: false)
        let activity = try Activity.request(attributes: AgentActivityAttributes(title: title),
                                            content: ActivityContent(state: state, staleDate: nil))
        return DeviceOutput(["id": activity.id, "title": title])
    }

    @available(iOS 16.2, *)
    @MainActor private static func update(detail: String?, fraction: Double?, done: Bool) async throws -> DeviceOutput {
        guard let activity = current else { throw DeviceError("no progress is shown; start one with progress.start") }
        var state = activity.content.state
        if let detail { state.detail = detail }
        if let fraction { state.fraction = clamp(fraction) }
        state.done = done
        await activity.update(ActivityContent(state: state, staleDate: nil))
        return DeviceOutput(["id": activity.id, "detail": state.detail, "fraction": state.fraction as Any])
    }

    @available(iOS 16.2, *)
    @MainActor private static func end(detail: String?, linger: Int) async throws -> DeviceOutput {
        guard let activity = current else { throw DeviceError("no progress is shown") }
        var state = activity.content.state
        if let detail { state.detail = detail }
        state.done = true
        if state.fraction != nil { state.fraction = 1 }
        await activity.end(ActivityContent(state: state, staleDate: nil),
                           dismissalPolicy: .after(Date().addingTimeInterval(Double(max(linger, 0)))))
        return DeviceOutput(["id": activity.id, "ended": true])
    }

    private static func clamp(_ value: Double?) -> Double? { value.map { min(max($0, 0), 1) } }
}
