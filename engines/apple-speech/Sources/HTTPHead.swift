// HTTP/1.1 の要求の頭 (= 要求行と header) を読む。 本文は Content-Length の分だけ、 呼び手が続けて読む。

import Foundation

struct RequestHead: Equatable {
  let method: String
  let path: String
  /// header の名前は小文字にして持つ
  let headers: [String: String]

  var contentLength: Int { Int(headers["content-length"] ?? "") ?? 0 }
}

struct HTTPError: Error, Equatable {
  let status: Int
  let message: String
}

enum HTTPHead {
  private static let end = Data("\r\n\r\n".utf8)

  /// 受け取った分から頭を読む。 頭がまだ揃っていなければ nil。 返す bodyStart は data の中の本文の始まり。
  static func parse(_ data: Data) throws -> (head: RequestHead, bodyStart: Data.Index)? {
    guard let range = data.range(of: end) else { return nil }
    guard let text = String(data: data[data.startIndex..<range.lowerBound], encoding: .utf8) else {
      throw HTTPError(status: 400, message: "the request head is not UTF-8")
    }
    var lines = text.components(separatedBy: "\r\n")
    let parts = lines.removeFirst().split(separator: " ", omittingEmptySubsequences: true)
    guard parts.count == 3, parts[2].hasPrefix("HTTP/1.") else {
      throw HTTPError(status: 400, message: "the request line is not HTTP/1.x")
    }
    var headers: [String: String] = [:]
    for line in lines where !line.isEmpty {
      guard let colon = line.firstIndex(of: ":") else {
        throw HTTPError(status: 400, message: "a header has no colon")
      }
      let name = line[..<colon].trimmingCharacters(in: .whitespaces).lowercased()
      headers[name] = line[line.index(after: colon)...].trimmingCharacters(in: .whitespaces)
    }
    return (RequestHead(method: String(parts[0]), path: String(parts[1]), headers: headers), range.upperBound)
  }
}
