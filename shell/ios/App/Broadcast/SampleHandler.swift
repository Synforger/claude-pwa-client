import CoreImage
import ReplayKit

/// iPhone の画面を、 この Mac の agent が見られるように backend へ送る (= 画面の配信)。
///
/// コントロールセンターの画面収録を長押しして、 この app を選ぶと始まる。 送るのは 1 秒に 1 枚の JPEG
/// (= 長辺を MAX_SIDE までに縮める)。 backend は最後の 1 枚だけを持ち、 Mac で `cpc device screen` が出す。
/// extension の memory は 50MB までなので、 1 枚ずつ送り終えてから次を作る。
final class SampleHandler: RPBroadcastSampleHandler {
    /// 1 枚を送る間隔 (秒)
    private static let interval: CFTimeInterval = 1.0
    /// 長辺の上限 (px)
    private static let maxSide: CGFloat = 1280
    /// JPEG の質 (= 0〜1。 文字が読める所)
    private static let quality: CGFloat = 0.6

    private let queue = DispatchQueue(label: "screen.upload")
    private let context = CIContext()
    private var lastSent: CFTimeInterval = 0
    private var sending = false

    override func broadcastStarted(withSetupInfo setupInfo: [String: NSObject]?) {
        postState(live: true)
    }

    override func broadcastFinished() {
        postState(live: false)
    }

    override func processSampleBuffer(_ sampleBuffer: CMSampleBuffer, with sampleBufferType: RPSampleBufferType) {
        guard sampleBufferType == .video else { return }
        let now = CACurrentMediaTime()
        let due: Bool = queue.sync {
            guard !sending, now - lastSent >= Self.interval else { return false }
            sending = true
            lastSent = now
            return true
        }
        guard due else { return }
        guard let jpeg = encode(sampleBuffer) else { finish(); return }
        upload(jpeg)
    }

    private func encode(_ sampleBuffer: CMSampleBuffer) -> Data? {
        guard let pixels = CMSampleBufferGetImageBuffer(sampleBuffer) else { return nil }
        var image = CIImage(cvPixelBuffer: pixels)
        // 横にした時の向き (= ReplayKit が付ける)
        if let raw = CMGetAttachment(sampleBuffer, key: RPVideoSampleOrientationKey as CFString, attachmentModeOut: nil)
            as? NSNumber, let orientation = CGImagePropertyOrientation(rawValue: raw.uint32Value) {
            image = image.oriented(orientation)
        }
        let side = max(image.extent.width, image.extent.height)
        if side > Self.maxSide {
            let scale = Self.maxSide / side
            image = image.transformed(by: CGAffineTransform(scaleX: scale, y: scale))
        }
        guard let space = CGColorSpace(name: CGColorSpace.sRGB) else { return nil }
        let options = [CIImageRepresentationOption(rawValue: kCGImageDestinationLossyCompressionQuality as String): Self.quality]
        return context.jpegRepresentation(of: image, colorSpace: space, options: options)
    }

    private func upload(_ jpeg: Data) {
        guard let url = try? ServerAddress.url("/device/screen") else { finish(); return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("image/jpeg", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 5
        URLSession.shared.uploadTask(with: request, from: jpeg) { [weak self] _, _, _ in self?.finish() }.resume()
    }

    private func finish() {
        queue.sync { sending = false }
    }

    private func postState(live: Bool) {
        guard let url = try? ServerAddress.url("/device/screen/state") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: ["live": live])
        URLSession.shared.dataTask(with: request).resume()
    }
}
