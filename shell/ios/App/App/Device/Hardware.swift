import AVFoundation
import CoreHaptics
import Foundation
import Network
import NetworkExtension
import UIKit

/// iPhone の体: 振動、 ライト、 画面の明るさ、 電池や空き容量などの状態、 つながっている回線。
enum Hardware {
    static let ops: [DeviceOperation] = [
        DeviceOp(DeviceSpec(name: "device.status", kind: .read,
                            summary: "battery, charging, low power mode, heat, free storage, model, iOS version, volume and brightness")) { _ in
            let device = UIDevice.current
            device.isBatteryMonitoringEnabled = true
            defer { device.isBatteryMonitoringEnabled = false }
            var out: [String: Any] = [
                "name": device.name, "model": modelCode(), "system": "\(device.systemName) \(device.systemVersion)",
                "battery": device.batteryLevel < 0 ? NSNull() : Double((device.batteryLevel * 100).rounded()) / 100,
                "charging": [.charging, .full].contains(device.batteryState),
                "low_power": ProcessInfo.processInfo.isLowPowerModeEnabled,
                "heat": ["nominal", "fair", "serious", "critical"][ProcessInfo.processInfo.thermalState.rawValue],
                "volume": Double((AVAudioSession.sharedInstance().outputVolume * 100).rounded()) / 100,
            ]
            if let screen = activeScreen() { out["brightness"] = Double((screen.brightness * 100).rounded()) / 100 }
            if let free = try? URL(fileURLWithPath: NSHomeDirectory())
                .resourceValues(forKeys: [.volumeAvailableCapacityForImportantUsageKey, .volumeTotalCapacityKey]) {
                out["storage_free_gb"] = free.volumeAvailableCapacityForImportantUsage.map { Double($0 / 100_000_000) / 10 } as Any
                out["storage_total_gb"] = free.volumeTotalCapacity.map { Double($0 / 100_000_000) / 10 } as Any
            }
            return DeviceOutput(out)
        },
        DeviceOp(DeviceSpec(name: "network.status", kind: .read,
                            summary: "how the iPhone is connected (wifi, cellular, none) and the Wi-Fi name when it can be read")) { _ in
            var out = await pathNow()
            // (= Wi-Fi の名前は、 その権利と位置の許可がある時だけ読める。 無ければ入れない)
            if let wifi = await NEHotspotNetwork.fetchCurrent() { out["wifi_name"] = wifi.ssid }
            return DeviceOutput(out)
        },
        DeviceOp(DeviceSpec(name: "haptic.play", kind: .act, summary: "vibrate the iPhone",
                            params: [.string("pattern", "tap, success, warning, error or long (default tap)")],
                            foreground: true)) { args in
            try requireForeground("Vibrating")
            try play(args.string("pattern") ?? "tap")
            return DeviceOutput(["played": args.string("pattern") ?? "tap"])
        },
        DeviceOp(DeviceSpec(name: "torch.set", kind: .change, summary: "turn the flashlight on or off",
                            params: [.bool("on", "on or off", required: true),
                                     .number("level", "brightness from 0 to 1 when on (default 1)")])) { args in
            guard let on = args.bool("on") else { throw DeviceError("on (true or false) is required") }
            guard let camera = AVCaptureDevice.default(for: .video), camera.hasTorch else { throw DeviceError("no flashlight") }
            try camera.lockForConfiguration()
            defer { camera.unlockForConfiguration() }
            if on {
                try camera.setTorchModeOn(level: Float(min(max(args.number("level") ?? 1, 0.01), 1)))
            } else {
                camera.torchMode = .off
            }
            return DeviceOutput(["on": on])
        },
        DeviceOp(DeviceSpec(name: "screen.brightness", kind: .change, summary: "set the screen brightness",
                            params: [.number("level", "from 0 to 1", required: true)], foreground: true)) { args in
            try requireForeground("Changing the brightness")
            guard let level = args.number("level") else { throw DeviceError("level is required") }
            guard let screen = activeScreen() else { throw DeviceError("no screen") }
            screen.brightness = CGFloat(min(max(level, 0), 1))
            return DeviceOutput(["brightness": Double(screen.brightness)])
        },
    ]

    /// 機種の名前 (= 例 iPhone17,1。 UIDevice.model は "iPhone" しか返さない)
    private static func modelCode() -> String {
        var info = utsname()
        uname(&info)
        return withUnsafeBytes(of: &info.machine) { raw in
            String(decoding: raw.prefix { $0 != 0 }, as: UTF8.self)
        }
    }

    @MainActor private static func activeScreen() -> UIScreen? {
        UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first?.screen
    }

    private static func pathNow() async -> [String: Any] {
        await withCheckedContinuation { done in
            let monitor = NWPathMonitor()
            monitor.pathUpdateHandler = { path in
                monitor.cancel()
                let kind = path.status != .satisfied ? "none"
                    : path.usesInterfaceType(.wifi) ? "wifi"
                    : path.usesInterfaceType(.cellular) ? "cellular"
                    : path.usesInterfaceType(.wiredEthernet) ? "wired" : "other"
                done.resume(returning: ["connection": kind, "expensive": path.isExpensive, "constrained": path.isConstrained])
            }
            monitor.start(queue: DispatchQueue(label: "network.status"))
        }
    }

    @MainActor private static func play(_ pattern: String) throws {
        switch pattern {
        case "tap": UIImpactFeedbackGenerator(style: .medium).impactOccurred()
        case "success": UINotificationFeedbackGenerator().notificationOccurred(.success)
        case "warning": UINotificationFeedbackGenerator().notificationOccurred(.warning)
        case "error": UINotificationFeedbackGenerator().notificationOccurred(.error)
        case "long":
            guard CHHapticEngine.capabilitiesForHardware().supportsHaptics else { throw DeviceError("no haptics") }
            let engine = try CHHapticEngine()
            try engine.start()
            let event = CHHapticEvent(eventType: .hapticContinuous, parameters: [
                CHHapticEventParameter(parameterID: .hapticIntensity, value: 1),
            ], relativeTime: 0, duration: 1)
            try engine.makePlayer(with: try CHHapticPattern(events: [event], parameters: [])).start(atTime: 0)
            // (= 鳴り終わるまで engine を持っておく)
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { engine.stop() }
        default:
            throw DeviceError("pattern is one of tap, success, warning, error, long")
        }
    }
}
