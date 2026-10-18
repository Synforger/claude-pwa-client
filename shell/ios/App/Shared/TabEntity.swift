import AppIntents
import Foundation

/// タブ (= Siri とショートカットの送り先と、 Tabs のウィジェットの編集で選ぶ選択肢。 app とウィジェットの両方が持つ)。
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
