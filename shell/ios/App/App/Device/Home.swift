import Foundation
import HomeKit

/// 家の機器 (= HomeKit): 家・部屋・機器の一覧、 電源の入 / 切、 シーンを動かす。
///
/// 使うには、 app の署名に HomeKit の権利 (= com.apple.developer.homekit) が要る。
enum Home {
    static let ops: [DeviceOperation] = [
        DeviceOp(DeviceSpec(name: "home.list", kind: .read, summary: "homes, rooms, accessories and scenes")) { _ in
            let homes = try await Homes.load()
            return DeviceOutput(homes.map { home -> [String: Any] in
                ["name": home.name,
                 "scenes": home.actionSets.map(\.name),
                 "accessories": home.accessories.map { accessory -> [String: Any] in
                     ["name": accessory.name, "room": accessory.room?.name as Any, "reachable": accessory.isReachable,
                      "power": power(of: accessory).flatMap { $0.value as? Bool } as Any,
                      "kind": accessory.category.localizedDescription]
                 }]
            })
        },
        DeviceOp(DeviceSpec(name: "home.power", kind: .change, summary: "switch an accessory on or off",
                            params: [.string("accessory", "accessory name", required: true),
                                     .bool("on", "true to switch on, false to switch off", required: true)])) { args in
            let name = try args.required("accessory")
            guard let on = args.bool("on") else { throw DeviceError("on is required") }
            let accessory = try await find(name)
            guard let power = power(of: accessory) else { throw DeviceError("\(name) has no power switch") }
            try await power.writeValue(on)
            return DeviceOutput(["accessory": accessory.name, "on": on])
        },
        DeviceOp(DeviceSpec(name: "home.scene", kind: .act, summary: "run a scene",
                            params: [.string("scene", "scene name", required: true)])) { args in
            let name = try args.required("scene")
            for home in try await Homes.load() {
                if let scene = home.actionSets.first(where: { $0.name == name }) {
                    try await home.executeActionSet(scene)
                    return DeviceOutput(["scene": name, "home": home.name])
                }
            }
            throw DeviceError("no scene named \(name)")
        },
    ]

    private static func power(of accessory: HMAccessory) -> HMCharacteristic? {
        accessory.services.flatMap(\.characteristics).first { $0.characteristicType == HMCharacteristicTypePowerState }
    }

    private static func find(_ name: String) async throws -> HMAccessory {
        for home in try await Homes.load() {
            if let accessory = home.accessories.first(where: { $0.name == name }) { return accessory }
        }
        throw DeviceError("no accessory named \(name)")
    }
}

/// 家の一覧を読み終えるまで待つ (= HMHomeManager は作った後に一覧を知らせてくる)。
@MainActor final class Homes: NSObject, HMHomeManagerDelegate {
    private static var shared: Homes?
    private let manager = HMHomeManager()
    private var loaded = false
    private var waiting: [CheckedContinuation<[HMHome], Error>] = []

    /// 家の許可の状態 (= 家の一覧を 1 度読んだ後だけ分かる。 係を作るだけで iOS が許可を訊くので、 ここでは作らない)
    static var authorization: HMHomeManagerAuthorizationStatus? { shared?.manager.authorizationStatus }

    static func load() async throws -> [HMHome] {
        let homes = shared ?? Homes()
        shared = homes
        return try await homes.wait()
    }

    override init() {
        super.init()
        manager.delegate = self
    }

    private func wait() async throws -> [HMHome] {
        if loaded { return manager.homes }
        return try await withCheckedThrowingContinuation { waiting.append($0) }
    }

    nonisolated func homeManagerDidUpdateHomes(_ manager: HMHomeManager) {
        Task { @MainActor in
            self.loaded = true
            let homes = manager.homes
            self.waiting.forEach { $0.resume(returning: homes) }
            self.waiting = []
        }
    }
}
