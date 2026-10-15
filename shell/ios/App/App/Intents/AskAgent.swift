import AppIntents
import Foundation

/// Siri とショートカットから、 app を開かずにタブの agent へ頼みを送る口。
///
/// 「Hey Siri、 <app の名前>で頼む」 (= 英語の Siri では「Ask <app の名前>」) と言うと、 送り先のタブ (= 前に選んだ物か、 その場で選ぶ) と頼みの文を
/// 訊いて、 画面から送るのと同じ口 (= `POST /pty/<sid>/send`) でそのタブへ送る。 タブの一覧は backend の
/// `/sessions` が真値 (= app は覚えない)。

/// 送り先のタブ (= Siri とショートカットで選ぶ選択肢)。
@available(iOS 16.0, *)
struct TabEntity: AppEntity {
    static var typeDisplayRepresentation: TypeDisplayRepresentation = "Tab"
    static var defaultQuery = TabQuery()

    let id: String
    let title: String

    var displayRepresentation: DisplayRepresentation { DisplayRepresentation(title: "\(title)") }
}

/// タブの一覧を backend から引く。
@available(iOS 16.0, *)
struct TabQuery: EntityQuery {
    func entities(for identifiers: [TabEntity.ID]) async throws -> [TabEntity] {
        try await Self.tabs().filter { identifiers.contains($0.id) }
    }

    func suggestedEntities() async throws -> [TabEntity] { try await Self.tabs() }

    static func tabs() async throws -> [TabEntity] {
        let (data, _) = try await URLSession.shared.data(from: try ServerAddress.url("/sessions"))
        let rows = try JSONSerialization.jsonObject(with: data) as? [[String: Any]] ?? []
        return rows.compactMap { row in
            guard let id = row["id"] as? String else { return nil }
            return TabEntity(id: id, title: row["title"] as? String ?? id)
        }
    }
}

/// タブの agent へ頼みを送る。
@available(iOS 16.0, *)
struct AskAgentIntent: AppIntent {
    static var title: LocalizedStringResource = "Ask the Agent"
    static var description = IntentDescription("Sends a request to the agent in a tab, without opening the app.")
    static var openAppWhenRun = false

    @Parameter(title: "Tab")
    var tab: TabEntity

    @Parameter(title: "Request", inputOptions: String.IntentInputOptions(multiline: true))
    var request: String

    static var parameterSummary: some ParameterSummary {
        Summary("Ask \(\.$tab) to \(\.$request)")
    }

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let text = request.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { throw DeviceError("the request is empty") }
        var call = URLRequest(url: try ServerAddress.url("/pty/\(tab.id)/send"))
        call.httpMethod = "POST"
        call.setValue("application/json", forHTTPHeaderField: "Content-Type")
        // 送信 1 回の名前 (= Siri が同じ頼みを 2 度打っても、 backend が 2 度目を落とす)
        call.setValue(UUID().uuidString, forHTTPHeaderField: "Idempotency-Key")
        call.httpBody = try JSONSerialization.data(withJSONObject: ["text": text, "enter": true])
        let (data, _) = try await URLSession.shared.data(for: call)
        let reply = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        guard reply?["ok"] as? Bool == true else {
            throw DeviceError("\(tab.title) did not get it; open the app and send it again")
        }
        return .result(dialog: "Sent to \(tab.title).")
    }
}

/// Siri の呼び方 (= 言い方の中に app の名前が要る)。
@available(iOS 16.0, *)
struct AgentShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: AskAgentIntent(),
            phrases: [
                "Ask the agent in \(.applicationName)",
                "Ask \(.applicationName)",
                "\(.applicationName) request",
                // (= Siri の言語が日本語の時の言い方)
                "\(.applicationName)で頼む",
                "\(.applicationName)に頼む",
            ],
            shortTitle: "Ask the Agent",
            systemImageName: "bubble.left.and.text.bubble.right"
        )
    }
}
