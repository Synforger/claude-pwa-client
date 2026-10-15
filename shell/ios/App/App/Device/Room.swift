import Foundation
import RoomPlan
import simd
import UIKit

/// 部屋を測る: カメラと LiDAR で部屋を写して回り、 壁・床・ドア・窓・家具の寸法と、 3D の file を返す。
/// 人が iPhone を持って部屋を歩き、 終わったら「Done」 を押す (= LiDAR の付いた iPhone だけ)。
enum Room {
    static var ops: [DeviceOperation] {
        guard #available(iOS 16.0, *) else { return [] }
        return [
            DeviceOp(DeviceSpec(name: "room.scan", kind: .read,
                                summary: "measure a room by walking it with the camera; returns sizes and a 3D file",
                                timeout: 1800, foreground: true)) { _ in
                try requireForeground("Measuring a room")
                guard RoomCaptureSession.isSupported else { throw DeviceError("this iPhone has no LiDAR") }
                guard let front = frontController() else { throw DeviceError("no screen to show the scanner on") }
                let room = try await RoomScan().run(from: front)
                let file = FileManager.default.temporaryDirectory.appendingPathComponent("room-\(UUID().uuidString).usdz")
                try room.export(to: file)
                return DeviceOutput(summary(room),
                                    files: [DeviceFile(name: "room.usdz", mime: "model/vnd.usdz+zip", data: try Data(contentsOf: file))])
            },
        ]
    }

    @available(iOS 16.0, *)
    private static func summary(_ room: CapturedRoom) -> [String: Any] {
        func size(_ dimensions: simd_float3) -> [String: Any] {
            ["width_m": round2(dimensions.x), "height_m": round2(dimensions.y), "depth_m": round2(dimensions.z)]
        }
        return [
            "walls": room.walls.map { size($0.dimensions) },
            "doors": room.doors.map { size($0.dimensions) },
            "windows": room.windows.map { size($0.dimensions) },
            "openings": room.openings.map { size($0.dimensions) },
            "objects": room.objects.map { size($0.dimensions).merging(["kind": "\($0.category)"]) { a, _ in a } },
        ]
    }

    private static func round2(_ value: Float) -> Double { (Double(value) * 100).rounded() / 100 }
}

@available(iOS 16.0, *)
@MainActor private final class RoomScan: UIViewController, RoomCaptureViewDelegate {
    private var waiting: CheckedContinuation<CapturedRoom, Error>?
    private var keep: RoomScan?
    private var capture: RoomCaptureView!

    func run(from front: UIViewController) async throws -> CapturedRoom {
        try await withCheckedThrowingContinuation { done in
            waiting = done
            keep = self
            let navigation = UINavigationController(rootViewController: self)
            navigation.modalPresentationStyle = .fullScreen
            front.present(navigation, animated: true)
        }
    }

    override func viewDidLoad() {
        super.viewDidLoad()
        capture = RoomCaptureView(frame: view.bounds)
        capture.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        capture.delegate = self
        view.addSubview(capture)
        navigationItem.leftBarButtonItem = UIBarButtonItem(systemItem: .cancel, primaryAction: UIAction { [weak self] _ in
            self?.capture.captureSession.stop()
            self?.finish(.failure(DeviceError("the room scan was cancelled")))
        })
        navigationItem.rightBarButtonItem = UIBarButtonItem(systemItem: .done, primaryAction: UIAction { [weak self] _ in
            self?.capture.captureSession.stop()
        })
    }

    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        capture.captureSession.run(configuration: RoomCaptureSession.Configuration())
    }

    private func finish(_ outcome: Result<CapturedRoom, Error>) {
        navigationController?.dismiss(animated: true)
        waiting?.resume(with: outcome)
        waiting = nil
        keep = nil
    }

    nonisolated func captureView(shouldPresent roomDataForProcessing: CapturedRoomData, error: Error?) -> Bool { true }

    nonisolated func captureView(didPresent processedResult: CapturedRoom, error: Error?) {
        Task { @MainActor in
            if let error { self.finish(.failure(error)) } else { self.finish(.success(processedResult)) }
        }
    }
}
