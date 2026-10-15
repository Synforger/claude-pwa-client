import AppIntents
import SwiftUI
import WidgetKit

/// Mac の agent が置いた文字と短い値を、 ホーム画面とロック画面に出す (= `cpc device widget set`)。
///
/// 中身は backend の `/device/boards/<名前>` が真値。 agent が置き換えた時、 app がつながっていればその場で描き直し
/// (= `widget.reload`)、 そうでなければ iOS が決める間隔で引き直す (= 頼むのは 15 分ごと)。 どの board を出すかは
/// 長押しの「ウィジェットを編集」 で選ぶ (= 選ばなければ `main`)。 押すと app が開き、 board がタブを持っていれば
/// そのタブを開く。
@available(iOS 17.0, *)
struct BoardWidget: Widget {
    var body: some WidgetConfiguration {
        AppIntentConfiguration(kind: "Board", intent: BoardConfiguration.self, provider: BoardProvider()) { entry in
            BoardView(entry: entry).widgetBackground()
        }
        .configurationDisplayName("Board")
        .description("Text and a short value the agent puts here.")
        .supportedFamilies([.systemSmall, .systemMedium, .systemLarge,
                            .accessoryRectangular, .accessoryInline, .accessoryCircular])
    }
}

/// 出す board (= ウィジェットの編集で選ぶ選択肢。 一覧は backend の `/device/boards`)。
@available(iOS 17.0, *)
struct BoardEntity: AppEntity {
    static var typeDisplayRepresentation: TypeDisplayRepresentation = "Board"
    static var defaultQuery = BoardQuery()

    let id: String

    var displayRepresentation: DisplayRepresentation { DisplayRepresentation(title: "\(id)") }
}

@available(iOS 17.0, *)
struct BoardQuery: EntityStringQuery {
    /// 選んだ名前は、 backend にまだ無くてもそのまま使う (= agent が後から置く board も選べる)
    func entities(for identifiers: [BoardEntity.ID]) async throws -> [BoardEntity] {
        identifiers.map { BoardEntity(id: $0) }
    }

    /// 打った名前を、 そのまま board の名前として出す (= backend の名前の決まりに合う物だけ)
    func entities(matching string: String) async throws -> [BoardEntity] {
        let name = string.trimmingCharacters(in: .whitespaces)
        let valid = (1...32).contains(name.count)
            && name.unicodeScalars.allSatisfy { CharacterSet.alphanumerics.contains($0) && $0.isASCII || "-_".unicodeScalars.contains($0) }
        let known = try await suggestedEntities().filter { $0.id.localizedCaseInsensitiveContains(name) }
        return valid && !known.contains(where: { $0.id == name }) ? known + [BoardEntity(id: name)] : known
    }

    func suggestedEntities() async throws -> [BoardEntity] {
        let names = (try? await BoardProvider.fetch("/device/boards"))
            .flatMap { ($0["boards"] as? [String: Any])?.keys.sorted() } ?? []
        return (names.contains(BoardProvider.main) ? names : [BoardProvider.main] + names).map { BoardEntity(id: $0) }
    }
}

@available(iOS 17.0, *)
struct BoardConfiguration: WidgetConfigurationIntent {
    static var title: LocalizedStringResource = "Board"
    static var description = IntentDescription("Which board to show.")

    @Parameter(title: "Board")
    var board: BoardEntity?
}

struct BoardEntry: TimelineEntry {
    let date: Date
    let name: String
    let title: String?
    let text: String?
    let value: String?
    let tab: String?
    let updated: Date?
    /// 引けなかった理由 (= backend に届かない時)
    let problem: String?

    var isEmpty: Bool { title == nil && text == nil && value == nil }

    static let sample = BoardEntry(date: Date(), name: "main", title: "Build", text: "All tests passed",
                                   value: "42", tab: nil, updated: Date(), problem: nil)
}

@available(iOS 17.0, *)
struct BoardProvider: AppIntentTimelineProvider {
    /// 何も選んでいないウィジェットが出す board (= backend の既定と同じ)
    static let main = "main"
    /// 引き直しを頼む間隔
    static let refresh: TimeInterval = 15 * 60

    func placeholder(in context: Context) -> BoardEntry { .sample }

    func snapshot(for configuration: BoardConfiguration, in context: Context) async -> BoardEntry {
        context.isPreview ? .sample : await Self.load(configuration.board?.id ?? Self.main)
    }

    func timeline(for configuration: BoardConfiguration, in context: Context) async -> Timeline<BoardEntry> {
        let entry = await Self.load(configuration.board?.id ?? Self.main)
        return Timeline(entries: [entry], policy: .after(entry.date.addingTimeInterval(Self.refresh)))
    }

    static func load(_ name: String) async -> BoardEntry {
        do {
            let answer = try await fetch("/device/boards/\(name)")
            let board = answer["board"] as? [String: Any] ?? [:]
            func field(_ key: String) -> String? { (board[key] as? String).flatMap { $0.isEmpty ? nil : $0 } }
            return BoardEntry(date: Date(), name: name, title: field("title"), text: field("text"),
                              value: field("value"), tab: field("tab"),
                              updated: (board["updated_at"] as? Double).map { Date(timeIntervalSince1970: $0) },
                              problem: nil)
        } catch {
            return BoardEntry(date: Date(), name: name, title: nil, text: nil, value: nil, tab: nil, updated: nil,
                              problem: "Can't reach the server")
        }
    }

    static func fetch(_ path: String) async throws -> [String: Any] {
        var request = URLRequest(url: try ServerAddress.url(path))
        request.timeoutInterval = 10
        let (data, _) = try await URLSession.shared.data(for: request)
        return try JSONSerialization.jsonObject(with: data) as? [String: Any] ?? [:]
    }
}

struct BoardView: View {
    let entry: BoardEntry
    @Environment(\.widgetFamily) private var family

    var body: some View {
        content.widgetURL(URL(string: entry.tab.map { "claudepwa://open?ses=\($0)" } ?? "claudepwa://open"))
    }

    /// 何も置かれていない時の 1 行
    private var empty: String { entry.problem ?? "Nothing on \(entry.name) yet" }

    @ViewBuilder private var content: some View {
        switch family {
        case .accessoryInline:
            Text(entry.isEmpty ? empty : [entry.value, entry.title ?? entry.text].compactMap { $0 }.joined(separator: " "))
        case .accessoryCircular:
            VStack(spacing: 0) {
                Text(entry.value ?? "–").font(.title3.bold()).minimumScaleFactor(0.5).lineLimit(1)
                if let title = entry.title { Text(title).font(.caption2).lineLimit(1) }
            }
        case .accessoryRectangular:
            VStack(alignment: .leading, spacing: 1) {
                if entry.isEmpty {
                    Text(empty).font(.caption)
                } else {
                    HStack(alignment: .firstTextBaseline) {
                        if let title = entry.title {
                            Text(title).font(.headline).lineLimit(1)
                            Spacer(minLength: 4)
                        }
                        if let value = entry.value { Text(value).font(.headline.bold()).lineLimit(1) }
                    }
                    if let text = entry.text { Text(text).font(.caption).lineLimit(entry.title == nil ? 3 : 2) }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        default:
            board(textLines: family == .systemSmall ? 3 : family == .systemMedium ? 4 : 14)
        }
    }

    private func board(textLines: Int) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            if entry.isEmpty {
                Text(empty).font(.caption).foregroundStyle(.secondary)
            } else {
                if let title = entry.title { Text(title).font(.caption).foregroundStyle(.secondary).lineLimit(1) }
                if let value = entry.value {
                    Text(value).font(.system(size: 34, weight: .bold, design: .rounded))
                        .minimumScaleFactor(0.4).lineLimit(1)
                }
                if let text = entry.text { Text(text).font(.subheadline).lineLimit(textLines) }
            }
            Spacer(minLength: 0)
            if let updated = entry.updated {
                Text(updated, style: .time).font(.caption2).foregroundStyle(.tertiary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}
