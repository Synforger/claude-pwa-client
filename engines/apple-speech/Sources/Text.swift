// 文の出入り: whisper の `prompt` (= 句読点で区切った手がかりの語) を聞き取りの文脈の語の並びにし、 聞き取った文を
// whisper と同じ形 (= 声が無ければ空の文) で返す。

import Foundation

enum Prompt {
  private static let separators = CharacterSet(charactersIn: "、。,，.．・ \t\n")

  static func words(_ prompt: String) -> [String] {
    var seen = Set<String>()
    return prompt.components(separatedBy: separators).filter { !$0.isEmpty && seen.insert($0).inserted }
  }
}

enum Spoken {
  /// 聞き取った文。 文字も数字も無い (= 句読点だけ。 雑音や無音で「。」 が返る) 時は空にする
  static func text(_ heard: String) -> String {
    let trimmed = heard.trimmingCharacters(in: .whitespacesAndNewlines)
    return trimmed.unicodeScalars.contains(where: { CharacterSet.alphanumerics.contains($0) }) ? trimmed : ""
  }
}
