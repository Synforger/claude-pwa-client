import CoreBluetooth
import Foundation

/// Bluetooth: 周りの Bluetooth の機器を数秒探して、 名前と電波の強さを並べる。
enum Bluetooth {
    static let ops: [DeviceOperation] = [
        DeviceOp(DeviceSpec(name: "bluetooth.scan", kind: .read, summary: "nearby Bluetooth devices",
                            params: [.int("seconds", "how long to listen (default 5)")], timeout: 60)) { args in
            let found = try await Scan().run(seconds: Double(min(max(args.int("seconds") ?? 5, 1), 30)))
            return DeviceOutput(found)
        },
    ]
}

@MainActor private final class Scan: NSObject, CBCentralManagerDelegate {
    private var manager: CBCentralManager?
    private var seen: [UUID: [String: Any]] = [:]
    private var ready: CheckedContinuation<Void, Error>?
    private var keep: Scan?

    func run(seconds: Double) async throws -> [[String: Any]] {
        keep = self
        defer { manager?.stopScan(); keep = nil }
        try await withCheckedThrowingContinuation { (done: CheckedContinuation<Void, Error>) in
            ready = done
            manager = CBCentralManager(delegate: self, queue: .main)
        }
        manager?.scanForPeripherals(withServices: nil, options: [CBCentralManagerScanOptionAllowDuplicatesKey: false])
        try await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000))
        return seen.values.sorted { ($0["rssi"] as? Int ?? -999) > ($1["rssi"] as? Int ?? -999) }
    }

    nonisolated func centralManagerDidUpdateState(_ central: CBCentralManager) {
        let state = central.state
        Task { @MainActor in
            switch state {
            case .poweredOn: self.ready?.resume()
            case .unauthorized: self.ready?.resume(throwing: DeviceError("Bluetooth access is not allowed"))
            case .poweredOff: self.ready?.resume(throwing: DeviceError("Bluetooth is off"))
            case .unsupported: self.ready?.resume(throwing: DeviceError("Bluetooth is not supported"))
            default: return
            }
            self.ready = nil
        }
    }

    nonisolated func centralManager(_ central: CBCentralManager, didDiscover peripheral: CBPeripheral,
                                    advertisementData: [String: Any], rssi RSSI: NSNumber) {
        let id = peripheral.identifier
        let name = peripheral.name ?? advertisementData[CBAdvertisementDataLocalNameKey] as? String
        let rssi = RSSI.intValue
        Task { @MainActor in
            self.seen[id] = ["id": id.uuidString, "name": name as Any, "rssi": rssi]
        }
    }
}
