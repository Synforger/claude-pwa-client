import Foundation
import UIKit

/// カメラ: app の前にカメラの画面を出し、 人が撮った写真を返す (= 裏では撮れない。 iOS の決まり)。
enum Camera {
    static let ops: [DeviceOperation] = [
        DeviceOp(DeviceSpec(name: "camera.take", kind: .act, summary: "open the camera on screen and return the photo taken",
                            params: [.bool("front", "use the front camera (default: back)")],
                            timeout: 300, foreground: true)) { args in
            try requireForeground("The camera")
            guard UIImagePickerController.isSourceTypeAvailable(.camera) else { throw DeviceError("no camera") }
            guard let front = frontController() else { throw DeviceError("no screen to show the camera on") }
            let image = try await Shot().take(from: front, front: args.bool("front") ?? false)
            guard let jpeg = image.jpegData(compressionQuality: 0.85) else { throw DeviceError("could not encode the photo") }
            return DeviceOutput(["width": Int(image.size.width * image.scale), "height": Int(image.size.height * image.scale)],
                                files: [DeviceFile(name: "camera.jpg", mime: "image/jpeg", data: jpeg)])
        },
    ]
}

@MainActor private final class Shot: NSObject, UIImagePickerControllerDelegate, UINavigationControllerDelegate {
    private var waiting: CheckedContinuation<UIImage, Error>?
    private var keep: Shot?

    func take(from front: UIViewController, front useFront: Bool) async throws -> UIImage {
        try await withCheckedThrowingContinuation { done in
            waiting = done
            keep = self
            let picker = UIImagePickerController()
            picker.sourceType = .camera
            if useFront, UIImagePickerController.isCameraDeviceAvailable(.front) { picker.cameraDevice = .front }
            picker.delegate = self
            front.present(picker, animated: true)
        }
    }

    private func finish(_ picker: UIImagePickerController, _ outcome: Result<UIImage, Error>) {
        picker.dismiss(animated: true)
        waiting?.resume(with: outcome)
        waiting = nil
        keep = nil
    }

    nonisolated func imagePickerController(_ picker: UIImagePickerController,
                                           didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]) {
        let image = info[.originalImage] as? UIImage
        Task { @MainActor in
            self.finish(picker, image.map { .success($0) } ?? .failure(DeviceError("no photo was taken")))
        }
    }

    nonisolated func imagePickerControllerDidCancel(_ picker: UIImagePickerController) {
        Task { @MainActor in self.finish(picker, .failure(DeviceError("the camera was closed without a photo"))) }
    }
}
