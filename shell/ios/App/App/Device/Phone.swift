import Foundation
import UIKit
import UserNotifications

/// iPhone の小さな操作: クリップボード、 ショートカットを動かす、 通知を出す。
enum Phone {
    static let ops: [DeviceOperation] = [
        DeviceOp(DeviceSpec(name: "clipboard.read", kind: .read, summary: "the text on the clipboard",
                            foreground: true)) { _ in
            // (= 裏で読むと iOS が貼り付けの許可を出せないので、 前に出ている時だけ)
            try requireForeground("Reading the clipboard")
            return DeviceOutput(["text": UIPasteboard.general.string as Any])
        },
        DeviceOp(DeviceSpec(name: "clipboard.write", kind: .change, summary: "put text on the clipboard",
                            params: [.string("text", "the text", required: true)])) { args in
            UIPasteboard.general.string = try args.required("text")
            return DeviceOutput(["ok": true])
        },
        DeviceOp(DeviceSpec(name: "shortcuts.run", kind: .act, summary: "run a shortcut from the Shortcuts app",
                            params: [.string("name", "the shortcut's name", required: true),
                                     .string("input", "text handed to the shortcut")], foreground: true)) { args in
            try requireForeground("Running a shortcut")
            var link = URLComponents(string: "shortcuts://run-shortcut")!
            link.queryItems = [URLQueryItem(name: "name", value: try args.required("name"))]
            if let input = args.string("input") {
                link.queryItems! += [URLQueryItem(name: "input", value: "text"), URLQueryItem(name: "text", value: input)]
            }
            guard let url = link.url, await UIApplication.shared.open(url) else {
                throw DeviceError("the Shortcuts app did not open")
            }
            return DeviceOutput(["opened": true])
        },
        DeviceOp(DeviceSpec(name: "notify.post", kind: .act, summary: "show a notification on the iPhone",
                            params: [.string("title", "the title", required: true),
                                     .string("body", "the text"),
                                     .int("after", "seconds from now (default: now)")])) { args in
            let center = UNUserNotificationCenter.current()
            guard try await center.requestAuthorization(options: [.alert, .sound, .badge]) else {
                throw DeviceError("notifications are not allowed")
            }
            let content = UNMutableNotificationContent()
            content.title = try args.required("title")
            content.body = args.string("body") ?? ""
            content.sound = .default
            let after = Double(max(args.int("after") ?? 0, 0))
            let trigger = after > 0 ? UNTimeIntervalNotificationTrigger(timeInterval: after, repeats: false) : nil
            try await center.add(UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: trigger))
            return DeviceOutput(["posted": true, "after_s": after])
        },
    ]
}
