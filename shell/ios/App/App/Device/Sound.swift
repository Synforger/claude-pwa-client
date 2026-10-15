import AVFoundation
import Foundation
import SoundAnalysis
import Speech

/// 音: 録る、 読み上げる、 録った音を文字にする、 周りで鳴っている音の種類を当てる。
///
/// どれもマイクかスピーカーを使うので、 声の会話の間は断る (= 通話の途中で音の設定を変えると、 その通話の残りは
/// エコー消しが切れる)。 app が起きているのは前に出ている間なので、 前に出している時に頼む。 同時に 2 つは動かさない。
enum Sound {
    static let ops: [DeviceOperation] = [
        DeviceOp(DeviceSpec(name: "audio.record", kind: .read, summary: "record sound with the microphone and return the file",
                            params: [.number("seconds", "how long to record", required: true)],
                            timeout: 600, foreground: true)) { args in
            let file = try await record(seconds: try seconds(args), what: "Recording")
            return DeviceOutput(["seconds": try seconds(args)],
                                files: [DeviceFile(name: "recording.m4a", mime: "audio/mp4", data: try Data(contentsOf: file))])
        },
        DeviceOp(DeviceSpec(name: "audio.transcribe", kind: .read,
                            summary: "record with the microphone and turn the speech into text on the iPhone",
                            params: [.number("seconds", "how long to record", required: true),
                                     .string("language", "the language spoken, e.g. ja-JP or en-US (default ja-JP)")],
                            timeout: 600, foreground: true)) { args in
            let language = args.string("language") ?? "ja-JP"
            let file = try await record(seconds: try seconds(args), what: "Transcribing")
            let text = try await transcribe(file, language: language)
            return DeviceOutput(["text": text, "language": language],
                                files: [DeviceFile(name: "recording.m4a", mime: "audio/mp4", data: try Data(contentsOf: file))])
        },
        DeviceOp(DeviceSpec(name: "audio.sounds", kind: .read,
                            summary: "listen and name the kinds of sound around the iPhone (siren, applause, rain, ...)",
                            params: [.number("seconds", "how long to listen", required: true),
                                     .int("count", "how many kinds to return, most likely first (default 10)")],
                            timeout: 600, foreground: true)) { args in
            let file = try await record(seconds: try seconds(args), what: "Listening")
            return DeviceOutput(try classify(file, count: args.int("count") ?? 10))
        },
        DeviceOp(DeviceSpec(name: "audio.speak", kind: .act, summary: "say text aloud from the iPhone's speaker",
                            params: [.string("text", "what to say", required: true),
                                     .string("language", "the voice's language, e.g. ja-JP or en-US (default: the text's)")],
                            timeout: 300, foreground: true)) { args in
            try begin("Speaking")
            defer { end() }
            try await Speaker().say(try args.required("text"), language: args.string("language"))
            return DeviceOutput(["spoken": true])
        },
    ]

    /// 音を使っている (= 同時に 2 つ頼まれたら、 後の方を断る)
    @MainActor private static var busy = false

    @MainActor private static func begin(_ what: String) throws {
        try requireForeground(what)
        try requireNoCall(what)
        guard !busy else { throw DeviceError("another sound operation is running; ask again when it ends") }
        busy = true
    }

    @MainActor private static func end() {
        busy = false
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    private static func seconds(_ args: DeviceArgs) throws -> Double {
        guard let value = args.number("seconds"), value > 0 else { throw DeviceError("seconds must be more than 0") }
        return value
    }

    @MainActor private static func record(seconds: Double, what: String) async throws -> URL {
        try begin(what)
        defer { end() }
        guard await microphoneAllowed() else {
            throw DeviceError("microphone access is not allowed (Settings → the app → Microphone)")
        }
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.record, mode: .default)
        try session.setActive(true)
        let file = FileManager.default.temporaryDirectory.appendingPathComponent("device-\(UUID().uuidString).m4a")
        let recorder = try AVAudioRecorder(url: file, settings: [
            AVFormatIDKey: kAudioFormatMPEG4AAC, AVSampleRateKey: 44_100, AVNumberOfChannelsKey: 1,
            AVEncoderAudioQualityKey: AVAudioQuality.high.rawValue,
        ])
        guard recorder.record(forDuration: seconds) else { throw DeviceError("the recording did not start") }
        try await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000))
        recorder.stop()
        return file
    }

    private static func microphoneAllowed() async -> Bool {
        if #available(iOS 17.0, *) { return await AVAudioApplication.requestRecordPermission() }
        return await withCheckedContinuation { done in
            AVAudioSession.sharedInstance().requestRecordPermission { done.resume(returning: $0) }
        }
    }

    private static func transcribe(_ file: URL, language: String) async throws -> String {
        let status: SFSpeechRecognizerAuthorizationStatus = await withCheckedContinuation { done in
            SFSpeechRecognizer.requestAuthorization { done.resume(returning: $0) }
        }
        guard status == .authorized else { throw DeviceError("speech recognition is not allowed") }
        guard let recognizer = SFSpeechRecognizer(locale: Locale(identifier: language)), recognizer.isAvailable else {
            throw DeviceError("speech recognition for \(language) is not available on this iPhone")
        }
        let request = SFSpeechURLRecognitionRequest(url: file)
        // (= 音を外へ出さない。 iPhone が対応していない言語の時だけ Apple の server を使う)
        request.requiresOnDeviceRecognition = recognizer.supportsOnDeviceRecognition
        return try await withCheckedThrowingContinuation { done in
            var finished = false
            recognizer.recognitionTask(with: request) { result, error in
                guard !finished else { return }
                if let error { finished = true; done.resume(throwing: error); return }
                if let result, result.isFinal { finished = true; done.resume(returning: result.bestTranscription.formattedString) }
            }
        }
    }

    private static func classify(_ file: URL, count: Int) throws -> [[String: Any]] {
        let analyzer = try SNAudioFileAnalyzer(url: file)
        let request = try SNClassifySoundRequest(classifierIdentifier: .version1)
        let collector = SoundCollector()
        try analyzer.add(request, withObserver: collector)
        analyzer.analyze()
        // (= 区間ごとの結果のうち、 種類ごとに一番高い確からしさを取る)
        return collector.best.sorted { $0.value > $1.value }.prefix(max(count, 1))
            .map { ["sound": $0.key, "confidence": ($0.value * 100).rounded() / 100] }
    }
}

private final class SoundCollector: NSObject, SNResultsObserving {
    var best: [String: Double] = [:]

    func request(_ request: SNRequest, didProduce result: SNResult) {
        guard let result = result as? SNClassificationResult else { return }
        for item in result.classifications {
            best[item.identifier] = max(best[item.identifier] ?? 0, item.confidence)
        }
    }
}

@MainActor private final class Speaker: NSObject, AVSpeechSynthesizerDelegate {
    private let synthesizer = AVSpeechSynthesizer()
    private var waiting: CheckedContinuation<Void, Never>?

    func say(_ text: String, language: String?) async throws {
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playback, mode: .spokenAudio)
        try session.setActive(true)
        let utterance = AVSpeechUtterance(string: text)
        if let language { utterance.voice = AVSpeechSynthesisVoice(language: language) }
        synthesizer.delegate = self
        await withCheckedContinuation { done in
            waiting = done
            synthesizer.speak(utterance)
        }
    }

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        Task { @MainActor in self.waiting?.resume(); self.waiting = nil }
    }

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
        Task { @MainActor in self.waiting?.resume(); self.waiting = nil }
    }
}
