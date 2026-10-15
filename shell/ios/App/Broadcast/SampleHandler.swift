import CoreImage
import ReplayKit

/// iPhone の画面を、 この Mac の agent が見られるように backend へ送る (= 画面の配信)。
///
/// コントロールセンターの画面収録を長押しして、 この app を選ぶと始まる。 送るのは JPEG を 1 枚ずつで、 間隔・
/// 長辺の上限・質は backend の設定 (= `GET /device/screen/settings`、 既定は backend が持つ) から受け取る。
/// 受け取るまでは送らない。 backend は最後の 1 枚だけを持ち、 Mac で `cpc device screen` が出す。
/// extension の memory は 50MB までなので、 1 枚ずつ送り終えてから次を作る。
final class SampleHandler: RPBroadcastSampleHandler {
    /// 配信の仕方 (= backend から受け取る)
    private struct Settings {
        let interval: CFTimeInterval
        let maxSide: CGFloat
        let quality: CGFloat
    }

    /// 設定を受け取れなかった時に、 次に受け取りに行くまでの間 (秒。 絵は 1 秒に何十枚も来るので、 毎回は行かない)
    private static let retrySeconds: CFTimeInterval = 5

    private let queue = DispatchQueue(label: "screen.upload")
    private let context = CIContext()
    private var settings: Settings?
    private var loading = false
    private var lastTried: CFTimeInterval = 0
    private var lastSent: CFTimeInterval = 0
    private var sending = false

    override func broadcastStarted(withSetupInfo setupInfo: [String: NSObject]?) {
        postState(live: true)
        loadSettings()
    }

    override func broadcastFinished() {
        postState(live: false)
    }

    override func processSampleBuffer(_ sampleBuffer: CMSampleBuffer, with sampleBufferType: RPSampleBufferType) {
        guard sampleBufferType == .video else { return }
        let now = CACurrentMediaTime()
        let due: Settings? = queue.sync {
            guard let settings, !sending, now - lastSent >= settings.interval else { return nil }
            sending = true
            lastSent = now
            return settings
        }
        guard let due else {
            if queue.sync(execute: { settings == nil && !loading && now - lastTried >= Self.retrySeconds }) { loadSettings() }
            return
        }
        guard let jpeg = encode(sampleBuffer, with: due) else { finish(); return }
        upload(jpeg)
    }

    /// 配信の仕方を backend から受け取る (= 届かなければ、 次の絵の時にもう 1 度)。
    private func loadSettings() {
        guard let url = try? ServerAddress.url("/device/screen/settings") else { return }
        queue.sync { loading = true; lastTried = CACurrentMediaTime() }
        URLSession.shared.dataTask(with: url) { [weak self] data, _, _ in
            guard let self else { return }
            let got = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
            self.queue.sync {
                self.loading = false
                if let got, let interval = got["interval_s"] as? Double, let side = got["max_side"] as? Double,
                   let quality = got["quality"] as? Double {
                    self.settings = Settings(interval: interval, maxSide: CGFloat(side), quality: CGFloat(quality))
                }
            }
        }.resume()
    }

    private func encode(_ sampleBuffer: CMSampleBuffer, with settings: Settings) -> Data? {
        guard let pixels = CMSampleBufferGetImageBuffer(sampleBuffer) else { return nil }
        var image = CIImage(cvPixelBuffer: pixels)
        // 横にした時の向き (= ReplayKit が付ける)
        if let raw = CMGetAttachment(sampleBuffer, key: RPVideoSampleOrientationKey as CFString, attachmentModeOut: nil)
            as? NSNumber, let orientation = CGImagePropertyOrientation(rawValue: raw.uint32Value) {
            image = image.oriented(orientation)
        }
        let side = max(image.extent.width, image.extent.height)
        if side > settings.maxSide {
            let scale = settings.maxSide / side
            image = image.transformed(by: CGAffineTransform(scaleX: scale, y: scale))
        }
        guard let space = CGColorSpace(name: CGColorSpace.sRGB) else { return nil }
        let options = [CIImageRepresentationOption(rawValue: kCGImageDestinationLossyCompressionQuality as String): settings.quality]
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
