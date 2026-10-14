import AVFoundation
import AVKit
import Capacitor
import CoreMedia
import PipecatClientIOS
import UIKit

/// 通話の間、 app を抜けたら PiP の小窓に会話を出す (= 吹き出しの小さなチャット。 上の帯に今の状態)。
///
/// 小窓は「絵を流し込む PiP」 (= `AVSampleBufferDisplayLayer`) で出す。 通話の PiP
/// (= `AVPictureInPictureVideoCallViewController`) は iOS 16 から閉じる・戻るのボタンを描かず、 小窓を消すには app を
/// 落とすしかなかった。 こちらは iOS が両方のボタンを付ける。 中身は終わりの無い生の映像として伝え (= 再生の範囲を
/// 無限)、 小窓を閉じても通話は続く。 ただし再生の範囲は「とても長い録画の途中」 として伝える (= 生の映像だと、 iOS は
/// 送りのボタンを効かなくする)。 小窓を閉じたら仕組みを作り直す (= 一度閉じた仕組みは、 次に抜けても自動で出ない)。
///
/// iOS が付ける再生の操作は読み替える: 再生 / 停止 = マイクの入 / 切 (= 入っている間が「再生中」。 ただし app を抜ける
/// 瞬間だけは「再生中」 と伝える。 一時停止中だと、 iOS は小窓を自動で出さない)、 10 秒戻し / 送り =
/// 会話を上 (= 古い方) / 下 (= 新しい方) へ窓の 3 分の 2 ずつ送る。 上へ送って読んでいる間に新しい行が来ても位置は
/// そのままで、 帯に「▼ 新しい行」 と出す (= 一番下まで戻すと、 また新しい行に付いていく)。
///
/// 文と状態は backend の会話が送る (= `backend/voice_call/agent.py` の小窓)。 変わる度に吹き出しを絵に描いて流し込む。
/// 流し込む先の層は、 画面の隅に 1 pt で置く (= PiP は画面に載っている層からしか始められない)。
@MainActor final class CallPicture: NSObject {
    /// 描く大きさ (pt)。 小窓は iOS がこの縦横比のまま縮めて出す
    private static let canvas = CGSize(width: 300, height: 400)
    /// 覚えておく吹き出しの数 (= 窓に入らない古い物は描かれない。 これは覚えすぎないための上限)
    private static let keptLines = 40
    /// 文が変わらない間も絵を流し込む間隔 (= 流れが止まった層を、 PiP が古い物と見なさないように)
    private static let refreshSecs = 2.0

    private var layer = AVSampleBufferDisplayLayer()
    /// 閉じた後に作り直した時の、 前の仕組み (= すぐ捨てると、 閉じる途中の仕組みが落ちる。 通話の終わりで捨てる)
    private var retired: [AVPictureInPictureController] = []
    /// 小窓を閉じてから作り直すまで待つ間 (= 閉じる動きが終わるのを待つ)
    private static let rearmDelay: UInt64 = 600_000_000
    private let host = UIView(frame: CGRect(x: 0, y: 0, width: 1, height: 1))
    private var controller: AVPictureInPictureController?
    private var lines: [(who: String, text: String)] = []
    private var state = "waiting"
    private var timer: Timer?
    /// マイクが入っているか (= 再生 / 停止の絵と帯。 iOS は main actor の外から読む)
    nonisolated(unsafe) private var micOn = false
    /// app を抜けようとしている間か (= この間は「再生中」 と伝え、 小窓を自動で出させる)
    nonisolated(unsafe) private var leaving = false
    /// 再生の範囲 (= とても長い録画の途中。 送りのボタンを効かせるため。 今の位置は真ん中に置いたまま動かさない)
    private static let span = CMTime(seconds: 48 * 3600, preferredTimescale: 600)
    /// 小窓の再生 / 停止で、 マイクを入れる / 切る (= 引数は入れるか)
    var onMic: ((Bool) -> Void)?
    /// 一番下から上へ送った量 (pt)。 0 なら新しい行に付いていく
    private var scrolledUp: CGFloat = 0
    /// 上へ送っている間に、 下に新しい行が来たか
    private var newBelow = false
    /// 前に描いた会話の高さ (= 上へ送れる量の上限を決める)
    private var contentHeight: CGFloat = 0
    /// 小窓を出せるかの変わり目を log に出す (= 自動で出ない時の切り分け)
    private var possibleObservation: NSKeyValueObservation?
    private var sceneObservers: [NSObjectProtocol] = []

    func start(over screen: UIView) {
        guard AVPictureInPictureController.isPictureInPictureSupported() else {
            CAPLog.print("[CallPicture] PiP is not supported on this device")
            return
        }
        host.isUserInteractionEnabled = false
        screen.addSubview(host)
        freshLayer()
        arm()
        sceneObservers = [
            NotificationCenter.default.addObserver(
                forName: UIScene.willDeactivateNotification, object: nil, queue: .main
            ) { [weak self] _ in
                MainActor.assumeIsolated { self?.setLeaving(true) }
            },
            NotificationCenter.default.addObserver(
                forName: UIScene.didActivateNotification, object: nil, queue: .main
            ) { [weak self] _ in
                MainActor.assumeIsolated { self?.setLeaving(false) }
            },
        ]
        timer = Timer.scheduledTimer(withTimeInterval: Self.refreshSecs, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.render() }
        }
        CAPLog.print("[CallPicture] ready (starts when the app goes to the background)")
    }

    /// 絵を流し込む層を新しくする (= 始めた時と、 閉じた後に作り直す時。 前の層は前の仕組みと一緒に残す)。
    private func freshLayer() {
        layer.removeFromSuperlayer()
        layer = AVSampleBufferDisplayLayer()
        layer.frame = host.bounds
        layer.videoGravity = .resizeAspect
        var timebase: CMTimebase?
        CMTimebaseCreateWithSourceClock(
            allocator: kCFAllocatorDefault, sourceClock: CMClockGetHostTimeClock(), timebaseOut: &timebase)
        if let timebase {
            CMTimebaseSetTime(timebase, time: CMTimeMultiplyByRatio(Self.span, multiplier: 1, divisor: 2))
            CMTimebaseSetRate(timebase, rate: 0)
            layer.controlTimebase = timebase
        }
        host.layer.addSublayer(layer)
        render()
    }

    /// 小窓の仕組みを作る (= 始めた時と、 小窓を閉じた後)。
    private func arm() {
        let source = AVPictureInPictureController.ContentSource(sampleBufferDisplayLayer: layer, playbackDelegate: self)
        let controller = AVPictureInPictureController(contentSource: source)
        controller.canStartPictureInPictureAutomaticallyFromInline = true
        controller.delegate = self
        self.controller = controller
        possibleObservation = controller.observe(\.isPictureInPicturePossible, options: [.initial, .new]) { _, change in
            CAPLog.print("[CallPicture] possible=\(change.newValue.map(String.init(describing:)) ?? "?")")
        }
    }

    private func setLeaving(_ on: Bool) {
        leaving = on
        controller?.invalidatePlaybackState()
        CAPLog.print("[CallPicture] leaving=\(on) possible=\(controller?.isPictureInPicturePossible ?? false) active=\(controller?.isPictureInPictureActive ?? false)")
    }

    /// マイクの入 / 切を、 小窓の再生 / 停止の絵と帯に合わせる (= 画面の 🎙 から切り替えた時も)。
    func setMic(_ on: Bool) {
        micOn = on
        controller?.invalidatePlaybackState()
        render()
    }

    /// 小窓を今出す (= 自動で出なかった時の、 画面のボタンから)。 出せない時は false。
    func show() -> Bool {
        guard let controller, controller.isPictureInPicturePossible else { return false }
        controller.startPictureInPicture()
        return true
    }

    /// 会話を上 (= 古い方。 up が true) か下へ、 窓の 3 分の 2 だけ送る。
    func scroll(up: Bool) {
        let step = (Self.canvas.height - Self.bandHeight) * 2 / 3
        let most = max(0, contentHeight - (Self.canvas.height - Self.bandHeight - Self.margin))
        scrolledUp = up ? min(most, scrolledUp + step) : max(0, scrolledUp - step)
        if scrolledUp == 0 { newBelow = false }
        render()
    }

    func stop() {
        possibleObservation = nil
        sceneObservers.forEach(NotificationCenter.default.removeObserver)
        sceneObservers = []
        timer?.invalidate()
        timer = nil
        controller?.stopPictureInPicture()
        controller = nil
        retired.removeAll()
        layer.flushAndRemoveImage()
        host.removeFromSuperview()
    }

    /// backend の会話の知らせ (= `{"pip": "line", "who", "text"}` / `{"pip": "state", "state"}`) を受ける。
    func receive(_ message: Value) {
        guard case let .object(fields) = message, case let .string(kind)?? = fields["pip"] else { return }
        switch kind {
        case "line":
            guard case let .string(who)?? = fields["who"], case let .string(text)?? = fields["text"] else { return }
            lines.append((who, text))
            if lines.count > Self.keptLines { lines.removeFirst(lines.count - Self.keptLines) }
            if scrolledUp > 0 {
                // 読んでいる所を動かさない (= 新しい行の分だけ、 上へ送った量を増やす)
                scrolledUp += Self.bubbleSize(who: who, text: text).height + Self.gap
                newBelow = true
            }
        case "state":
            guard case let .string(state)?? = fields["state"] else { return }
            self.state = state
        default:
            return
        }
        render()
    }

    // MARK: - 絵を描いて流し込む

    private func render() {
        let format = UIGraphicsImageRendererFormat()
        format.scale = 2
        format.opaque = true
        let image = UIGraphicsImageRenderer(size: Self.canvas, format: format).image { context in
            draw(in: context.cgContext)
        }
        guard let picture = image.cgImage, let sample = Self.sample(of: picture) else { return }
        if layer.status == .failed { layer.flush() }
        layer.enqueue(sample)
    }

    private static let background = UIColor(white: 0.07, alpha: 1)
    private static let bandColor = UIColor(red: 0.12, green: 0.16, blue: 0.23, alpha: 1)
    private static let bandText = UIColor(red: 0.61, green: 0.79, blue: 1, alpha: 1)
    private static let mineColor = UIColor(red: 0.18, green: 0.44, blue: 0.84, alpha: 1)
    private static let theirsColor = UIColor(white: 0.17, alpha: 1)
    private static let bandHeight: CGFloat = 40
    private static let margin: CGFloat = 10
    private static let gap: CGFloat = 8
    private static let padding = CGSize(width: 10, height: 7)
    private static let textFont = UIFont.systemFont(ofSize: 20)

    private static func stateText(_ state: String) -> String {
        switch state {
        case "listening": return "🎙 聞いています"
        case "thinking": return "💭 考えています"
        case "speaking": return "🔊 話しています"
        default: return "⏸ 待っています"
        }
    }

    private func draw(in context: CGContext) {
        let size = Self.canvas
        Self.background.setFill()
        context.fill(CGRect(origin: .zero, size: size))

        // 上の帯: 今の状態
        Self.bandColor.setFill()
        context.fill(CGRect(x: 0, y: 0, width: size.width, height: Self.bandHeight))
        let bandText = Self.stateText(state) + (micOn ? "" : "  🎙✕") + (newBelow ? "   ▼ 新しい行" : "")
        let band = NSAttributedString(string: bandText, attributes: [
            .font: UIFont.systemFont(ofSize: 18, weight: .semibold), .foregroundColor: Self.bandText,
        ])
        band.draw(at: CGPoint(x: Self.margin, y: (Self.bandHeight - band.size().height) / 2))

        // 吹き出し: 新しい物を一番下に置き、 上へ積む (= 窓に入らない古い物は帯の下で切れる)
        let area = CGRect(x: 0, y: Self.bandHeight, width: size.width, height: size.height - Self.bandHeight)
        context.saveGState()
        context.clip(to: area)
        var bottom = size.height - Self.margin + scrolledUp
        var height: CGFloat = 0
        for line in lines.reversed() {
            let mine = line.who == "user"
            let text = Self.styled(line.text, color: mine ? UIColor.white : UIColor(white: 0.93, alpha: 1))
            let bubble = Self.bubbleSize(of: text)
            height += bubble.height + Self.gap
            let x = mine ? size.width - Self.margin - bubble.width : Self.margin
            let frame = CGRect(x: x, y: bottom - bubble.height, width: bubble.width, height: bubble.height)
            bottom = frame.minY - Self.gap
            guard frame.minY < size.height, frame.maxY > area.minY else { continue }   // 窓の外は描かない
            (mine ? Self.mineColor : Self.theirsColor).setFill()
            UIBezierPath(roundedRect: frame, cornerRadius: 12).fill()
            text.draw(with: frame.insetBy(dx: Self.padding.width, dy: Self.padding.height),
                      options: [.usesLineFragmentOrigin, .usesFontLeading], context: nil)
        }
        contentHeight = height
        context.restoreGState()
    }

    private static let maxBubbleWidth = (canvas.width - margin * 2) * 0.85

    private static func bubbleSize(who: String, text: String) -> CGSize {
        bubbleSize(of: styled(text, color: .white))
    }

    private static func bubbleSize(of text: NSAttributedString) -> CGSize {
        let bounds = text.boundingRect(
            with: CGSize(width: maxBubbleWidth - padding.width * 2, height: .greatestFiniteMagnitude),
            options: [.usesLineFragmentOrigin, .usesFontLeading], context: nil)
        return CGSize(width: ceil(bounds.width) + padding.width * 2, height: ceil(bounds.height) + padding.height * 2)
    }

    /// 行の中の markdown (= 太字・斜体・コード・リンクの文字) を描く文字にする (= 表や見出しのような行単位の形は、
    /// backend が小窓で読める行に直して送る)。 読めない文は、 そのままの文字で描く。
    private static func styled(_ text: String, color: UIColor) -> NSAttributedString {
        let options = AttributedString.MarkdownParsingOptions(interpretedSyntax: .inlineOnlyPreservingWhitespace)
        guard let parsed = try? AttributedString(markdown: text, options: options) else {
            return NSAttributedString(string: text, attributes: [.font: textFont, .foregroundColor: color])
        }
        let styled = NSMutableAttributedString()
        for run in parsed.runs {
            var font = textFont
            if let intent = run.inlinePresentationIntent {
                if intent.contains(.code) {
                    font = .monospacedSystemFont(ofSize: textFont.pointSize - 1, weight: .regular)
                }
                var traits: UIFontDescriptor.SymbolicTraits = []
                if intent.contains(.stronglyEmphasized) { traits.insert(.traitBold) }
                if intent.contains(.emphasized) { traits.insert(.traitItalic) }
                if !traits.isEmpty, let bolder = font.fontDescriptor.withSymbolicTraits(traits) {
                    font = UIFont(descriptor: bolder, size: font.pointSize)
                }
            }
            styled.append(NSAttributedString(
                string: String(parsed[run.range].characters), attributes: [.font: font, .foregroundColor: color]))
        }
        return styled
    }

    /// 絵を、 すぐに出す 1 枚の映像の frame にする。
    private static func sample(of picture: CGImage) -> CMSampleBuffer? {
        let width = picture.width, height = picture.height
        let attributes = [
            kCVPixelBufferCGImageCompatibilityKey: true,
            kCVPixelBufferCGBitmapContextCompatibilityKey: true,
            kCVPixelBufferIOSurfacePropertiesKey: [:] as CFDictionary,
        ] as CFDictionary
        var pixels: CVPixelBuffer?
        guard CVPixelBufferCreate(nil, width, height, kCVPixelFormatType_32BGRA, attributes, &pixels) == kCVReturnSuccess,
              let pixels else { return nil }
        CVPixelBufferLockBaseAddress(pixels, [])
        let bitmap = CGContext(
            data: CVPixelBufferGetBaseAddress(pixels), width: width, height: height, bitsPerComponent: 8,
            bytesPerRow: CVPixelBufferGetBytesPerRow(pixels), space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGImageAlphaInfo.premultipliedFirst.rawValue | CGBitmapInfo.byteOrder32Little.rawValue)
        bitmap?.draw(picture, in: CGRect(x: 0, y: 0, width: width, height: height))
        CVPixelBufferUnlockBaseAddress(pixels, [])

        var format: CMVideoFormatDescription?
        guard CMVideoFormatDescriptionCreateForImageBuffer(
            allocator: nil, imageBuffer: pixels, formatDescriptionOut: &format) == noErr, let format else { return nil }
        var timing = CMSampleTimingInfo(
            duration: .invalid, presentationTimeStamp: CMClockGetTime(CMClockGetHostTimeClock()),
            decodeTimeStamp: .invalid)
        var sample: CMSampleBuffer?
        guard CMSampleBufferCreateReadyWithImageBuffer(
            allocator: nil, imageBuffer: pixels, formatDescription: format, sampleTiming: &timing,
            sampleBufferOut: &sample) == noErr, let sample else { return nil }
        if let attachments = CMSampleBufferGetSampleAttachmentsArray(sample, createIfNecessary: true),
           CFArrayGetCount(attachments) > 0 {
            let first = unsafeBitCast(CFArrayGetValueAtIndex(attachments, 0), to: CFMutableDictionary.self)
            CFDictionarySetValue(
                first, Unmanaged.passUnretained(kCMSampleAttachmentKey_DisplayImmediately).toOpaque(),
                Unmanaged.passUnretained(kCFBooleanTrue).toOpaque())
        }
        return sample
    }
}

// 再生の操作: 生の映像として伝え、 再生 / 停止と送りは通話の操作に読み替える
extension CallPicture: AVPictureInPictureSampleBufferPlaybackDelegate {
    nonisolated func pictureInPictureController(_ controller: AVPictureInPictureController, setPlaying playing: Bool) {
        Task { @MainActor in
            self.setMic(playing)
            self.onMic?(playing)
        }
    }

    nonisolated func pictureInPictureControllerTimeRangeForPlayback(
        _ controller: AVPictureInPictureController
    ) -> CMTimeRange {
        CMTimeRange(start: .zero, duration: CallPicture.span)
    }

    nonisolated func pictureInPictureControllerIsPlaybackPaused(_ controller: AVPictureInPictureController) -> Bool {
        !(micOn || leaving)
    }

    nonisolated func pictureInPictureController(
        _ controller: AVPictureInPictureController, didTransitionToRenderSize newRenderSize: CMVideoDimensions
    ) {}

    nonisolated func pictureInPictureController(
        _ controller: AVPictureInPictureController, skipByInterval skipInterval: CMTime,
        completion completionHandler: @escaping () -> Void
    ) {
        let up = CMTimeGetSeconds(skipInterval) < 0
        Task { @MainActor in self.scroll(up: up) }
        completionHandler()
    }
}

extension CallPicture: AVPictureInPictureControllerDelegate {
    nonisolated func pictureInPictureControllerWillStartPictureInPicture(_ controller: AVPictureInPictureController) {
        CAPLog.print("[CallPicture] will start")
    }

    nonisolated func pictureInPictureControllerDidStartPictureInPicture(_ controller: AVPictureInPictureController) {
        CAPLog.print("[CallPicture] started")
        Task { @MainActor in self.setLeaving(false) }   // 出たので、 再生 / 停止の絵をマイクの状態に戻す
    }

    nonisolated func pictureInPictureController(
        _ controller: AVPictureInPictureController, failedToStartPictureInPictureWithError error: Error
    ) {
        CAPLog.print("[CallPicture] failed to start: \(error)")
    }

    nonisolated func pictureInPictureControllerDidStopPictureInPicture(_ controller: AVPictureInPictureController) {
        CAPLog.print("[CallPicture] stopped")
        // 一度閉じた仕組みは次に抜けても自動で出ないので、 通話の間なら作り直す (= 閉じる動きが終わってから、 新しい層で)
        Task { @MainActor in
            try? await Task.sleep(nanoseconds: CallPicture.rearmDelay)
            guard self.timer != nil, let old = self.controller, !old.isPictureInPictureActive else { return }
            old.delegate = nil
            self.retired.append(old)
            self.freshLayer()
            self.arm()
            CAPLog.print("[CallPicture] re-armed")
        }
    }

    /// 戻るのボタン: app が前に出る (= 画面は通話の前のまま。 戻せたと答える)
    nonisolated func pictureInPictureController(
        _ controller: AVPictureInPictureController,
        restoreUserInterfaceForPictureInPictureStopWithCompletionHandler completionHandler: @escaping (Bool) -> Void
    ) {
        completionHandler(true)
    }
}
