import Foundation

/// app と extension (= ウィジェット・画面の配信) が話す backend。
///
/// `npx cap sync` が capacitor.config.json の server.url に書いた所 (= 画面を読み込む所と同じ)。 extension は同じ
/// file を自分の bundle に持つ (= project で app の file を extension の Resources にも入れている)。
enum ServerAddress {
    static func base() -> URL? {
        guard let file = Bundle.main.url(forResource: "capacitor.config", withExtension: "json"),
              let data = try? Data(contentsOf: file),
              let config = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let server = config["server"] as? [String: Any], let raw = server["url"] as? String else { return nil }
        return URL(string: raw)
    }

    /// backend の path の URL (= 例 `/sessions`)。
    static func url(_ path: String, scheme: String? = nil) throws -> URL {
        guard let base = base(), var parts = URLComponents(url: base, resolvingAgainstBaseURL: false) else {
            throw ServerAddressError("the app does not know its server; build it with CPC_SHELL_SERVER_URL")
        }
        if let scheme { parts.scheme = scheme }
        parts.path = path
        guard let url = parts.url else { throw ServerAddressError("bad path \(path)") }
        return url
    }
}

struct ServerAddressError: LocalizedError {
    let message: String
    init(_ message: String) { self.message = message }
    var errorDescription: String? { message }
}
