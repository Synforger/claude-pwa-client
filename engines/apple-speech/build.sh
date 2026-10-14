#!/usr/bin/env bash
# engines/apple-speech を build する (= macOS 26 以降と、 Swift の compiler が要る)。
#
#   bash engines/apple-speech/build.sh [出力の folder]
#
# 出力 (= 既定は engines/apple-speech/.build/): apple-speech (= engine) と apple-speech-tests (= 部品のテスト)。
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
out="${1:-$here/.build}"
mkdir -p "$out"
flags=(-O)

# Command Line Tools の一部の版は、 同じ module (= SwiftBridging) を 2 つの modulemap で定義していて、 Foundation を
# 読み込めない。 その版の時だけ、 build の間だけ片方を空の file に見せる (= 入っている file は書き換えない)。
tools="$(xcode-select -p)"
twice="$tools/usr/include/swift/module.modulemap"
if [ -f "$twice" ] && [ -f "$tools/usr/include/swift/bridging.modulemap" ] \
  && grep -q 'module SwiftBridging' "$twice" && grep -q 'module SwiftBridging' "$tools/usr/include/swift/bridging.modulemap"; then
  : > "$out/empty.modulemap"
  printf '{"version": 0, "case-sensitive": "false", "roots": [{"type": "file", "name": "%s", "external-contents": "%s"}]}\n' \
    "$twice" "$out/empty.modulemap" > "$out/overlay.yaml"
  flags+=(-vfsoverlay "$out/overlay.yaml" -Xcc -ivfsoverlay -Xcc "$out/overlay.yaml")
fi

started=$(date +%s)
swiftc "${flags[@]}" "$here"/Sources/*.swift -o "$out/apple-speech"
swiftc "${flags[@]}" "$here/Tests/main.swift" "$here/Sources/HTTPHead.swift" "$here/Sources/Multipart.swift" \
  "$here/Sources/Text.swift" -o "$out/apple-speech-tests"
echo "built $out/apple-speech and $out/apple-speech-tests in $(( $(date +%s) - started ))s"
