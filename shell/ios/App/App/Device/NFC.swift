import CoreNFC
import Foundation

/// NFC: iPhone をタグにかざして、 中身 (= 文字や URL) を読む。 iOS の読み取りの画面が前に出る。
///
/// 使うには、 app の署名に NFC の権利 (= com.apple.developer.nfc.readersession.formats) が要る。
enum NFC {
    static let ops: [DeviceOperation] = [
        DeviceOp(DeviceSpec(name: "nfc.read", kind: .read, summary: "read an NFC tag held to the iPhone",
                            timeout: 90, foreground: true)) { _ in
            try requireForeground("Reading a tag")
            guard NFCNDEFReaderSession.readingAvailable else { throw DeviceError("NFC reading is not available") }
            return DeviceOutput(try await TagRead().run())
        },
    ]
}

private final class TagRead: NSObject, NFCNDEFReaderSessionDelegate {
    private var session: NFCNDEFReaderSession?
    private var waiting: CheckedContinuation<[[String: Any]], Error>?
    private var keep: TagRead?

    @MainActor func run() async throws -> [[String: Any]] {
        try await withCheckedThrowingContinuation { done in
            waiting = done
            keep = self
            session = NFCNDEFReaderSession(delegate: self, queue: nil, invalidateAfterFirstRead: true)
            session?.alertMessage = "Hold the iPhone near the tag."
            session?.begin()
        }
    }

    func readerSession(_ session: NFCNDEFReaderSession, didDetectNDEFs messages: [NFCNDEFMessage]) {
        let records = messages.flatMap(\.records).map { record -> [String: Any] in
            var row: [String: Any] = ["type": String(data: record.type, encoding: .utf8) ?? ""]
            if let url = record.wellKnownTypeURIPayload() { row["url"] = url.absoluteString }
            let (text, _) = record.wellKnownTypeTextPayload()
            if let text { row["text"] = text }
            if row["url"] == nil && row["text"] == nil { row["bytes"] = record.payload.base64EncodedString() }
            return row
        }
        waiting?.resume(returning: records)
        waiting = nil
        keep = nil
    }

    func readerSession(_ session: NFCNDEFReaderSession, didInvalidateWithError error: Error) {
        waiting?.resume(throwing: error)
        waiting = nil
        keep = nil
    }
}
