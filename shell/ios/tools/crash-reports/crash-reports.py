#!/usr/bin/env python3
"""USB か同じ Wi-Fi でつないだ iPhone から、 この app の crash の記録を拾って、 落ちた理由と場所を出す。

iOS は app が落ちると `<app の名前>-<日時>.ips` を残す (= 設定 → プライバシー → 解析と改善 → 解析データ と同じ物)。
`xcrun devicectl` で一覧を取り、 新しい物を写して、 例外の種類・終わらせた理由 (= 許可の文の抜けなど)・落ちた
thread の上の方の frame を並べる。

Usage:
  python3 shell/ios/tools/crash-reports/crash-reports.py --device <UDID> [--since 2026-10-15] [--out <dir>]
  (UDID は `xcrun devicectl list devices` の Identifier)
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# 試しの app (= Debug) も AltStore の app も、 実行 file の名前は App
APP_NAME = "App"
FRAMES = 12


def listing(device: str) -> list[tuple[str, str]]:
    """iPhone の crash の記録の (file の名前, 日付) の一覧 (= この app の分だけ)。"""
    out = subprocess.run(
        ["xcrun", "devicectl", "device", "info", "files", "--device", device, "--domain-type", "systemCrashLogs"],
        capture_output=True, text=True, check=True).stdout
    found = []
    for line in out.splitlines():
        m = re.match(rf"^({APP_NAME}-(\d{{4}}-\d{{2}}-\d{{2}})-\d{{6}}\.ips)\s", line)
        if m:
            found.append((m.group(1), m.group(2)))
    return sorted(found)


def choose(found: list[tuple[str, str]], since: str | None) -> list[str]:
    """拾う記録の名前 (= since があればその日付から後の全部、 無ければ一番新しい 1 件)。"""
    if since:
        return [name for name, day in found if day >= since]
    return [name for name, _ in found[-1:]]


def fetch(device: str, name: str, out_dir: Path) -> Path:
    target = out_dir / name
    subprocess.run(
        ["xcrun", "devicectl", "device", "copy", "from", "--device", device, "--domain-type", "systemCrashLogs",
         "--source", name, "--destination", str(target)],
        capture_output=True, text=True, check=True)
    return target


def summary(path: Path) -> str:
    head, body = path.read_text().split("\n", 1)
    meta, report = json.loads(head), json.loads(body)
    lines = [f"{path.name}  {meta.get('bundleID')} {meta.get('app_version')} ({meta.get('build_version')})  "
             f"{meta.get('timestamp')}"]
    ex = report.get("exception") or {}
    lines.append(f"  exception: {ex.get('type')} {ex.get('signal', '')} {ex.get('subtype', '')}".rstrip())
    term = report.get("termination") or {}
    if term.get("details") or term.get("indicator"):
        lines.append(f"  ended by: {term.get('namespace')} — {' '.join(term.get('details') or [term.get('indicator', '')])}")
    images = report.get("usedImages") or []
    thread = (report.get("threads") or [{}])[report.get("faultingThread", 0)]
    frames = report.get("lastExceptionBacktrace") or thread.get("frames") or []
    lines.append(f"  thread {report.get('faultingThread', 0)} {thread.get('queue') or thread.get('name') or ''}".rstrip())
    for frame in frames[:FRAMES]:
        image = images[frame["imageIndex"]].get("name", "?") if frame.get("imageIndex") is not None else "?"
        where = f" {frame['sourceFile']}:{frame.get('sourceLine', '')}" if frame.get("sourceFile") else ""
        lines.append(f"    {image}  {frame.get('symbol', '?')}{where}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--device", required=True)
    parser.add_argument("--since", help="この日付 (= YYYY-MM-DD) 以降の物だけ。 省けば一番新しい 1 件")
    parser.add_argument("--out", type=Path, help="写した記録を置く folder (= 省けば使い捨ての folder)")
    args = parser.parse_args()
    found = listing(args.device)
    chosen = choose(found, args.since)
    if not chosen:
        print("crash-reports: no crash report of the app on the device" + (f" since {args.since}" if args.since else ""))
        return 0
    out_dir = args.out or Path(tempfile.mkdtemp(prefix="crash-reports-"))
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in chosen:
        print(summary(fetch(args.device, name, out_dir)))
        print()
    print(f"crash-reports: {len(chosen)} report(s) copied to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
