import Foundation
import Intents
import LocalAuthentication
import MessageUI
import UIKit

/// iPhone の仕組みを通す操作: Face ID で本人か確かめる、 URL や他の app を開く、 SMS とメールの下書きを出す、
/// 集中モードかを見る。 送る・電話をかけるといった最後の一押しは、 どれも iPhone で人が押す (= iOS の決まり)。
enum System {
    static let ops: [DeviceOperation] = [
        DeviceOp(DeviceSpec(name: "auth.check", kind: .read, summary: "ask for Face ID (or the passcode) on the iPhone",
                            params: [.string("reason", "what it is for, shown to the person", required: true)],
                            timeout: 120, foreground: true)) { args in
            try requireForeground("Face ID")
            let context = LAContext()
            UserDefaults.standard.set(true, forKey: Permissions.faceIDAsked)
            do {
                let passed = try await context.evaluatePolicy(.deviceOwnerAuthentication,
                                                              localizedReason: try args.required("reason"))
                return DeviceOutput(["passed": passed])
            } catch let error as LAError where [.userCancel, .authenticationFailed, .appCancel].contains(error.code) {
                return DeviceOutput(["passed": false, "why": error.localizedDescription])
            }
        },
        DeviceOp(DeviceSpec(name: "app.open", kind: .act,
                            summary: "open a URL on the iPhone: a web page, another app (maps://, tel:, sms:, shortcuts://, ...)",
                            params: [.string("url", "the URL", required: true)], foreground: true)) { args in
            try requireForeground("Opening a URL")
            guard let url = URL(string: try args.required("url")) else { throw DeviceError("not a URL") }
            guard await UIApplication.shared.open(url) else { throw DeviceError("nothing on the iPhone opens \(url)") }
            return DeviceOutput(["opened": url.absoluteString])
        },
        DeviceOp(DeviceSpec(name: "message.compose", kind: .act,
                            summary: "show a text message ready to send (the person presses send)",
                            params: [.string("to", "phone numbers or emails, separated by commas"),
                                     .string("body", "the text")], timeout: 600, foreground: true)) { args in
            try requireForeground("Writing a message")
            guard MFMessageComposeViewController.canSendText() else { throw DeviceError("this iPhone cannot send messages") }
            guard let front = frontController() else { throw DeviceError("no screen to show the message on") }
            let sheet = MFMessageComposeViewController()
            sheet.recipients = list(args.string("to"))
            sheet.body = args.string("body")
            let result = try await Compose().message(sheet, from: front)
            return DeviceOutput(["result": result])
        },
        DeviceOp(DeviceSpec(name: "mail.compose", kind: .act,
                            summary: "show an email ready to send (the person presses send)",
                            params: [.string("to", "addresses, separated by commas"), .string("subject", "the subject"),
                                     .string("body", "the text")], timeout: 600, foreground: true)) { args in
            try requireForeground("Writing an email")
            guard MFMailComposeViewController.canSendMail() else { throw DeviceError("no mail account is set up on this iPhone") }
            guard let front = frontController() else { throw DeviceError("no screen to show the email on") }
            let sheet = MFMailComposeViewController()
            sheet.setToRecipients(list(args.string("to")))
            sheet.setSubject(args.string("subject") ?? "")
            sheet.setMessageBody(args.string("body") ?? "", isHTML: false)
            let result = try await Compose().mail(sheet, from: front)
            return DeviceOutput(["result": result])
        },
        DeviceOp(DeviceSpec(name: "focus.status", kind: .read, summary: "whether a Focus (Do Not Disturb, Sleep, ...) is on")) { _ in
        let center = INFocusStatusCenter.default
        let status = await withCheckedContinuation { done in center.requestAuthorization { done.resume(returning: $0) } }
        guard status == .authorized else { throw DeviceError("Focus status is not allowed") }
        return DeviceOutput(["focused": center.focusStatus.isFocused as Any])
        },
    ]

    private static func list(_ raw: String?) -> [String] {
        (raw ?? "").split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
    }
}

@MainActor private final class Compose: NSObject, MFMessageComposeViewControllerDelegate, MFMailComposeViewControllerDelegate {
    private var waiting: CheckedContinuation<String, Never>?
    private var keep: Compose?

    func message(_ sheet: MFMessageComposeViewController, from front: UIViewController) async throws -> String {
        sheet.messageComposeDelegate = self
        return await show(sheet, from: front)
    }

    func mail(_ sheet: MFMailComposeViewController, from front: UIViewController) async throws -> String {
        sheet.mailComposeDelegate = self
        return await show(sheet, from: front)
    }

    private func show(_ sheet: UIViewController, from front: UIViewController) async -> String {
        await withCheckedContinuation { done in
            waiting = done
            keep = self
            front.present(sheet, animated: true)
        }
    }

    private func finish(_ sheet: UIViewController, _ result: String) {
        sheet.dismiss(animated: true)
        waiting?.resume(returning: result)
        waiting = nil
        keep = nil
    }

    nonisolated func messageComposeViewController(_ controller: MFMessageComposeViewController,
                                                  didFinishWith result: MessageComposeResult) {
        let name = [MessageComposeResult.sent: "sent", .cancelled: "cancelled", .failed: "failed"][result] ?? "unknown"
        Task { @MainActor in self.finish(controller, name) }
    }

    nonisolated func mailComposeController(_ controller: MFMailComposeViewController,
                                           didFinishWith result: MFMailComposeResult, error: Error?) {
        let name = [MFMailComposeResult.sent: "sent", .saved: "saved as a draft", .cancelled: "cancelled",
                    .failed: "failed"][result] ?? "unknown"
        Task { @MainActor in self.finish(controller, name) }
    }
}
