import Foundation
import Photos
import UIKit
import Vision

/// 写真の中身: iPhone の写真ライブラリの写真を並べ、 写っている文字と物を読み、 それで探し、 1 枚を Mac へ渡す。
///
/// 写真そのものの整理 (= アルバム分け・消す) は、 iCloud で同期された Mac の写真で行う (= この app では持たない)。
/// 文字と物は iPhone の中で読む (= Vision。 文字は日本語と英語、 物は Vision の分類の名前 = 英語)。
enum PhotoText {
    static let ops: [DeviceOperation] = [
        DeviceOp(DeviceSpec(name: "photos.recent", kind: .read, summary: "the newest photos (id, date, place)",
                            params: [.int("count", "how many (default 20)")])) { args in
            try await allow()
            return DeviceOutput(newest(args.int("count") ?? 20).map(row))
        },
        DeviceOp(DeviceSpec(name: "photos.text", kind: .read, summary: "the text written in a photo",
                            params: [.string("id", "photo id from photos.recent (default: the newest photo)")],
                            timeout: 60)) { args in
            try await allow()
            let asset = try pick(args.string("id"))
            return DeviceOutput(["photo": row(asset), "text": try await read(asset)])
        },
        DeviceOp(DeviceSpec(name: "photos.find_text", kind: .read, summary: "photos whose text contains a word",
                            params: [.string("query", "the word to look for", required: true),
                                     .int("count", "how many of the newest photos to look through (default 50)")],
                            timeout: 300)) { args in
            try await allow()
            let query = try args.required("query").lowercased()
            var hits: [[String: Any]] = []
            for asset in newest(min(args.int("count") ?? 50, 500)) {
                let lines = try await read(asset)
                if lines.contains(where: { $0.lowercased().contains(query) }) {
                    hits.append(["photo": row(asset), "text": lines])
                }
            }
            return DeviceOutput(hits)
        },
        DeviceOp(DeviceSpec(name: "photos.labels", kind: .read, summary: "what is in a photo (Vision's labels, in English)",
                            params: [.string("id", "photo id from photos.recent (default: the newest photo)")],
                            timeout: 60)) { args in
            try await allow()
            let asset = try pick(args.string("id"))
            return DeviceOutput(["photo": row(asset), "labels": try await labels(asset)])
        },
        DeviceOp(DeviceSpec(name: "photos.find", kind: .read, summary: "photos showing something (matched against Vision's labels)",
                            params: [.string("query", "what to look for, in English (e.g. dog, receipt, beach)", required: true),
                                     .int("count", "how many of the newest photos to look through (default 50)")],
                            timeout: 300)) { args in
            try await allow()
            let query = try args.required("query").lowercased()
            var hits: [[String: Any]] = []
            for asset in newest(min(args.int("count") ?? 50, 500)) {
                let found = try await labels(asset).filter { ($0["label"] as? String ?? "").contains(query) }
                if !found.isEmpty { hits.append(["photo": row(asset), "labels": found]) }
            }
            return DeviceOutput(hits)
        },
        DeviceOp(DeviceSpec(name: "photos.get", kind: .read, summary: "one photo as a file on the Mac",
                            params: [.string("id", "photo id from photos.recent (default: the newest photo)"),
                                     .int("size", "longest side in pixels (default 2048)")], timeout: 60)) { args in
            try await allow()
            let asset = try pick(args.string("id"))
            let image = try await picture(asset, side: CGFloat(args.int("size") ?? 2048))
            guard let jpeg = image.jpegData(compressionQuality: 0.85) else { throw DeviceError("could not encode the photo") }
            return DeviceOutput(row(asset), files: [DeviceFile(name: "photo.jpg", mime: "image/jpeg", data: jpeg)])
        },
    ]

    private static func allow() async throws {
        let status = await PHPhotoLibrary.requestAuthorization(for: .readWrite)
        guard status == .authorized || status == .limited else {
            throw DeviceError("photo access is not allowed (Settings → Privacy → Photos)")
        }
    }

    private static func newest(_ count: Int) -> [PHAsset] {
        let options = PHFetchOptions()
        options.sortDescriptors = [NSSortDescriptor(key: "creationDate", ascending: false)]
        options.fetchLimit = max(count, 1)
        let found = PHAsset.fetchAssets(with: .image, options: options)
        return (0..<found.count).map { found.object(at: $0) }
    }

    private static func pick(_ id: String?) throws -> PHAsset {
        if let id {
            guard let asset = PHAsset.fetchAssets(withLocalIdentifiers: [id], options: nil).firstObject else {
                throw DeviceError("no photo with id \(id)")
            }
            return asset
        }
        guard let asset = newest(1).first else { throw DeviceError("there are no photos") }
        return asset
    }

    private static func row(_ asset: PHAsset) -> [String: Any] {
        var row: [String: Any] = ["id": asset.localIdentifier, "width": asset.pixelWidth, "height": asset.pixelHeight,
                                  "favorite": asset.isFavorite]
        if let date = asset.creationDate { row["date"] = iso(date) }
        if let place = asset.location?.coordinate { row["latitude"] = place.latitude; row["longitude"] = place.longitude }
        return row
    }

    private static func picture(_ asset: PHAsset, side: CGFloat) async throws -> UIImage {
        let options = PHImageRequestOptions()
        options.deliveryMode = .highQualityFormat
        options.isNetworkAccessAllowed = true   // (= iCloud にだけ在る写真も取りに行く)
        return try await withCheckedThrowingContinuation { done in
            PHImageManager.default().requestImage(for: asset, targetSize: CGSize(width: side, height: side),
                                                  contentMode: .aspectFit, options: options) { image, info in
                if let image { done.resume(returning: image) } else {
                    done.resume(throwing: (info?[PHImageErrorKey] as? Error) ?? DeviceError("could not load the photo"))
                }
            }
        }
    }

    /// 写っている物の名前に入れる確からしさの下限 (= これ以上の物を、 高い順に返す)
    private static let labelMin: Float = 0.3

    private static func labels(_ asset: PHAsset) async throws -> [[String: Any]] {
        let image = try await picture(asset, side: 1024)
        guard let cg = image.cgImage else { return [] }
        return try await withCheckedThrowingContinuation { done in
            DispatchQueue.global(qos: .userInitiated).async {
                let request = VNClassifyImageRequest()
                do {
                    try VNImageRequestHandler(cgImage: cg, orientation: .up).perform([request])
                    let found = (request.results ?? []).filter { $0.confidence >= labelMin }
                        .sorted { $0.confidence > $1.confidence }
                        .map { ["label": $0.identifier, "confidence": Double(($0.confidence * 100).rounded() / 100)] as [String: Any] }
                    done.resume(returning: found)
                } catch {
                    done.resume(throwing: error)
                }
            }
        }
    }

    private static func read(_ asset: PHAsset) async throws -> [String] {
        let image = try await picture(asset, side: 2048)
        guard let cg = image.cgImage else { return [] }
        // (= 1 枚に 1 秒ほど掛かるので、 画面の流れから外して読む。 頼みもその流れの中で作る)
        return try await withCheckedThrowingContinuation { done in
            DispatchQueue.global(qos: .userInitiated).async {
                let request = VNRecognizeTextRequest { request, error in
                    if let error { done.resume(throwing: error); return }
                    let lines = (request.results as? [VNRecognizedTextObservation] ?? [])
                        .compactMap { $0.topCandidates(1).first?.string }
                    done.resume(returning: lines)
                }
                request.recognitionLanguages = ["ja-JP", "en-US"]
                request.recognitionLevel = .accurate
                do {
                    try VNImageRequestHandler(cgImage: cg, orientation: .up).perform([request])
                } catch {
                    done.resume(throwing: error)
                }
            }
        }
    }
}
