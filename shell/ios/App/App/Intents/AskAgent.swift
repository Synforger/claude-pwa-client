import AppIntents
import Foundation
import UIKit

/// Siri とショートカットから、 app を開かずにタブの agent へ頼みを送る口。
///
/// 「Hey Siri、 <app の名前>で頼む」 (= 英語の Siri では「Ask <app の名前>」) と言うと、 送り先のタブ (= 前に選んだ物か、 その場で選ぶ) と頼みの文を
/// 訊いて、 画面から送るのと同じ口 (= `POST /pty/<sid>/send`) でそのタブへ送る。 タブの一覧は backend の
/// `/sessions` が真値 (= app は覚えない。 選択肢は `Shared/TabEntity.swift`)。

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

/// タブの agent と通話する: app を前に出して、 そのタブで声とマイクの会話を始める。
///
/// 通話の小窓 (= PiP) は、 前に出ている app からしか始められない (= iOS の決まり)。 app を前に出してから会話を
/// 始めるので、 人が app から抜けると小窓が自動で出る。
@available(iOS 16.0, *)
struct CallAgentIntent: AppIntent {
    static var title: LocalizedStringResource = "Call the Agent"
    static var description = IntentDescription("Opens the app and starts a voice call with the agent in a tab.")
    static var openAppWhenRun = true

    @Parameter(title: "Tab")
    var tab: TabEntity

    static var parameterSummary: some ParameterSummary {
        Summary("Call \(\.$tab)")
    }

    @MainActor
    func perform() async throws -> some IntentResult {
        guard let url = AppLinkPlugin.callURL(sid: tab.id) else { throw DeviceError("the tab \(tab.title) has no usable id") }
        // 自分の app を開く URL (= 前に出ている app の場面へ届き、 画面が受けて通話を始める)
        await UIApplication.shared.open(url)
        return .result()
    }
}

/// Siri の呼び方 (= 言い方の中に app の名前が要る)。
///
/// ここに書く言い方は開発言語 (= 英語) の Siri にだけ載る。 他の言語の言い方は `<言語>.lproj/AppShortcuts.strings` が、
/// ここの言い方を鍵にした訳として持つ (= 鍵 1 つに訳 1 つ。 日本語は `ja.lproj/AppShortcuts.strings`)。
@available(iOS 16.0, *)
struct AgentShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: AskAgentIntent(),
            phrases: [
                "Ask the agent in \(.applicationName)",
                "Ask \(.applicationName)",
                "\(.applicationName) request",
            ],
            shortTitle: "Ask the Agent",
            systemImageName: "bubble.left.and.text.bubble.right"
        )
        AppShortcut(
            intent: CallAgentIntent(),
            phrases: [
                "Call the agent in \(.applicationName)",
                "Call \(\.$tab) in \(.applicationName)",
                "\(.applicationName) call",
            ],
            shortTitle: "Call the Agent",
            systemImageName: "phone.bubble"
        )
    }
}
