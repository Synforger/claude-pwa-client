import FamilyControls
import Foundation
import ManagedSettings
import SwiftUI

/// スクリーンタイム: 止める app を人が選び、 agent が止める・戻す。
///
/// 選んだ app は iOS が中身を隠した印でしか渡さない (= agent は app の名前を知れない)。 選んだ物は app の中に
/// 控えて、 止める・戻すはそれに対して掛ける。 使った時間そのものは、 iOS がどの app にも渡さない。
enum ScreenTime {
    static var ops: [DeviceOperation] {
        guard #available(iOS 16.0, *) else { return [] }
        return [
            DeviceOp(DeviceSpec(name: "screentime.pick", kind: .change,
                                summary: "let the person choose the apps, categories and sites that screentime.block stops",
                                timeout: 600, foreground: true)) { _ in
                try requireForeground("Choosing apps")
                try await AuthorizationCenter.shared.requestAuthorization(for: .individual)
                guard let front = frontController() else { throw DeviceError("no screen to show the list on") }
                let picked = try await Picker().run(from: front, current: chosen())
                save(picked)
                return DeviceOutput(counts(picked))
            },
            DeviceOp(DeviceSpec(name: "screentime.block", kind: .change,
                                summary: "stop the apps chosen with screentime.pick (iOS shows a shield over them)")) { _ in
                let picked = chosen()
                guard !(picked.applicationTokens.isEmpty && picked.categoryTokens.isEmpty && picked.webDomainTokens.isEmpty) else {
                    throw DeviceError("nothing is chosen; run screentime.pick first")
                }
                let store = ManagedSettingsStore()
                store.shield.applications = picked.applicationTokens
                store.shield.applicationCategories = .specific(picked.categoryTokens)
                store.shield.webDomains = picked.webDomainTokens
                return DeviceOutput(["blocked": true].merging(counts(picked)) { a, _ in a })
            },
            DeviceOp(DeviceSpec(name: "screentime.unblock", kind: .change, summary: "let the stopped apps run again")) { _ in
                ManagedSettingsStore().clearAllSettings()
                return DeviceOutput(["blocked": false])
            },
        ]
    }

    private static let key = "device.screentime.selection"

    @available(iOS 16.0, *)
    private static func chosen() -> FamilyActivitySelection {
        guard let data = UserDefaults.standard.data(forKey: key),
              let picked = try? JSONDecoder().decode(FamilyActivitySelection.self, from: data) else { return FamilyActivitySelection() }
        return picked
    }

    @available(iOS 16.0, *)
    private static func save(_ picked: FamilyActivitySelection) {
        UserDefaults.standard.set(try? JSONEncoder().encode(picked), forKey: key)
    }

    @available(iOS 16.0, *)
    private static func counts(_ picked: FamilyActivitySelection) -> [String: Any] {
        ["apps": picked.applicationTokens.count, "categories": picked.categoryTokens.count, "sites": picked.webDomainTokens.count]
    }
}

@available(iOS 16.0, *)
@MainActor private final class Picker {
    func run(from front: UIViewController, current: FamilyActivitySelection) async throws -> FamilyActivitySelection {
        try await withCheckedThrowingContinuation { done in
            var host: UIViewController?
            let view = PickerView(selection: current) { outcome in
                host?.dismiss(animated: true)
                done.resume(with: outcome)
            }
            host = UIHostingController(rootView: view)
            // (= 払って閉じると答えが返らないので、 閉じるのは Cancel と Done だけ)
            host!.isModalInPresentation = true
            front.present(host!, animated: true)
        }
    }
}

@available(iOS 16.0, *)
private struct PickerView: View {
    @State var selection: FamilyActivitySelection
    let finish: (Result<FamilyActivitySelection, Error>) -> Void

    var body: some View {
        NavigationStack {
            FamilyActivityPicker(selection: $selection)
                .navigationTitle("Apps to stop")
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button("Cancel") { finish(.failure(DeviceError("nothing was chosen"))) }
                    }
                    ToolbarItem(placement: .confirmationAction) {
                        Button("Done") { finish(.success(selection)) }
                    }
                }
        }
    }
}
