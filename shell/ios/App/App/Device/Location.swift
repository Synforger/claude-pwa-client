import CoreLocation
import Foundation

/// 位置: 今どこに居るか (= 座標と、 住所に直した物)。
enum Location {
    static let ops: [DeviceOperation] = [
        DeviceOp(DeviceSpec(name: "location.now", kind: .read, summary: "where the iPhone is now, with the address",
                            timeout: 30)) { _ in
            let place = try await OneFix().locate()
            var value: [String: Any] = ["latitude": place.coordinate.latitude, "longitude": place.coordinate.longitude,
                                        "accuracy_m": place.horizontalAccuracy, "altitude_m": place.altitude,
                                        "at": iso(place.timestamp)]
            if let mark = try? await CLGeocoder().reverseGeocodeLocation(place).first {
                value["address"] = [mark.administrativeArea, mark.locality, mark.subLocality, mark.thoroughfare,
                                    mark.subThoroughfare].compactMap { $0 }.joined(separator: " ")
                value["name"] = mark.name
            }
            return DeviceOutput(value)
        },
    ]
}

/// 位置を 1 回だけ取る (= 許可がまだなら頼んでから)。
@MainActor private final class OneFix: NSObject, CLLocationManagerDelegate {
    private let manager = CLLocationManager()
    private var waiting: CheckedContinuation<CLLocation, Error>?
    private var keep: OneFix?

    func locate() async throws -> CLLocation {
        try await withCheckedThrowingContinuation { done in
            waiting = done
            keep = self   // (= 答えるまで自分を持つ)
            manager.delegate = self
            manager.desiredAccuracy = kCLLocationAccuracyBest
            if manager.authorizationStatus == .notDetermined {
                manager.requestWhenInUseAuthorization()
            } else {
                begin()
            }
        }
    }

    private func begin() {
        switch manager.authorizationStatus {
        case .authorizedAlways, .authorizedWhenInUse: manager.requestLocation()
        case .notDetermined: break
        default: finish(.failure(DeviceError("location access is not allowed (Settings → Privacy → Location Services)")))
        }
    }

    private func finish(_ outcome: Result<CLLocation, Error>) {
        waiting?.resume(with: outcome)
        waiting = nil
        keep = nil
    }

    nonisolated func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        Task { @MainActor in self.begin() }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let last = locations.last else { return }
        Task { @MainActor in self.finish(.success(last)) }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        Task { @MainActor in self.finish(.failure(error)) }
    }
}
