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
/// 無限)、 再生の操作には何もしない。 小窓を閉じても通話は続く。
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

    private let layer = AVSampleBufferDisplayLayer()
    private let host = UIView(frame: CGRect(x: 0, y: 0, width: 1, height: 1))
    private var controller: AVPictureInPictureController?
    private var lines: [(who: String, text: String)] = []
    private var state = "waiting"
    private var timer: Timer?

    func start(over screen: UIView) {
        guard AVPictureInPictureController.isPictureInPictureSupported() else {
            CAPLog.print("[CallPicture] PiP is not supported on this device")
            return
        }
        host.isUserInteractionEnabled = false
        screen.addSubview(host)
        layer.frame = host.bounds
        layer.videoGravity = .resizeAspect
        host.layer.addSublayer(layer)
        render()

        let source = AVPictureInPictureController.ContentSource(sampleBufferDisplayLayer: layer, playbackDelegate: self)
        let controller = AVPictureInPictureController(contentSource: source)
        controller.canStartPictureInPictureAutomaticallyFromInline = true
        controller.requiresLinearPlayback = true
        controller.delegate = self
        self.controller = controller
        timer = Timer.scheduledTimer(withTimeInterval: Self.refreshSecs, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.render() }
        }
        CAPLog.print("[CallPicture] ready (starts when the app goes to the background)")
    }

    func stop() {
        timer?.invalidate()
        timer = nil
        controller?.stopPictureInPicture()
        controller = nil
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
        let band = NSAttributedString(string: Self.stateText(state), attributes: [
            .font: UIFont.systemFont(ofSize: 18, weight: .semibold), .foregroundColor: Self.bandText,
        ])
        band.draw(at: CGPoint(x: Self.margin, y: (Self.bandHeight - band.size().height) / 2))

        // 吹き出し: 新しい物を一番下に置き、 上へ積む (= 窓に入らない古い物は帯の下で切れる)
        let area = CGRect(x: 0, y: Self.bandHeight, width: size.width, height: size.height - Self.bandHeight)
        context.saveGState()
        context.clip(to: area)
        let maxBubble = (size.width - Self.margin * 2) * 0.85
        var bottom = size.height - Self.margin
        for line in lines.reversed() {
            let mine = line.who == "user"
            let text = Self.styled(line.text, color: mine ? UIColor.white : UIColor(white: 0.93, alpha: 1))
            let bounds = text.boundingRect(
                with: CGSize(width: maxBubble - Self.padding.width * 2, height: .greatestFiniteMagnitude),
                options: [.usesLineFragmentOrigin, .usesFontLeading], context: nil)
            let bubble = CGSize(width: ceil(bounds.width) + Self.padding.width * 2,
                                height: ceil(bounds.height) + Self.padding.height * 2)
            let x = mine ? size.width - Self.margin - bubble.width : Self.margin
            let frame = CGRect(x: x, y: bottom - bubble.height, width: bubble.width, height: bubble.height)
            (mine ? Self.mineColor : Self.theirsColor).setFill()
            UIBezierPath(roundedRect: frame, cornerRadius: 12).fill()
            text.draw(with: frame.insetBy(dx: Self.padding.width, dy: Self.padding.height),
                      options: [.usesLineFragmentOrigin, .usesFontLeading], context: nil)
            bottom = frame.minY - Self.gap
            if bottom < area.minY { break }
        }
        context.restoreGState()
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

// 再生の操作: 生の映像として伝え、 操作には何もしない (= 一時停止も早送りも無い)
extension CallPicture: AVPictureInPictureSampleBufferPlaybackDelegate {
    nonisolated func pictureInPictureController(_ controller: AVPictureInPictureController, setPlaying playing: Bool) {}

    nonisolated func pictureInPictureControllerTimeRangeForPlayback(
        _ controller: AVPictureInPictureController
    ) -> CMTimeRange {
        CMTimeRange(start: .negativeInfinity, duration: .positiveInfinity)
    }

    nonisolated func pictureInPictureControllerIsPlaybackPaused(_ controller: AVPictureInPictureController) -> Bool {
        false
    }

    nonisolated func pictureInPictureController(
        _ controller: AVPictureInPictureController, didTransitionToRenderSize newRenderSize: CMVideoDimensions
    ) {}

    nonisolated func pictureInPictureController(
        _ controller: AVPictureInPictureController, skipByInterval skipInterval: CMTime,
        completion completionHandler: @escaping () -> Void
    ) {
        completionHandler()
    }
}

extension CallPicture: AVPictureInPictureControllerDelegate {
    nonisolated func pictureInPictureControllerDidStartPictureInPicture(_ controller: AVPictureInPictureController) {
        CAPLog.print("[CallPicture] started")
    }

    nonisolated func pictureInPictureController(
        _ controller: AVPictureInPictureController, failedToStartPictureInPictureWithError error: Error
    ) {
        CAPLog.print("[CallPicture] failed to start: \(error)")
    }

    nonisolated func pictureInPictureControllerDidStopPictureInPicture(_ controller: AVPictureInPictureController) {
        CAPLog.print("[CallPicture] stopped")
    }

    /// 戻るのボタン: app が前に出る (= 画面は通話の前のまま。 戻せたと答える)
    nonisolated func pictureInPictureController(
        _ controller: AVPictureInPictureController,
        restoreUserInterfaceForPictureInPictureStopWithCompletionHandler completionHandler: @escaping (Bool) -> Void
    ) {
        completionHandler(true)
    }
}
