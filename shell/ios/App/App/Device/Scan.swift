import Foundation
import UIKit
import Vision
import VisionKit

/// 読み取り: 書類をスキャンする、 QR コードやバーコードを読む。 どちらもカメラの画面を出し、 人が iPhone を向ける。
enum Scanning {
    static var ops: [DeviceOperation] {
        var ops: [DeviceOperation] = [
            DeviceOp(DeviceSpec(name: "scan.document", kind: .read,
                                summary: "scan paper with the camera; returns each page as a file and the text on it",
                                timeout: 600, foreground: true)) { _ in
                try requireForeground("Scanning a document")
                guard VNDocumentCameraViewController.isSupported else { throw DeviceError("document scanning is not supported") }
                guard let front = frontController() else { throw DeviceError("no screen to show the scanner on") }
                let pages = try await DocumentScan().run(from: front)
                var texts: [String] = []
                var files: [DeviceFile] = []
                for (index, page) in pages.enumerated() {
                    texts.append(try await read(page).joined(separator: "\n"))
                    if let jpeg = page.jpegData(compressionQuality: 0.85) {
                        files.append(DeviceFile(name: "page-\(index + 1).jpg", mime: "image/jpeg", data: jpeg))
                    }
                }
                return DeviceOutput(["pages": pages.count, "text": texts], files: files)
            },
        ]
        if #available(iOS 16.0, *) { ops += codes }
        return ops
    }

    @available(iOS 16.0, *)
    private static let codes: [DeviceOperation] = [
        DeviceOp(DeviceSpec(name: "scan.code", kind: .read, summary: "read a QR code or barcode held to the camera",
                            timeout: 300, foreground: true)) { _ in
            try requireForeground("Reading a code")
            guard DataScannerViewController.isSupported, DataScannerViewController.isAvailable else {
                throw DeviceError("code scanning is not available (it needs camera access and a newer iPhone)")
            }
            guard let front = frontController() else { throw DeviceError("no screen to show the scanner on") }
            let found = try await CodeScan().run(from: front)
            return DeviceOutput(["code": found.payload, "type": found.symbology])
        },
    ]

    private static func read(_ page: UIImage) async throws -> [String] {
        guard let cg = page.cgImage else { return [] }
        return try await withCheckedThrowingContinuation { done in
            DispatchQueue.global(qos: .userInitiated).async {
                let request = VNRecognizeTextRequest { request, error in
                    if let error { done.resume(throwing: error); return }
                    done.resume(returning: (request.results as? [VNRecognizedTextObservation] ?? [])
                        .compactMap { $0.topCandidates(1).first?.string })
                }
                request.recognitionLanguages = ["ja-JP", "en-US"]
                request.recognitionLevel = .accurate
                do { try VNImageRequestHandler(cgImage: cg, orientation: .up).perform([request]) } catch { done.resume(throwing: error) }
            }
        }
    }
}

@MainActor private final class DocumentScan: NSObject, VNDocumentCameraViewControllerDelegate {
    private var waiting: CheckedContinuation<[UIImage], Error>?
    private var keep: DocumentScan?

    func run(from front: UIViewController) async throws -> [UIImage] {
        try await withCheckedThrowingContinuation { done in
            waiting = done
            keep = self
            let scanner = VNDocumentCameraViewController()
            scanner.delegate = self
            front.present(scanner, animated: true)
        }
    }

    private func finish(_ scanner: VNDocumentCameraViewController, _ outcome: Result<[UIImage], Error>) {
        scanner.dismiss(animated: true)
        waiting?.resume(with: outcome)
        waiting = nil
        keep = nil
    }

    nonisolated func documentCameraViewController(_ controller: VNDocumentCameraViewController,
                                                  didFinishWith scan: VNDocumentCameraScan) {
        let pages = (0..<scan.pageCount).map { scan.imageOfPage(at: $0) }
        Task { @MainActor in self.finish(controller, .success(pages)) }
    }

    nonisolated func documentCameraViewControllerDidCancel(_ controller: VNDocumentCameraViewController) {
        Task { @MainActor in self.finish(controller, .failure(DeviceError("the scanner was closed without a scan"))) }
    }

    nonisolated func documentCameraViewController(_ controller: VNDocumentCameraViewController, didFailWithError error: Error) {
        Task { @MainActor in self.finish(controller, .failure(error)) }
    }
}

@available(iOS 16.0, *)
@MainActor private final class CodeScan: NSObject, DataScannerViewControllerDelegate {
    struct Found { let payload: String; let symbology: String }
    private var waiting: CheckedContinuation<Found, Error>?
    private var keep: CodeScan?
    private var scanner: DataScannerViewController?

    func run(from front: UIViewController) async throws -> Found {
        try await withCheckedThrowingContinuation { done in
            waiting = done
            keep = self
            let scanner = DataScannerViewController(recognizedDataTypes: [.barcode()], isHighlightingEnabled: true)
            scanner.delegate = self
            self.scanner = scanner
            // (= 閉じる手段。 読まずにやめる時に押す)
            scanner.navigationItem.leftBarButtonItem = UIBarButtonItem(systemItem: .cancel, primaryAction: UIAction { [weak self] _ in
                self?.finish(.failure(DeviceError("the scanner was closed without a code")))
            })
            let navigation = UINavigationController(rootViewController: scanner)
            // (= 払って閉じると答えが返らないので、 閉じるのは Cancel と読めた時だけ)
            navigation.isModalInPresentation = true
            front.present(navigation, animated: true) {
                try? scanner.startScanning()
            }
        }
    }

    private func finish(_ outcome: Result<Found, Error>) {
        scanner?.stopScanning()
        scanner?.navigationController?.dismiss(animated: true)
        waiting?.resume(with: outcome)
        waiting = nil
        keep = nil
    }

    nonisolated func dataScanner(_ dataScanner: DataScannerViewController, didAdd addedItems: [RecognizedItem],
                                 allItems: [RecognizedItem]) {
        for item in addedItems {
            if case .barcode(let code) = item, let payload = code.payloadStringValue {
                let kind = code.observation.symbology.rawValue
                Task { @MainActor in self.finish(.success(Found(payload: payload, symbology: kind))) }
                return
            }
        }
    }
}
