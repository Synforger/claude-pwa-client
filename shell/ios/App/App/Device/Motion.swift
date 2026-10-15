import CoreMotion
import Foundation

/// 動き: 日ごとの歩数と階段 (= 端末の歩数計。 7 日まで) と、 歩いていたか乗り物に乗っていたか。
enum Motion {
    private static let pedometer = CMPedometer()
    private static let activity = CMMotionActivityManager()

    static let ops: [DeviceOperation] = [
        DeviceOp(DeviceSpec(name: "motion.steps", kind: .read, summary: "steps, distance and floors per day (up to 7 days)",
                            params: [.int("days", "how many days back, today included (default 7, at most 7)")])) { args in
            guard CMPedometer.isStepCountingAvailable() else { throw DeviceError("step counting is not available") }
            let days = min(max(args.int("days") ?? 7, 1), 7)
            let calendar = Calendar.current
            var rows: [[String: Any]] = []
            for back in (0..<days).reversed() {
                let start = calendar.date(byAdding: .day, value: -back, to: calendar.startOfDay(for: Date()))!
                let end = min(calendar.date(byAdding: .day, value: 1, to: start)!, Date())
                let data: CMPedometerData = try await withCheckedThrowingContinuation { done in
                    pedometer.queryPedometerData(from: start, to: end) { data, error in
                        if let data { done.resume(returning: data) } else {
                            done.resume(throwing: error ?? DeviceError("no pedometer data"))
                        }
                    }
                }
                rows.append(["day": iso(start), "steps": data.numberOfSteps, "distance_m": data.distance as Any,
                             "floors_up": data.floorsAscended as Any])
            }
            return DeviceOutput(["days": rows])
        },
        DeviceOp(DeviceSpec(name: "motion.activity", kind: .read,
                            summary: "what the iPhone was doing: walking, running, cycling, in a vehicle or still",
                            params: [.int("hours", "how many hours back (default 24)")])) { args in
            guard CMMotionActivityManager.isActivityAvailable() else { throw DeviceError("activity is not available") }
            let start = Date().addingTimeInterval(-Double(args.int("hours") ?? 24) * 3600)
            let found: [CMMotionActivity] = try await withCheckedThrowingContinuation { done in
                activity.queryActivityStarting(from: start, to: Date(), to: .main) { found, error in
                    if let error { done.resume(throwing: error) } else { done.resume(returning: found ?? []) }
                }
            }
            // 同じ様子が続く間は 1 行にまとめる
            var rows: [[String: Any]] = []
            for item in found {
                let what = state(item)
                if rows.last?["state"] as? String == what { continue }
                rows.append(["state": what, "from": iso(item.startDate)])
            }
            return DeviceOutput(["segments": rows])
        },
    ]

    private static func state(_ item: CMMotionActivity) -> String {
        if item.automotive { return "vehicle" }
        if item.cycling { return "cycling" }
        if item.running { return "running" }
        if item.walking { return "walking" }
        if item.stationary { return "still" }
        return "unknown"
    }
}
