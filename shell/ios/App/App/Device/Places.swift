import CoreLocation
import Foundation
import MapKit

/// 地図: 場所を探す、 2 つの場所の間の経路と所要時間。 iPhone の地図 (= Apple Maps) の検索を使う。
enum Places {
    /// 緯度と経度を渡された時に探す広さの既定 (m。 頼みの `meters` で変えられる)
    private static let searchMeters: Double = 5_000

    static let ops: [DeviceOperation] = [
        DeviceOp(DeviceSpec(name: "maps.search", kind: .read, summary: "places matching words (shops, stations, addresses)",
                            params: [.string("query", "what to look for", required: true),
                                     .number("latitude", "look around here (default: near the iPhone's map region)"),
                                     .number("longitude", "look around here"),
                                     .number("meters", "how far around latitude / longitude to look (default 5000)"),
                                     .int("count", "how many (default 10)")])) { args in
            let found = try await search(try args.required("query"), near: point(args), meters: args.number("meters") ?? searchMeters)
            return DeviceOutput(found.prefix(args.int("count") ?? 10).map(row))
        },
        DeviceOp(DeviceSpec(name: "maps.route", kind: .read, summary: "the route and travel time between two places",
                            params: [.string("to", "where to go (name or address)", required: true),
                                     .string("from", "where to start (default: where the iPhone is)"),
                                     .string("mode", "driving, walking or transit (default driving)")],
                            timeout: 60)) { args in
            let request = MKDirections.Request()
            request.destination = try await place(try args.required("to"))
            if let from = args.string("from") {
                request.source = try await place(from)
            } else {
                request.source = MKMapItem.forCurrentLocation()
            }
            switch args.string("mode") ?? "driving" {
            case "driving": request.transportType = .automobile
            case "walking": request.transportType = .walking
            case "transit": request.transportType = .transit
            default: throw DeviceError("mode is one of driving, walking, transit")
            }
            let directions = MKDirections(request: request)
            if request.transportType == .transit {
                // (= 電車やバスの道順そのものは出せない。 所要時間と着く時刻だけ)
                let eta = try await directions.calculateETA()
                return DeviceOutput(["minutes": Int(eta.expectedTravelTime / 60), "arrival": iso(eta.expectedArrivalDate),
                                     "departure": iso(eta.expectedDepartureDate), "meters": Int(eta.distance)])
            }
            guard let route = try await directions.calculate().routes.first else { throw DeviceError("no route found") }
            return DeviceOutput(["minutes": Int(route.expectedTravelTime / 60), "meters": Int(route.distance),
                                 "name": route.name, "steps": route.steps.map(\.instructions).filter { !$0.isEmpty }])
        },
    ]

    private static func point(_ args: DeviceArgs) -> CLLocationCoordinate2D? {
        guard let latitude = args.number("latitude"), let longitude = args.number("longitude") else { return nil }
        return CLLocationCoordinate2D(latitude: latitude, longitude: longitude)
    }

    private static func search(_ query: String, near: CLLocationCoordinate2D?, meters: Double = searchMeters) async throws -> [MKMapItem] {
        let request = MKLocalSearch.Request()
        request.naturalLanguageQuery = query
        if let near { request.region = MKCoordinateRegion(center: near, latitudinalMeters: meters, longitudinalMeters: meters) }
        return try await MKLocalSearch(request: request).start().mapItems
    }

    private static func place(_ query: String) async throws -> MKMapItem {
        guard let first = try await search(query, near: nil).first else { throw DeviceError("no place matches \(query)") }
        return first
    }

    private static func row(_ item: MKMapItem) -> [String: Any] {
        let mark = item.placemark
        return ["name": item.name as Any, "address": [mark.postalCode, mark.administrativeArea, mark.locality,
                                                      mark.thoroughfare, mark.subThoroughfare]
                    .compactMap { $0 }.joined(separator: " "),
                "latitude": mark.coordinate.latitude, "longitude": mark.coordinate.longitude,
                "phone": item.phoneNumber as Any, "url": item.url?.absoluteString as Any]
    }
}
