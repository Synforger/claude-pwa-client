// apple-speech: macOS に入っている聞き取りを、 whisper.cpp の `whisper-server` と同じ口で出す engine。
//
//   apple-speech [--host 127.0.0.1] [--port 10104] [--locale ja-JP]
//
//   POST /inference   multipart/form-data の `file` (= 音) と `prompt` (= 手がかりの語、 省略可) → {"text": "..."}
//   GET  /            {"status": "ok"} (= 起きているか)
//
// 聞き取った文は log に書かない (= 書くのは、 要求ごとの状態・音の長さ・掛かった時間だけ)。

import Foundation

func log(_ line: String) {
  FileHandle.standardError.write(Data("\(ISO8601DateFormatter().string(from: Date())) \(line)\n".utf8))
}

func option(_ name: String, _ fallback: String) -> String {
  let args = CommandLine.arguments
  guard let at = args.firstIndex(of: name), at + 1 < args.count else { return fallback }
  return args[at + 1]
}

let host = option("--host", "127.0.0.1")
let port = UInt16(option("--port", "10104")) ?? 10104
let localeIdentifier = option("--locale", "ja-JP")
// 受ける本文の上限。 backend が受ける音の上限 (= 10 分話した音、 約 29 MB) に、 multipart の包みの分を足しても
// 届かない大きさ
let maxBodyBytes = 64 << 20

let transcriber: Transcriber
do {
  transcriber = try await Transcriber(localeIdentifier: localeIdentifier)
  let started = Date()
  try await transcriber.warmUp()
  log("ready locale=\(localeIdentifier) warm-up=\(String(format: "%.2f", Date().timeIntervalSince(started)))s")
} catch {
  log("cannot start: \(error)")
  exit(1)
}

func inference(_ head: RequestHead, _ body: Data) async -> Response {
  guard let boundary = Multipart.boundary(contentType: head.headers["content-type"] ?? "") else {
    return .json(400, ["error": "the body must be multipart/form-data"])
  }
  let form: [String: FormPart]
  do {
    form = try Multipart.parse(body, boundary: boundary)
  } catch let error as HTTPError {
    return .json(error.status, ["error": error.message])
  } catch {
    return .json(400, ["error": "\(error)"])
  }
  guard let audio = form["file"], !audio.data.isEmpty else { return .json(400, ["error": "the form has no file"]) }
  let suffix = URL(fileURLWithPath: audio.filename ?? "audio.wav").pathExtension
  let url = FileManager.default.temporaryDirectory
    .appendingPathComponent("apple-speech-\(UUID().uuidString).\(suffix.isEmpty ? "wav" : suffix)")
  defer { try? FileManager.default.removeItem(at: url) }
  do {
    try audio.data.write(to: url)
    let started = Date()
    let (text, seconds) = try await transcriber.transcribe(fileAt: url, words: Prompt.words(form["prompt"]?.text ?? ""))
    log("POST /inference 200 audio=\(String(format: "%.2f", seconds))s took=\(String(format: "%.2f", Date().timeIntervalSince(started)))s")
    return .json(200, ["text": text])
  } catch let error as TranscriberError {
    log("POST /inference 415 \(error)")
    return .json(415, ["error": error.description])
  } catch {
    log("POST /inference 500 \(error)")
    return .json(500, ["error": "\(error)"])
  }
}

let server: Server
do {
  server = try Server(host: host, port: port, maxBodyBytes: maxBodyBytes) { head, body in
    switch (head.method, head.path) {
    case ("GET", "/"): return .json(200, ["status": "ok"])
    case ("POST", "/inference"): return await inference(head, body)
    case (_, "/"), (_, "/inference"): return .json(405, ["error": "method not allowed"])
    default: return .json(404, ["error": "not found"])
    }
  }
  try await server.start()
  log("listening on \(host):\(port)")
} catch {
  log("cannot listen on \(host):\(port): \(error)")
  exit(1)
}

// 待ち受けは server の queue で続く。 この task は終わらせない
while true { try await Task.sleep(for: .seconds(3_600)) }
