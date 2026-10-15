import Foundation
import SwiftUI
@_weakLinked import JournalingSuggestions

/// ジャーナル: iPhone が覚えている「その日の出来事」 (= 行った場所、 聴いた曲、 会った人、 運動) から、 人が 1 つ選んで
/// agent に渡す。 一覧を開いて選ぶのは人 (= iOS は agent に勝手には渡さない)。
enum Journal {
    static var ops: [DeviceOperation] {
        guard #available(iOS 17.2, *) else { return [] }
        return [
            DeviceOp(DeviceSpec(name: "journal.pick", kind: .read,
                                summary: "let the person pick a moment the iPhone remembers (places, songs, people, workouts)",
                                timeout: 600, foreground: true)) { _ in
                try requireForeground("Picking a moment")
                guard let front = frontController() else { throw DeviceError("no screen to show the list on") }
                let suggestion = try await Moment().run(from: front)
                var out: [String: Any] = ["title": suggestion.title]
                if let date = suggestion.date { out["from"] = iso(date.start); out["to"] = iso(date.end) }
                let places = await suggestion.content(forType: JournalingSuggestion.Location.self)
                out["places"] = places.map { ["place": $0.place as Any, "city": $0.city as Any, "date": $0.date.map(iso) as Any] }
                let songs = await suggestion.content(forType: JournalingSuggestion.Song.self)
                out["songs"] = songs.map { ["song": $0.song as Any, "artist": $0.artist as Any] }
                out["items"] = suggestion.items.count
                return DeviceOutput(out)
            },
        ]
    }
}

@available(iOS 17.2, *)
@MainActor private final class Moment {
    func run(from front: UIViewController) async throws -> JournalingSuggestion {
        try await withCheckedThrowingContinuation { done in
            var host: UIViewController?
            var finished = false
            let view = NavigationStack {
                JournalingSuggestionsPicker {
                    Label("Choose a moment", systemImage: "book")
                } onCompletion: { suggestion in
                    guard !finished else { return }
                    finished = true
                    host?.dismiss(animated: true)
                    done.resume(returning: suggestion)
                }
                .padding()
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button("Cancel") {
                            guard !finished else { return }
                            finished = true
                            host?.dismiss(animated: true)
                            done.resume(throwing: DeviceError("no moment was picked"))
                        }
                    }
                }
            }
            host = UIHostingController(rootView: view)
            // (= 払って閉じると答えが返らないので、 閉じるのは Cancel と選んだ時だけ)
            host!.isModalInPresentation = true
            front.present(host!, animated: true)
        }
    }
}
