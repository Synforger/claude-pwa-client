@_weakLinked import AlarmKit
import Foundation
import MediaPlayer
import NaturalLanguage
import ShazamKit
import SwiftUI
@_weakLinked import Translation

/// 音と時間: ミュージックのライブラリ、 アラームとタイマー、 翻訳、 流れている曲の判定。
enum Media {
    static var ops: [DeviceOperation] {
        var ops: [DeviceOperation] = music
        if #available(iOS 26.0, *) { ops += alarms + translation }
        if #available(iOS 17.0, *) { ops += shazam }
        return ops
    }

    // MARK: ミュージック (= この iPhone のライブラリの曲)

    private static let music: [DeviceOperation] = [
        DeviceOp(DeviceSpec(name: "music.search", kind: .read, summary: "songs in the iPhone's music library",
                            params: [.string("query", "words in the title, artist or album", required: true),
                                     .int("count", "how many (default 20)")])) { args in
            try await allowMusic()
            let query = try args.required("query")
            let found = songs(matching: query).prefix(args.int("count") ?? 20)
            return DeviceOutput(found.map { ["id": "\($0.persistentID)", "title": $0.title as Any,
                                             "artist": $0.artist as Any, "album": $0.albumTitle as Any,
                                             "seconds": Int($0.playbackDuration)] })
        },
        DeviceOp(DeviceSpec(name: "music.play", kind: .act, summary: "play songs from the library",
                            params: [.string("query", "words in the title, artist or album (default: resume)")])) { args in
            try await allowMusic()
            let player = MPMusicPlayerController.systemMusicPlayer
            if let query = args.string("query") {
                let found = songs(matching: query)
                guard !found.isEmpty else { throw DeviceError("no songs match \(query)") }
                player.setQueue(with: MPMediaItemCollection(items: found))
            }
            player.play()
            return DeviceOutput(nowPlaying())
        },
        DeviceOp(DeviceSpec(name: "music.pause", kind: .act, summary: "pause the music")) { _ in
            MPMusicPlayerController.systemMusicPlayer.pause()
            return DeviceOutput(["paused": true])
        },
        DeviceOp(DeviceSpec(name: "music.now", kind: .read, summary: "the song playing now")) { _ in
            DeviceOutput(nowPlaying())
        },
    ]

    private static func allowMusic() async throws {
        let status: MPMediaLibraryAuthorizationStatus = await withCheckedContinuation { done in
            MPMediaLibrary.requestAuthorization { done.resume(returning: $0) }
        }
        guard status == .authorized else { throw DeviceError("music library access is not allowed") }
    }

    private static func songs(matching query: String) -> [MPMediaItem] {
        let needle = query.lowercased()
        return (MPMediaQuery.songs().items ?? []).filter { item in
            [item.title, item.artist, item.albumTitle].compactMap { $0?.lowercased() }.contains { $0.contains(needle) }
        }
    }

    private static func nowPlaying() -> [String: Any] {
        let player = MPMusicPlayerController.systemMusicPlayer
        guard let item = player.nowPlayingItem else { return ["playing": false] }
        return ["playing": player.playbackState == .playing, "title": item.title as Any, "artist": item.artist as Any,
                "position_s": Int(player.currentPlaybackTime), "seconds": Int(item.playbackDuration)]
    }

    // MARK: アラームとタイマー (= iOS 26 の AlarmKit。 時計 app と同じ鳴り方)

    @available(iOS 26.0, *)
    private static let alarms: [DeviceOperation] = [
        DeviceOp(DeviceSpec(name: "alarm.at", kind: .add, summary: "an alarm at a time of day",
                            params: [.string("time", "HH:MM, 24-hour", required: true),
                                     .string("label", "what the alarm is for")])) { args in
            let parts = try args.required("time").split(separator: ":").compactMap { Int($0) }
            guard parts.count == 2, (0..<24).contains(parts[0]), (0..<60).contains(parts[1]) else {
                throw DeviceError("time must be HH:MM")
            }
            let when = Alarm.Schedule.relative(.init(time: .init(hour: parts[0], minute: parts[1])))
            let alarm = try await schedule(.alarm(schedule: when, attributes: attributes(args.string("label") ?? "Alarm")))
            return DeviceOutput(["id": alarm.id.uuidString, "time": String(format: "%02d:%02d", parts[0], parts[1])])
        },
        DeviceOp(DeviceSpec(name: "alarm.timer", kind: .add, summary: "a timer that rings after some time",
                            params: [.int("seconds", "how long", required: true),
                                     .string("label", "what the timer is for")])) { args in
            guard let seconds = args.int("seconds"), seconds > 0 else { throw DeviceError("seconds must be above 0") }
            let alarm = try await schedule(.timer(duration: TimeInterval(seconds),
                                                  attributes: attributes(args.string("label") ?? "Timer")))
            return DeviceOutput(["id": alarm.id.uuidString, "rings_at": iso(Date().addingTimeInterval(TimeInterval(seconds)))])
        },
        DeviceOp(DeviceSpec(name: "alarm.list", kind: .read, summary: "alarms and timers this app has set")) { _ in
            DeviceOutput(try AlarmManager.shared.alarms.map { ["id": $0.id.uuidString, "state": "\($0.state)"] })
        },
        DeviceOp(DeviceSpec(name: "alarm.cancel", kind: .delete, summary: "cancel an alarm or timer this app has set",
                            params: [.string("id", "id from alarm.list", required: true)])) { args in
            guard let id = UUID(uuidString: try args.required("id")) else { throw DeviceError("not an alarm id") }
            try AlarmManager.shared.cancel(id: id)
            return DeviceOutput(["cancelled": id.uuidString])
        },
    ]

    @available(iOS 26.0, *)
    private struct AgentAlarm: AlarmMetadata {}

    @available(iOS 26.0, *)
    private static func attributes(_ label: String) -> AlarmAttributes<AgentAlarm> {
        let stop = AlarmButton(text: "Stop", textColor: .white, systemImageName: "stop.fill")
        return AlarmAttributes(presentation: AlarmPresentation(alert: .init(title: LocalizedStringResource(stringLiteral: label),
                                                                            stopButton: stop)),
                               tintColor: .orange)
    }

    @available(iOS 26.0, *)
    private static func schedule(_ configuration: AlarmManager.AlarmConfiguration<AgentAlarm>) async throws -> Alarm {
        let manager = AlarmManager.shared
        if manager.authorizationState != .authorized {
            guard try await manager.requestAuthorization() == .authorized else {
                throw DeviceError("alarms are not allowed (Settings → this app → Alarms)")
            }
        }
        return try await manager.schedule(id: UUID(), configuration: configuration)
    }

    // MARK: 翻訳 (= iPhone の中の翻訳。 その言語の組が入っている時だけ)

    @available(iOS 26.0, *)
    private static let translation: [DeviceOperation] = [
        DeviceOp(DeviceSpec(name: "translate.text", kind: .read, summary: "translate text on the iPhone",
                            params: [.string("text", "the text", required: true),
                                     .string("to", "target language, e.g. en, ja (default en)"),
                                     .string("from", "source language (default: detected)")])) { args in
            let text = try args.required("text")
            let source = args.string("from") ?? NLLanguageRecognizer.dominantLanguage(for: text)?.rawValue ?? "ja"
            let session = TranslationSession(installedSource: Locale.Language(identifier: source),
                                             target: Locale.Language(identifier: args.string("to") ?? "en"))
            let response = try await session.translate(text)
            return DeviceOutput(["text": response.targetText, "from": source, "to": args.string("to") ?? "en"])
        },
    ]

    // MARK: 流れている曲の判定 (= Shazam)

    @available(iOS 17.0, *)
    private static let shazam: [DeviceOperation] = [
        DeviceOp(DeviceSpec(name: "shazam.listen", kind: .read, summary: "name the song playing around the iPhone",
                            timeout: 60)) { _ in
            let session = SHManagedSession()
            switch await session.result() {
            case .match(let match):
                guard let item = match.mediaItems.first else { throw DeviceError("matched, but with no details") }
                return DeviceOutput(["title": item.title as Any, "artist": item.artist as Any,
                                     "apple_music": item.appleMusicURL?.absoluteString as Any])
            case .noMatch:
                return DeviceOutput(["match": false])
            case .error(let error, _):
                throw error
            }
        },
    ]
}
