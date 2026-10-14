// multipart/form-data の本文から、 名前ごとの中身を取り出す (= whisper-server の `POST /inference` と同じ形で受ける)。

import Foundation

struct FormPart: Equatable {
  let name: String
  let filename: String?
  let data: Data

  var text: String { String(decoding: data, as: UTF8.self) }
}

enum Multipart {
  /// Content-Type の boundary (= 引用符は外す)。 multipart/form-data でなければ nil。
  static func boundary(contentType: String) -> String? {
    let fields = contentType.split(separator: ";").map { $0.trimmingCharacters(in: .whitespaces) }
    guard let kind = fields.first, kind.lowercased() == "multipart/form-data" else { return nil }
    for field in fields.dropFirst() where field.lowercased().hasPrefix("boundary=") {
      let value = field.dropFirst("boundary=".count)
      let bare = value.hasPrefix("\"") && value.hasSuffix("\"") && value.count >= 2 ? value.dropFirst().dropLast() : value
      return bare.isEmpty ? nil : String(bare)
    }
    return nil
  }

  /// 本文を名前 → 中身にする (= 同じ名前が 2 つあれば後の方)。 形が違えば HTTPError (400)。
  static func parse(_ body: Data, boundary: String) throws -> [String: FormPart] {
    let opening = Data("--\(boundary)".utf8)
    let separator = Data("\r\n--\(boundary)".utf8)
    let headEnd = Data("\r\n\r\n".utf8)
    guard let first = body.range(of: opening) else { throw bad("the body has no boundary") }
    var parts: [String: FormPart] = [:]
    var at = first.upperBound
    while true {
      // 区切りの直後が "--" なら終わり、 "\r\n" なら次の部分
      let rest = body[at...]
      if rest.starts(with: Data("--".utf8)) { return parts }
      guard rest.starts(with: Data("\r\n".utf8)) else { throw bad("a boundary is not followed by a line break") }
      let start = body.index(at, offsetBy: 2)
      guard let head = body.range(of: headEnd, in: start..<body.endIndex) else { throw bad("a part has no header end") }
      guard let next = body.range(of: separator, in: head.upperBound..<body.endIndex) else {
        throw bad("the body has no closing boundary")
      }
      let headers = String(decoding: body[start..<head.lowerBound], as: UTF8.self)
      guard let disposition = headers.components(separatedBy: "\r\n").first(where: {
        $0.lowercased().hasPrefix("content-disposition:")
      }), let name = parameter("name", in: disposition) else {
        throw bad("a part has no name")
      }
      parts[name] = FormPart(name: name, filename: parameter("filename", in: disposition),
                             data: Data(body[head.upperBound..<next.lowerBound]))
      at = next.upperBound
    }
  }

  /// `name="value"` の value (= Content-Disposition の引数)
  private static func parameter(_ key: String, in header: String) -> String? {
    for field in header.split(separator: ";").dropFirst() {
      let pair = field.trimmingCharacters(in: .whitespaces)
      guard pair.lowercased().hasPrefix("\(key)=") else { continue }
      let value = pair.dropFirst(key.count + 1)
      return String(value.hasPrefix("\"") && value.hasSuffix("\"") && value.count >= 2 ? value.dropFirst().dropLast() : value)
    }
    return nil
  }

  private static func bad(_ message: String) -> HTTPError { HTTPError(status: 400, message: message) }
}
