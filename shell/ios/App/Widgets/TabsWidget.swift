import AppIntents
import SwiftUI
import WidgetKit

/// タブの状態 (= 作業中 / 答え待ち / 静か) を、 ホーム画面とロック画面に出す。
///
/// 中身は backend の `/sessions` (= タブの名前) と `/sessions/overview` (= 状態) を引いて作る。 iOS が決める間隔で
/// 引き直す (= 頼むのは 15 分ごと)。 押すと app が開き、 1 つのタブを出している時はそのタブを開く。
///
/// iOS 17 からは、 長押しの「ウィジェットを編集」 で出すタブを選べる (= 状態の順 / 全部 / 選んだタブ)。 それより前の
/// iOS では選べず、 状態の順で出す (= `TabsWidgetFixed`)。
@available(iOS 17.0, *)
struct TabsWidget: Widget {
    var body: some WidgetConfiguration {
        AppIntentConfiguration(kind: "Tabs", intent: TabsConfiguration.self, provider: TabsChosenProvider()) { entry in
            TabsView(entry: entry).widgetBackground()
        }
        .configurationDisplayName("Tabs")
        .description("Which tabs are working and which are waiting for you.")
        .supportedFamilies(TabsWidgetFixed.families)
    }
}

/// iOS 17 より前の Tabs (= 選べない。 iOS 17 からは一覧に出さない)。
struct TabsWidgetFixed: Widget {
    static let families: [WidgetFamily] = [.systemSmall, .systemMedium, .accessoryRectangular, .accessoryInline,
                                           .accessoryCircular]

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "TabsFixed", provider: TabsProvider()) { entry in
            TabsView(entry: entry).widgetBackground()
        }
        .configurationDisplayName("Tabs")
        .description("Which tabs are working and which are waiting for you.")
        .supportedFamilies(Self.shown)
    }

    /// iOS 17 からは、 選べる Tabs と並んで 2 つ出ないように、 置ける場所を無くす
    private static var shown: [WidgetFamily] {
        if #available(iOS 17.0, *) { return [] }
        return families
    }
}

/// 出すタブの選び方 (= ウィジェットの編集の選択肢)。
@available(iOS 17.0, *)
enum TabsShow: String, AppEnum {
    /// 答え待ち → 作業中 → 静かの順 (= ロック画面には答え待ちと作業中だけ)
    case status
    /// 全部のタブを、 一覧の順で
    case all
    /// 選んだタブだけを、 選んだ順で
    case chosen

    static var typeDisplayRepresentation: TypeDisplayRepresentation = "Show"
    static var caseDisplayRepresentations: [TabsShow: DisplayRepresentation] = [
        .status: "Waiting and working first",
        .all: "All tabs",
        .chosen: "Chosen tabs",
    ]
}

@available(iOS 17.0, *)
struct TabsConfiguration: WidgetConfigurationIntent {
    static var title: LocalizedStringResource = "Tabs"
    static var description = IntentDescription("Which tabs to show.")

    @Parameter(title: "Show", default: .status)
    var show: TabsShow

    @Parameter(title: "Tabs")
    var tabs: [TabEntity]?

    static var parameterSummary: some ParameterSummary {
        When(\.$show, .equalTo, .chosen) {
            Summary { \.$show; \.$tabs }
        } otherwise: {
            Summary { \.$show }
        }
    }
}

@available(iOS 17.0, *)
struct TabsChosenProvider: AppIntentTimelineProvider {
    func placeholder(in context: Context) -> TabsEntry { .sample }

    func snapshot(for configuration: TabsConfiguration, in context: Context) async -> TabsEntry {
        context.isPreview ? .sample : await load(configuration)
    }

    func timeline(for configuration: TabsConfiguration, in context: Context) async -> Timeline<TabsEntry> {
        let entry = await load(configuration)
        return Timeline(entries: [entry], policy: .after(entry.date.addingTimeInterval(TabsProvider.refresh)))
    }

    private func load(_ configuration: TabsConfiguration) async -> TabsEntry {
        switch configuration.show {
        case .status: return await TabsProvider.load()
        case .all: return await TabsProvider.load(order: .listed, showIdle: true)
        case .chosen:
            let ids = (configuration.tabs ?? []).map(\.id)
            if ids.isEmpty {
                return TabsEntry(date: Date(), tabs: [], problem: "Edit the widget to choose tabs", showIdle: true)
            }
            return await TabsProvider.load(order: .chosen(ids), showIdle: true)
        }
    }
}

struct TabState: Identifiable {
    enum Kind: Int { case waiting = 0, working = 1, idle = 2 }
    let id: String
    let title: String
    let kind: Kind
}

struct TabsEntry: TimelineEntry {
    let date: Date
    let tabs: [TabState]
    /// 引けなかった理由 (= backend に届かない時)
    let problem: String?
    /// 静かなタブもロック画面に出す (= 全部 / 選んだタブを出す時)
    var showIdle = false

    var working: Int { tabs.filter { $0.kind == .working }.count }
    var waiting: Int { tabs.filter { $0.kind == .waiting }.count }
    var summary: String { "\(working) working · \(waiting) waiting" }

    static let sample = TabsEntry(date: Date(), tabs: [
        TabState(id: "a", title: "Assistant", kind: .working),
        TabState(id: "b", title: "Research", kind: .waiting),
        TabState(id: "c", title: "Notes", kind: .idle),
    ], problem: nil)
}

struct TabsProvider: TimelineProvider {
    /// 引き直しを頼む間隔
    static let refresh: TimeInterval = 15 * 60

    func placeholder(in context: Context) -> TabsEntry { .sample }

    func getSnapshot(in context: Context, completion: @escaping (TabsEntry) -> Void) {
        if context.isPreview { completion(.sample); return }
        Task { completion(await Self.load()) }
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<TabsEntry>) -> Void) {
        Task {
            let entry = await Self.load()
            completion(Timeline(entries: [entry], policy: .after(entry.date.addingTimeInterval(Self.refresh))))
        }
    }

    /// タブの並べ方 (= 状態の順 / 一覧の順 / 選んだ順で、 選んだタブだけ)
    enum Order { case status, listed, chosen([String]) }

    static func load(order: Order = .status, showIdle: Bool = false) async -> TabsEntry {
        do {
            async let names = fetch("/sessions")
            async let states = fetch("/sessions/overview")
            let rows = try await names as? [[String: Any]] ?? []
            let overview = try await states as? [String: [String: Any]] ?? [:]
            let tabs = rows.compactMap { row -> TabState? in
                guard let id = row["id"] as? String else { return nil }
                let state = overview[id] ?? [:]
                let kind: TabState.Kind = state["waiting_input"] as? Bool == true ? .waiting
                    : state["busy"] as? Bool == true ? .working : .idle
                return TabState(id: id, title: row["title"] as? String ?? id, kind: kind)
            }
            let ordered: [TabState]
            switch order {
            case .status: ordered = tabs.sorted { $0.kind.rawValue < $1.kind.rawValue }
            case .listed: ordered = tabs
            case .chosen(let ids):
                let byID = Dictionary(tabs.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
                ordered = ids.compactMap { byID[$0] }
            }
            return TabsEntry(date: Date(), tabs: ordered, problem: nil, showIdle: showIdle)
        } catch {
            return TabsEntry(date: Date(), tabs: [], problem: "Can't reach the server", showIdle: showIdle)
        }
    }

    private static func fetch(_ path: String) async throws -> Any {
        var request = URLRequest(url: try ServerAddress.url(path))
        request.timeoutInterval = 10
        let (data, _) = try await URLSession.shared.data(for: request)
        return try JSONSerialization.jsonObject(with: data)
    }
}

struct TabsView: View {
    let entry: TabsEntry
    @Environment(\.widgetFamily) private var family

    var body: some View {
        switch family {
        case .accessoryInline:
            Text(entry.problem ?? entry.summary)
        case .accessoryCircular:
            VStack(spacing: 0) {
                Text("\(entry.working)").font(.title2.bold())
                Text(entry.waiting > 0 ? "\(entry.waiting) wait" : "working").font(.caption2)
            }
        case .accessoryRectangular:
            VStack(alignment: .leading, spacing: 2) {
                Text(entry.problem ?? entry.summary).font(.headline)
                ForEach(entry.tabs.filter { entry.showIdle || $0.kind != .idle }.prefix(2)) { tab in
                    Text("\(Self.mark(tab.kind)) \(tab.title)").font(.caption).lineLimit(1)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        default:
            list(limit: family == .systemSmall ? 3 : 4)
        }
    }

    private func list(limit: Int) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(entry.problem ?? entry.summary).font(.caption).foregroundStyle(.secondary)
            ForEach(entry.tabs.prefix(limit)) { tab in
                Link(destination: Self.link(tab.id)) {
                    HStack(spacing: 6) {
                        Circle().fill(Self.color(tab.kind)).frame(width: 8, height: 8)
                        Text(tab.title).font(.subheadline).lineLimit(1)
                    }
                }
            }
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .widgetURL(entry.tabs.first.map { Self.link($0.id) })
    }

    /// app を開く URL (= app の AppLinkPlugin が受けてそのタブを開く)
    static func link(_ sid: String) -> URL { URL(string: "claudepwa://open?ses=\(sid)")! }

    static func mark(_ kind: TabState.Kind) -> String {
        switch kind {
        case .waiting: return "?"
        case .working: return "●"
        case .idle: return "○"
        }
    }

    static func color(_ kind: TabState.Kind) -> Color {
        switch kind {
        case .waiting: return .orange
        case .working: return .blue
        case .idle: return .gray.opacity(0.5)
        }
    }
}

extension View {
    /// iOS 17 からウィジェットは背景を宣言する (= 宣言しないと「Please adopt containerBackground」 と出る)
    @ViewBuilder func widgetBackground() -> some View {
        if #available(iOS 17.0, *) {
            containerBackground(.fill.tertiary, for: .widget)
        } else {
            padding()
        }
    }
}
