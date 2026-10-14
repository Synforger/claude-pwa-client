#!/usr/bin/env python3
"""iPhone の app が使う機能に、 Info.plist の許可の文 (= `NS…UsageDescription`) が揃っているかを見る。

iOS は、 許可の文の無い機能に触った瞬間に app を終わらせる (= crash の記録は `TCC __TCC_CRASHING_DUE_TO_PRIVACY_VIOLATION__`)。
2026-10-15 に、 添付の「写真を撮る」 でカメラの文が無く落ちた。 画面 (= `frontend/src/`、 app の中の WKWebView で動く)
と app の native (= `shell/ios/App/App/*.swift`) から、 iOS が許可の文を求める機能の使い方を種類ごとに探し、 文が
無ければ赤にする。

種類と、 使っていると見る書き方は下の USES が真値 (= 1 か所)。 試験は `backend/tests/test_ios_privacy_check.py`
(= わざと文を抜いた見本で赤になる)。

Usage:
  python3 .tooling/local-ci/ios-privacy-check.py [--root <repo>]
"""
from __future__ import annotations

import argparse
import plistlib
import re
import sys
from pathlib import Path

# 許可の文の名前 → それを使っていると見る書き方 (= 画面の code / native の code)
USES: dict[str, dict[str, list[str]]] = {
    "NSCameraUsageDescription": {
        # 画像を受け付ける <input type="file"> は、 iOS が「写真を撮る」 を出す (= カメラに触る)
        "web": [r"""accept=["'][^"']*image""", r"""\bcapture=""", r"getUserMedia\([^)]*video"],
        "native": [r"AVCaptureDevice", r"UIImagePickerController", r"\.video\b.*AVMediaType|AVMediaType\.video"],
    },
    "NSMicrophoneUsageDescription": {
        "web": [r"getUserMedia\("],
        "native": [r"enableMic\b", r"\.playAndRecord\b", r"\.record\b.*AVAudioSession", r"requestRecordPermission",
                   r"AVAudioRecorder"],
    },
    "NSPhotoLibraryUsageDescription": {
        "web": [],
        "native": [r"PHPhotoLibrary\.requestAuthorization\((?!for: \.addOnly)", r"PHAsset\.fetch"],
    },
    "NSPhotoLibraryAddUsageDescription": {
        "web": [],
        "native": [r"UIImageWriteToSavedPhotosAlbum", r"PHAssetChangeRequest", r"PHAssetCreationRequest"],
    },
    "NSLocationWhenInUseUsageDescription": {
        "web": [r"navigator\.geolocation"],
        "native": [r"CLLocationManager"],
    },
    "NSSpeechRecognitionUsageDescription": {
        "web": [r"SpeechRecognition\b"],
        "native": [r"SFSpeechRecognizer"],
    },
    "NSContactsUsageDescription": {"web": [], "native": [r"CNContactStore"]},
    "NSCalendarsUsageDescription": {"web": [], "native": [r"EKEventStore"]},
    "NSBluetoothAlwaysUsageDescription": {"web": [r"navigator\.bluetooth"], "native": [r"CBCentralManager", r"CBPeripheralManager"]},
    "NSFaceIDUsageDescription": {"web": [], "native": [r"LAContext"]},
    "NSLocalNetworkUsageDescription": {"web": [], "native": [r"NWBrowser", r"NetServiceBrowser", r"NWListener"]},
    "NSMotionUsageDescription": {"web": [r"DeviceMotionEvent\.requestPermission"], "native": [r"CMMotionManager", r"CMPedometer"]},
}

WEB_SUFFIXES = (".js", ".jsx", ".ts", ".tsx", ".html")


def sources(root: Path) -> dict[str, list[Path]]:
    web = [p for p in (root / "frontend" / "src").rglob("*")
           if p.suffix in WEB_SUFFIXES and ".test." not in p.name and "__tests__" not in p.parts]
    native = list((root / "shell" / "ios" / "App" / "App").glob("*.swift"))
    return {"web": web, "native": native}


def check(root: Path) -> list[str]:
    plist_path = root / "shell" / "ios" / "App" / "App" / "Info.plist"
    with plist_path.open("rb") as fh:
        declared = plistlib.load(fh)
    files = sources(root)
    problems: list[str] = []
    for key, kinds in USES.items():
        if isinstance(declared.get(key), str) and declared[key].strip():
            continue
        for kind, patterns in kinds.items():
            for path in files[kind]:
                text = path.read_text(encoding="utf-8", errors="replace")
                for pattern in patterns:
                    found = re.search(pattern, text)
                    if found:
                        line = text.count("\n", 0, found.start()) + 1
                        problems.append(f"{key} is missing from Info.plist, but "
                                        f"{path.relative_to(root)}:{line} uses it ({found.group(0)!r})")
                        break
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    problems = check(args.root)
    for problem in problems:
        print(f"ios-privacy-check: {problem}", file=sys.stderr)
    if problems:
        print("fix: add the key with a sentence saying what the app does with it "
              "(and the same sentence to the AltStore source's appPermissions.privacy)", file=sys.stderr)
        return 1
    print("ios-privacy-check: every feature the app uses has its usage description")
    return 0


if __name__ == "__main__":
    sys.exit(main())
