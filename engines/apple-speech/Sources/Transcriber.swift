// 音の file を、 macOS に入っている聞き取り (= Speech framework の SpeechTranscriber) で文字にする。
// 聞き取りは端末の中で行う (= 音は外へ出ない)。 1 度に 1 つずつ (= 同時に来た要求は順に待つ)。

import AVFoundation
import Foundation
import Speech

enum TranscriberError: Error, CustomStringConvertible {
  case unsupportedLocale(String)
  case unreadableAudio(String)

  var description: String {
    switch self {
    case .unsupportedLocale(let id): "this Mac does not transcribe \(id) on the device"
    case .unreadableAudio(let reason): "the audio cannot be read: \(reason)"
    }
  }
}

actor Transcriber {
  private let locale: Locale

  /// 言語が端末で聞き取れることを確かめ、 足りない model を入れる。 聞き取れない言語なら throw。
  init(localeIdentifier: String) async throws {
    guard let locale = await SpeechTranscriber.supportedLocale(equivalentTo: Locale(identifier: localeIdentifier)) else {
      throw TranscriberError.unsupportedLocale(localeIdentifier)
    }
    self.locale = locale
    if let install = try await AssetInventory.assetInstallationRequest(supporting: [Self.module(locale)]) {
      try await install.downloadAndInstall()
    }
  }

  /// 起動の直後に 1 度だけ呼ぶ (= 最初の要求で model を読む待ちを、 起動の時に済ませる)。
  func warmUp() async throws {
    let url = FileManager.default.temporaryDirectory.appendingPathComponent("apple-speech-warm-up-\(UUID().uuidString).wav")
    defer { try? FileManager.default.removeItem(at: url) }
    let format = AVAudioFormat(standardFormatWithSampleRate: 16_000, channels: 1)!
    let file = try AVAudioFile(forWriting: url, settings: format.settings)
    let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 8_000)!
    buffer.frameLength = 8_000
    try file.write(from: buffer)
    file.close()   // 閉じるまで、 読む側からは長さ 0 の file に見える
    _ = try await transcribe(fileAt: url, words: [])
  }

  /// file を文字にする。 words = 聞き取りの手がかりにする語 (= 固有名詞など)。 返すのは (文, 音の秒数)。
  func transcribe(fileAt url: URL, words: [String]) async throws -> (text: String, seconds: Double) {
    let file: AVAudioFile
    do {
      file = try AVAudioFile(forReading: url)
    } catch {
      throw TranscriberError.unreadableAudio(error.localizedDescription)
    }
    let seconds = Double(file.length) / file.processingFormat.sampleRate
    // 音が 1 つも無い file は、 聞き取りに渡すと結果の流れが終わらない (= 待ち続ける)。 空の文で返す
    if file.length == 0 { return ("", 0) }
    let module = Self.module(locale)
    let analyzer = SpeechAnalyzer(modules: [module])
    if !words.isEmpty {
      let context = AnalysisContext()
      context.contextualStrings[.general] = words
      try await analyzer.setContext(context)
    }
    // 結果は区切りごとに確定した文で届く (= 途中の文は頼まない)。 届いた順につなぐ
    let collected = Task {
      var text = ""
      for try await result in module.results { text += String(result.text.characters) }
      return text
    }
    if let last = try await analyzer.analyzeSequence(from: file) {
      try await analyzer.finalizeAndFinish(through: last)
    } else {
      await analyzer.cancelAndFinishNow()
    }
    return (Spoken.text(try await collected.value), seconds)
  }

  private static func module(_ locale: Locale) -> SpeechTranscriber {
    SpeechTranscriber(locale: locale, transcriptionOptions: [], reportingOptions: [], attributeOptions: [])
  }
}
