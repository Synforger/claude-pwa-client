#!/usr/bin/env bash
# 小窓の吹き出しを Mac で絵にする道具を build する (= 出力の path は引数で渡す)。
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
out="${1:?usage: build.sh <output-binary>}"
swiftc -O -o "$out" "$here/../../App/App/ChatMarkdown.swift" "$here/main.swift"
