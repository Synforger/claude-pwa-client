import Foundation
import HealthKit

/// ヘルスケア: 日ごとの歩数・距離・心拍などを読み、 水や体重を書く。
///
/// 使うには、 app の署名にヘルスケアの権利 (= com.apple.developer.healthkit) が要る。 権利が無い build では、
/// 許可を頼む所で iOS が断り、 その理由がそのまま答えになる。
enum Health {
    private static let store = HKHealthStore()

    /// 読める量 (= 名前 → 種類・単位・日ごとに足すか平均か)
    private static let quantities: [String: (HKQuantityTypeIdentifier, HKUnit, Bool)] = [
        "steps": (.stepCount, .count(), true),
        "distance": (.distanceWalkingRunning, .meter(), true),
        "active_energy": (.activeEnergyBurned, .kilocalorie(), true),
        "flights": (.flightsClimbed, .count(), true),
        "water": (.dietaryWater, .liter(), true),
        "heart_rate": (.heartRate, HKUnit.count().unitDivided(by: .minute()), false),
        "resting_heart_rate": (.restingHeartRate, HKUnit.count().unitDivided(by: .minute()), false),
        "weight": (.bodyMass, .gramUnit(with: .kilo), false),
    ]
    /// 書ける量 (= 足す物だけ)
    private static let writable = ["water", "weight", "steps"]

    /// 書く許可の状態 (= 種類ごと。 読む許可は iOS が app に教えない)
    static func writeStatus() -> [String: String] {
        guard HKHealthStore.isHealthDataAvailable() else { return [:] }
        var out: [String: String] = [:]
        for name in writable {
            guard let type = quantities[name].map({ HKQuantityType($0.0) }) else { continue }
            switch store.authorizationStatus(for: type) {
            case .sharingAuthorized: out[name] = "allowed"
            case .sharingDenied: out[name] = "denied"
            default: out[name] = "not asked"
            }
        }
        return out
    }

    static let ops: [DeviceOperation] = [
        DeviceOp(DeviceSpec(name: "health.read", kind: .read,
                            summary: "per-day totals or averages of a health value",
                            params: [.string("type", "one of: \(quantities.keys.sorted().joined(separator: ", "))",
                                             required: true),
                                     .int("days", "how many days back, today included (default 7)")])) { args in
            try await read(args.required("type"), days: args.int("days") ?? 7)
        },
        DeviceOp(DeviceSpec(name: "health.sleep", kind: .read, summary: "sleep per night (asleep and in bed)",
                            params: [.int("days", "how many nights back (default 7)")])) { args in
            try await sleep(days: args.int("days") ?? 7)
        },
        DeviceOp(DeviceSpec(name: "health.write", kind: .add, summary: "record a value now",
                            params: [.string("type", "one of: \(writable.joined(separator: ", "))", required: true),
                                     .number("value", "in liters (water), kilograms (weight) or count (steps)",
                                             required: true)])) { args in
            try await write(args.required("type"), value: args.number("value"))
        },
    ]

    /// app が読む物と書く物の全部 (= `Permissions.askAll` がまとめて訊く)
    private static var allRead: Set<HKObjectType> {
        Set(quantities.values.map { HKQuantityType($0.0) as HKObjectType }).union([HKCategoryType(.sleepAnalysis)])
    }
    private static var allShare: Set<HKSampleType> {
        Set(writable.compactMap { quantities[$0].map { HKQuantityType($0.0) as HKSampleType } })
    }

    /// まだ確認を出していない種類が在るか
    static func shouldAsk() async -> Bool {
        guard HKHealthStore.isHealthDataAvailable() else { return false }
        return (try? await store.statusForAuthorizationRequest(toShare: allShare, read: allRead)) == .shouldRequest
    }

    /// 読む物と書く物の確認を 1 枚で出す
    static func askAll() async throws {
        try await ensure(read: allRead, share: allShare)
    }

    private static func ensure(read: Set<HKObjectType>, share: Set<HKSampleType> = []) async throws {
        guard HKHealthStore.isHealthDataAvailable() else { throw DeviceError("Health is not available on this device") }
        try await store.requestAuthorization(toShare: share, read: read)
    }

    private static func read(_ name: String, days: Int) async throws -> DeviceOutput {
        guard let (id, unit, cumulative) = quantities[name] else { throw DeviceError("unknown type \(name)") }
        let type = HKQuantityType(id)
        try await ensure(read: [type])
        let calendar = Calendar.current
        let end = Date()
        let start = calendar.date(byAdding: .day, value: -(max(days, 1) - 1), to: calendar.startOfDay(for: end))!
        let rows: [[String: Any]] = try await withCheckedThrowingContinuation { done in
            let query = HKStatisticsCollectionQuery(
                quantityType: type, quantitySamplePredicate: HKQuery.predicateForSamples(withStart: start, end: end),
                options: cumulative ? .cumulativeSum : .discreteAverage, anchorDate: start,
                intervalComponents: DateComponents(day: 1))
            query.initialResultsHandler = { _, collection, error in
                if let error { done.resume(throwing: error); return }
                var rows: [[String: Any]] = []
                collection?.enumerateStatistics(from: start, to: end) { stats, _ in
                    let quantity = cumulative ? stats.sumQuantity() : stats.averageQuantity()
                    rows.append(["day": iso(stats.startDate), "value": quantity.map { $0.doubleValue(for: unit) } as Any])
                }
                done.resume(returning: rows)
            }
            store.execute(query)
        }
        return DeviceOutput(["type": name, "unit": unit.unitString, "days": rows])
    }

    private static func sleep(days: Int) async throws -> DeviceOutput {
        let type = HKCategoryType(.sleepAnalysis)
        try await ensure(read: [type])
        let start = Calendar.current.date(byAdding: .day, value: -max(days, 1), to: Date())!
        let samples: [HKCategorySample] = try await withCheckedThrowingContinuation { done in
            let query = HKSampleQuery(sampleType: type, predicate: HKQuery.predicateForSamples(withStart: start, end: Date()),
                                      limit: HKObjectQueryNoLimit,
                                      sortDescriptors: [NSSortDescriptor(key: HKSampleSortIdentifierStartDate, ascending: true)]) {
                _, samples, error in
                if let error { done.resume(throwing: error) } else { done.resume(returning: samples as? [HKCategorySample] ?? []) }
            }
            store.execute(query)
        }
        // 夜ごと (= 起きた日) に、 眠っていた時間と床にいた時間を足す
        var nights: [String: (asleep: Double, inBed: Double, from: Date, to: Date)] = [:]
        for sample in samples {
            let night = String(iso(sample.endDate).prefix(10))
            let seconds = sample.endDate.timeIntervalSince(sample.startDate)
            var entry = nights[night] ?? (0, 0, sample.startDate, sample.endDate)
            // (= 2 は「起きていた」。 iOS 16 からの値で、 眠りには数えない)
            if sample.value == HKCategoryValueSleepAnalysis.inBed.rawValue { entry.inBed += seconds }
            else if sample.value != 2 { entry.asleep += seconds }
            entry.from = min(entry.from, sample.startDate)
            entry.to = max(entry.to, sample.endDate)
            nights[night] = entry
        }
        let rows = nights.keys.sorted().map { night -> [String: Any] in
            let entry = nights[night]!
            return ["night": night, "asleep_hours": (entry.asleep / 3600 * 10).rounded() / 10,
                    "in_bed_hours": (entry.inBed / 3600 * 10).rounded() / 10, "from": iso(entry.from), "to": iso(entry.to)]
        }
        return DeviceOutput(["nights": rows])
    }

    private static func write(_ name: String, value: Double?) async throws -> DeviceOutput {
        guard writable.contains(name), let (id, unit, _) = quantities[name] else {
            throw DeviceError("can only write \(writable.joined(separator: ", "))")
        }
        guard let value else { throw DeviceError("value is required") }
        let type = HKQuantityType(id)
        try await ensure(read: [type], share: [type])
        let now = Date()
        try await store.save(HKQuantitySample(type: type, quantity: HKQuantity(unit: unit, doubleValue: value),
                                              start: now, end: now))
        return DeviceOutput(["type": name, "value": value, "unit": unit.unitString, "at": iso(now)])
    }
}
