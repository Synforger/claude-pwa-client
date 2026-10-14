// apple-speech の、 機械に依らない部品 (= HTTP の頭 / multipart / 手がかりの語) のテスト。
// 聞き取りそのもの (= Transcriber) は macOS の model が要るので、 ここでは見ない。

import Foundation

var failures = 0
func check(_ ok: Bool, _ name: String, file: StaticString = #file, line: UInt = #line) {
  if ok { print("ok   \(name)") } else { failures += 1; print("FAIL \(name) (\(file):\(line))") }
}
func expectThrows(_ name: String, status: Int, _ body: () throws -> Void) {
  do { try body(); check(false, name) } catch let error as HTTPError { check(error.status == status, name) } catch { check(false, name) }
}

// --- HTTP の頭 ---------------------------------------------------------------
do {
  let head = Data("POST /inference HTTP/1.1\r\nHost: x\r\nContent-Type: a/b\r\nContent-Length: 5\r\n\r\nhello".utf8)
  let parsed = try HTTPHead.parse(head)
  check(parsed?.head == RequestHead(method: "POST", path: "/inference",
                                    headers: ["host": "x", "content-type": "a/b", "content-length": "5"]),
        "reads the request line and lower-cases header names")
  check(parsed?.head.contentLength == 5, "reads the content length")
  check(parsed.map { String(decoding: head[$0.bodyStart...], as: UTF8.self) } == "hello", "points at where the body starts")
  check(try HTTPHead.parse(Data("GET / HTTP/1.1\r\nHost: x\r\n".utf8)) == nil, "waits until the head is complete")
  check(try HTTPHead.parse(Data("GET / HTTP/1.1\r\n\r\n".utf8))?.head.contentLength == 0, "counts a missing length as 0")
  expectThrows("refuses a request line that is not HTTP/1.x", status: 400) { _ = try HTTPHead.parse(Data("hello\r\n\r\n".utf8)) }
  expectThrows("refuses a header with no colon", status: 400) { _ = try HTTPHead.parse(Data("GET / HTTP/1.1\r\nbroken\r\n\r\n".utf8)) }
} catch {
  check(false, "HTTP head: \(error)")
}

// --- multipart --------------------------------------------------------------
check(Multipart.boundary(contentType: "multipart/form-data; boundary=abc") == "abc", "takes the boundary")
check(Multipart.boundary(contentType: "multipart/form-data; boundary=\"a b\"") == "a b", "takes a quoted boundary")
check(Multipart.boundary(contentType: "Multipart/Form-Data;boundary=x") == "x", "reads the type and boundary in any case")
check(Multipart.boundary(contentType: "application/json") == nil, "has no boundary for another type")
check(Multipart.boundary(contentType: "multipart/form-data") == nil, "has no boundary when none is given")

do {
  // 音の中に、 区切りに似た並びと改行と 0 の byte を入れる (= 本文は区切りの完全な並びでだけ切る)
  let sound = Data([0, 13, 10, 45, 45, 0xff, 0x00, 13, 10]) + Data("--ab".utf8)
  var body = Data("--BOUNDARY\r\nContent-Disposition: form-data; name=\"prompt\"\r\n\r\nClaude、PWA。\r\n".utf8)
  body.append(Data("--BOUNDARY\r\nContent-Disposition: form-data; name=\"file\"; filename=\"speech.wav\"\r\nContent-Type: audio/wav\r\n\r\n".utf8))
  body.append(sound)
  body.append(Data("\r\n--BOUNDARY--\r\n".utf8))
  let form = try Multipart.parse(body, boundary: "BOUNDARY")
  check(form["prompt"]?.text == "Claude、PWA。", "reads a text field")
  check(form["file"]?.filename == "speech.wav", "reads the file name")
  check(form["file"]?.data == sound, "keeps the file bytes as they are")
  check(try Multipart.parse(Data("--B--\r\n".utf8), boundary: "B").isEmpty, "reads an empty form")
  expectThrows("refuses a body with no boundary", status: 400) { _ = try Multipart.parse(Data("nothing".utf8), boundary: "B") }
  expectThrows("refuses a part that is never closed", status: 400) {
    _ = try Multipart.parse(Data("--B\r\nContent-Disposition: form-data; name=\"a\"\r\n\r\nx".utf8), boundary: "B")
  }
  expectThrows("refuses a part with no name", status: 400) {
    _ = try Multipart.parse(Data("--B\r\nContent-Type: text/plain\r\n\r\nx\r\n--B--".utf8), boundary: "B")
  }
} catch {
  check(false, "multipart: \(error)")
}

// --- 手がかりの語 ----------------------------------------------------------------
check(Prompt.words("Claude、Swift、PWA。") == ["Claude", "Swift", "PWA"], "splits the prompt at punctuation")
check(Prompt.words("トグル、 オン、オン") == ["トグル", "オン"], "drops blanks and repeats")
check(Prompt.words("") == [], "has no words for an empty prompt")

// --- 聞き取った文 -------------------------------------------------------------------
check(Spoken.text(" おはよう。\n") == "おはよう。", "keeps what was said, without the blanks around it")
check(Spoken.text("。") == "", "drops a lone full stop (noise and silence come back as one)")
check(Spoken.text("、。 ？") == "", "drops punctuation alone")
check(Spoken.text("123") == "123", "keeps digits")
check(Spoken.text("") == "", "keeps nothing as nothing")

print(failures == 0 ? "all passed" : "\(failures) failed")
exit(failures == 0 ? 0 : 1)
