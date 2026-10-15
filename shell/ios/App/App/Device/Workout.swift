import Foundation
import HealthKit
import WorkoutKit

/// ワークアウト: Apple Watch のワークアウト app に、 時間を決めたワークアウトを予定として送る (= iPhone と組になった
/// Apple Watch が要る)。
enum Workout {
    static var ops: [DeviceOperation] {
        guard #available(iOS 17.0, *) else { return [] }
        return [
            DeviceOp(DeviceSpec(name: "workout.schedule", kind: .add,
                                summary: "put a timed workout on the Apple Watch's schedule",
                                params: [.string("activity", "one of: \(activities.keys.sorted().joined(separator: ", "))", required: true),
                                         .number("minutes", "how long", required: true),
                                         .string("at", "when, ISO 8601 (default: now)")])) { args in
                try await allow()
                let name = try args.required("activity")
                guard let activity = activities[name] else { throw DeviceError("activity is one of \(activities.keys.sorted())") }
                guard let minutes = args.number("minutes"), minutes > 0 else { throw DeviceError("minutes must be more than 0") }
                var when = Date()
                if let raw = args.string("at") {
                    guard let parsed = ISO8601DateFormatter().date(from: raw) else { throw DeviceError("at is not ISO 8601") }
                    when = parsed
                }
                let plan = WorkoutPlan(.goal(SingleGoalWorkout(activity: activity, goal: .time(minutes, .minutes))))
                let parts = Calendar.current.dateComponents([.year, .month, .day, .hour, .minute], from: when)
                await WorkoutScheduler.shared.schedule(plan, at: parts)
                return DeviceOutput(["scheduled": name, "minutes": minutes, "at": iso(when)])
            },
            DeviceOp(DeviceSpec(name: "workout.scheduled", kind: .read, summary: "workouts on the Apple Watch's schedule")) { _ in
                try await allow()
                let plans = await WorkoutScheduler.shared.scheduledWorkouts
                return DeviceOutput(plans.map { item -> [String: Any] in
                    let date = Calendar.current.date(from: item.date)
                    return ["activity": activities.first { $0.value == item.plan.workout.activity }?.key ?? "other",
                            "at": date.map(iso) as Any, "complete": item.complete]
                })
            },
        ]
    }

    private static let activities: [String: HKWorkoutActivityType] = [
        "running": .running, "walking": .walking, "cycling": .cycling, "swimming": .swimming, "hiking": .hiking,
        "yoga": .yoga, "strength": .traditionalStrengthTraining, "hiit": .highIntensityIntervalTraining,
        "elliptical": .elliptical, "rowing": .rowing, "dance": .socialDance, "stretching": .flexibility,
    ]

    @available(iOS 17.0, *)
    private static func allow() async throws {
        guard WorkoutScheduler.isSupported else { throw DeviceError("no Apple Watch is paired") }
        guard await WorkoutScheduler.shared.requestAuthorization() == .authorized else {
            throw DeviceError("scheduling workouts is not allowed")
        }
    }
}
