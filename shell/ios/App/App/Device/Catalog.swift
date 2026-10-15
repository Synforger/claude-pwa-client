import Foundation

/// app が Mac の agent に出す操作の全部 (= 種類ごとの file の一覧を並べる)。 ここが一覧の真値で、 backend は
/// app がつないだ時に受け取る (= `cpc device` が出す一覧)。
enum DeviceCatalog {
    static var all: [DeviceOperation] {
        Health.ops + Location.ops + Motion.ops + Home.ops + Bluetooth.ops + NFC.ops
            + Camera.ops + PhotoText.ops + Phone.ops + Media.ops + Progress.ops
            + Sound.ops + Hardware.ops + Places.ops + Scanning.ops + System.ops + Room.ops
            + ScreenTime.ops + Workout.ops + Journal.ops
    }
}
