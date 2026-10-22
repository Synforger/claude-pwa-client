"""app の許可の文の検査 (= `.tooling/local-ci/ios-privacy-check.py`) が、 種類ごとに文の抜けを赤にするか。

iOS は許可の文の無い機能に触った瞬間に app を終わらせる (= 2026-10-15、 添付の「写真を撮る」 でカメラの文が無く落ちた)。
見本の repo (= 画面の code 1 本・native の code 1 本・Info.plist) を作り、 使う書き方ごとに、 文が無ければ赤・
在れば緑を見る。
"""
from __future__ import annotations

import importlib.util
import plistlib
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / ".tooling" / "local-ci" / "ios-privacy-check.py"
spec = importlib.util.spec_from_file_location("ios_privacy_check", SCRIPT)
check_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_module)

# 種類ごとに、 使っている書き方の見本 (= web は画面の code、 native は Swift)
SAMPLES = {
    "NSCameraUsageDescription": ("web", '<input type="file" accept="image/png,text/*" />'),
    "NSMicrophoneUsageDescription": ("web", "navigator.mediaDevices.getUserMedia({ audio: true })"),
    "NSPhotoLibraryUsageDescription": ("native", "PHPhotoLibrary.requestAuthorization(for: .readWrite) { _ in }"),
    "NSPhotoLibraryAddUsageDescription": ("native", "UIImageWriteToSavedPhotosAlbum(image, nil, nil, nil)"),
    "NSLocationWhenInUseUsageDescription": ("web", "navigator.geolocation.getCurrentPosition(cb)"),
    "NSSpeechRecognitionUsageDescription": ("native", "let r = SFSpeechRecognizer()"),
    "NSContactsUsageDescription": ("native", "let store = CNContactStore()"),
    "NSCalendarsUsageDescription": ("native", "let store = EKEventStore()"),
    "NSBluetoothAlwaysUsageDescription": ("native", "let m = CBCentralManager()"),
    "NSFaceIDUsageDescription": ("native", "let c = LAContext()"),
    "NSLocalNetworkUsageDescription": ("native", "let b = NWBrowser(for: d, using: p)"),
    "NSMotionUsageDescription": ("web", "DeviceMotionEvent.requestPermission()"),
    "NSLocationAlwaysAndWhenInUseUsageDescription": ("native", "manager.requestAlwaysAuthorization()"),
    "NSHealthShareUsageDescription": ("native", "let store = HKHealthStore()"),
    "NSHealthUpdateUsageDescription": ("native", "try await store.save(HKQuantitySample(type: t, quantity: q, start: s, end: e))"),
    "NSHomeKitUsageDescription": ("native", "let manager = HMHomeManager()"),
    "NFCReaderUsageDescription": ("native", "let session = NFCNDEFReaderSession(delegate: d, queue: nil, invalidateAfterFirstRead: true)"),
    "NSAppleMusicUsageDescription": ("native", "MPMediaLibrary.requestAuthorization { _ in }"),
    "NSAlarmKitUsageDescription": ("native", "let manager = AlarmManager.shared"),
    "NSFocusStatusUsageDescription": ("native", "let center = INFocusStatusCenter.default"),
}


def _repo(tmp_path: Path, kind: str, code: str, declared: dict) -> Path:
    web = tmp_path / "frontend" / "src"
    native = tmp_path / "shell" / "ios" / "App" / "App"
    web.mkdir(parents=True)
    native.mkdir(parents=True)
    (web / "App.jsx").write_text(code if kind == "web" else "export default 1\n")
    (native / "Plugin.swift").write_text(code if kind == "native" else "import UIKit\n")
    with (native / "Info.plist").open("wb") as fh:
        plistlib.dump(declared, fh)
    return tmp_path


def test_every_kind_has_a_sample():
    assert set(SAMPLES) == set(check_module.USES)


@pytest.mark.parametrize("key", sorted(SAMPLES))
def test_a_feature_without_its_usage_description_is_red(tmp_path, key):
    kind, code = SAMPLES[key]
    problems = check_module.check(_repo(tmp_path, kind, code, {}))
    assert any(p.startswith(f"{key} is missing") for p in problems), problems


@pytest.mark.parametrize("key", sorted(SAMPLES))
def test_a_feature_with_its_usage_description_is_green(tmp_path, key):
    kind, code = SAMPLES[key]
    assert check_module.check(_repo(tmp_path, kind, code, {key: "Says why."})) == []


def test_deleting_photos_needs_the_library_sentence_but_not_the_add_one(tmp_path):
    code = "PHPhotoLibrary.requestAuthorization(for: .readWrite) { _ in }\nPHAssetChangeRequest.deleteAssets(assets)\n"
    repo = _repo(tmp_path, "native", code, {"NSPhotoLibraryUsageDescription": "Says why."})
    assert check_module.check(repo) == []


def test_creating_a_photo_with_a_change_request_needs_the_add_sentence(tmp_path):
    code = "PHAssetChangeRequest.creationRequestForAsset(from: image)\n"
    problems = check_module.check(_repo(tmp_path, "native", code, {}))
    assert any(p.startswith("NSPhotoLibraryAddUsageDescription is missing") for p in problems), problems


def test_native_code_in_a_subfolder_is_seen(tmp_path):
    repo = _repo(tmp_path, "web", "export default 1\n", {})
    sub = repo / "shell" / "ios" / "App" / "App" / "Device"
    sub.mkdir()
    (sub / "Health.swift").write_text("let store = HKHealthStore()\n")
    problems = check_module.check(repo)
    assert any(p.startswith("NSHealthShareUsageDescription is missing") for p in problems), problems


def test_this_repo_is_green():
    assert check_module.check(SCRIPT.parents[2]) == []
