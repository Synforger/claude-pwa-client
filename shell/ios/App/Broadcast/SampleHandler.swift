import CoreImage
import ReplayKit

/// iPhone の画面を、 この Mac の agent が見られるように backend へ送る (= 画面の配信)。
///
/// コントロールセンターの画面収録を長押しして、 この app を選ぶと始まる。 送るのは JPEG を 1 枚ずつで、 間隔・
/// 長辺の上限・質は backend の設定 (= `GET /device/screen/settings`、 既定は backend が持つ) から受け取る。
/// 受け取るまでは送らない。 backend は最後の 1 枚だけを持ち、 Mac で `cpc device screen` が出す。
/// extension の memory は 50MB までなので、 1 枚ずつ送り終えてから次を作り、 1 枚ごとに絵の途中の控えを捨てる。
///
/// 画面が動かない間、 iOS は絵を渡さない。 その間も配信中と分かるよう、 送る間隔ごとに「生きている」 と知らせる。
/// 始まり・終わり・止まった理由と、 何枚目でどれだけ memory を使っているかは、 backend の記録 (= `/log/sw` の
/// `screen:…`) へ送る (= 配信が途中で止まった時に、 落とされたのか止められたのかを分けるため)。
final class SampleHandler: RPBroadcastSampleHandler {
    /// 配信の仕方 (= backend から受け取る)
    private struct Settings {
        let interval: CFTimeInterval
        let maxSide: CGFloat
        let quality: CGFloat
    }

    /// 設定を受け取れなかった時に、 次に受け取りに行くまでの間 (秒。 絵は 1 秒に何十枚も来るので、 毎回は行かない)
    private static let retrySeconds: CFTimeInterval = 5

    /// 記録へ毎枚送る枚数と、 その後に送る間隔 (= 始めの数枚で memory の増え方が見え、 後は時々で足りる)
    private static let reportEachFirst = 10
    private static let reportEvery = 60

    private let queue = DispatchQueue(label: "screen.upload")
    /// 絵を作る道具 (= 途中の控えを持たない。 50MB の内に収めるため)
    private let context = CIContext(options: [.cacheIntermediates: false])
    private var frames = 0
    private var heartbeat: DispatchSourceTimer?
    private var settings: Settings?
    private var loading = false
    private var lastTried: CFTimeInterval = 0
    private var lastSent: CFTimeInterval = 0
    private var sending = false

    override func broadcastStarted(withSetupInfo setupInfo: [String: NSObject]?) {
        report("start", [:])
        postState(live: true)
        loadSettings()
    }

    override func broadcastPaused() {
        report("paused", [:])
    }

    override func broadcastResumed() {
        report("resumed", [:])
    }

    override func broadcastFinished() {
        report("finish", ["frames": queue.sync { frames }])
        queue.sync { heartbeat?.cancel(); heartbeat = nil }
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
        let jpeg: Data? = autoreleasepool { encode(sampleBuffer, with: due) }
        context.clearCaches()
        guard let jpeg else {
            report("encode-failed", [:])
            finish()
            return
        }
        let count: Int = queue.sync { frames += 1; return frames }
        if count <= Self.reportEachFirst || count % Self.reportEvery == 0 {
            report("frame", ["n": count, "bytes": jpeg.count])
        }
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
                    self.startHeartbeat(every: interval)
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
        URLSession.shared.uploadTask(with: request, from: jpeg) { [weak self] _, response, error in
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            if error != nil || code != 200 {
                self?.report("upload-failed", ["status": code, "error": error.map { "\($0)" } ?? ""])
            }
            self?.finish()
        }.resume()
    }

    /// 送る間隔ごとに「生きている」 と知らせる (= queue の上で。 設定を受け取った時に 1 度だけ始める)
    private func startHeartbeat(every interval: CFTimeInterval) {
        guard heartbeat == nil else { return }
        let timer = DispatchSource.makeTimerSource(queue: queue)
        timer.schedule(deadline: .now() + interval, repeating: interval)
        timer.setEventHandler { [weak self] in self?.postState(live: true) }
        timer.resume()
        heartbeat = timer
    }

    /// backend の記録へ 1 行 (= `screen:<stage>`。 その時の memory の使用量を添える)
    private func report(_ stage: String, _ detail: [String: Any]) {
        guard let url = try? ServerAddress.url("/log/sw") else { return }
        var body: [String: Any] = ["stage": "screen:\(stage)", "footprint_mb": Self.footprintMB()]
        body.merge(detail) { _, new in new }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: body)
        URLSession.shared.dataTask(with: request).resume()
    }

    /// この extension が今使っている memory (MB。 iOS が 50MB の上限と比べる値)
    private static func footprintMB() -> Double {
        var info = task_vm_info_data_t()
        var count = mach_msg_type_number_t(MemoryLayout<task_vm_info_data_t>.size / MemoryLayout<integer_t>.size)
        let result = withUnsafeMutablePointer(to: &info) {
            $0.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
                task_info(mach_task_self_, task_flavor_t(TASK_VM_INFO), $0, &count)
            }
        }
        guard result == KERN_SUCCESS else { return -1 }
        return (Double(info.phys_footprint) / 1_048_576 * 10).rounded() / 10
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
