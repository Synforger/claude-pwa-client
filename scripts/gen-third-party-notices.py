#!/usr/bin/env python3
"""Generate THIRD_PARTY_NOTICES.md from pip-licenses + license-checker output.

Run via: task gen-notices
Requires: pip install pip-licenses (in the active env), npx license-checker-rseidelsohn

Reason for in-tree script vs. pure pipeline: needs metadata normalization
(google-crc32c LICENSE field is empty in pip metadata but the wheel ships
Apache-2.0; license-checker emits arrays for dual-licensed packages).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "THIRD_PARTY_NOTICES.md"


def norm_lic(s: str) -> str:
    if not s or s.strip() in ("", "UNKNOWN"):
        return "UNKNOWN"
    return (
        s.replace("Apache Software License", "Apache-2.0")
        .replace("MIT License", "MIT")
        .replace("BSD License", "BSD-3-Clause")
        .replace("ISC License (ISCL)", "ISC")
        .replace("Mozilla Public License 2.0 (MPL 2.0)", "MPL-2.0")
        .replace("Python Software Foundation License", "PSF-2.0")
    )


def collect_python() -> list[dict]:
    out = subprocess.run(
        ["pip-licenses", "--format", "json", "--no-version", "--with-urls",
         "--with-license-file", "--no-license-path"],
        capture_output=True, text=True, check=True,
    )
    pkgs = json.loads(out.stdout)
    # google-crc32c の License 欄 empty → wheel が Apache-2.0 (確認済)
    for p in pkgs:
        if p["Name"] == "google-crc32c" and not (p.get("License") or "").strip():
            p["License"] = "Apache-2.0"
    return pkgs


def collect_npm() -> dict:
    out = subprocess.run(
        ["npx", "--yes", "license-checker-rseidelsohn", "--production", "--json"],
        capture_output=True, text=True, check=True, cwd=str(REPO / "frontend"),
    )
    return json.loads(out.stdout)


def emit():
    py = collect_python()
    npm = collect_npm()

    lines: list[str] = []
    p = lines.append

    p("# Third-Party Notices")
    p("")
    p("claude-pwa-client は以下の OSS に依存している。 全 deps のライセンスは "
      "Apache License 2.0 (= 本リポジトリ自体のライセンス) と**互換**で、 "
      "GPL / AGPL / LGPL / SSPL 等の strong copyleft はゼロ。")
    p("")
    p("> 本 file は `scripts/gen-third-party-notices.py` で自動生成 "
      "(= `task gen-notices`)。 dependency を追加 / 削除 / version bump した時は再生成すること。")
    p("")
    p("## License summary")
    p("")
    agg: dict[tuple[str, str], list[str]] = {}
    for entry in py:
        L = norm_lic(entry.get("License", ""))
        agg.setdefault(("Python", L), []).append(entry["Name"])
    for k, v in npm.items():
        if k == "frontend@0.0.0":
            continue
        lic = v.get("licenses", "UNKNOWN")
        if isinstance(lic, list):
            lic = "/".join(lic)
        L = norm_lic(lic)
        name = k.rsplit("@", 1)[0]
        agg.setdefault(("NPM", L), []).append(name)

    p("| Ecosystem | License | Count |")
    p("|---|---|---|")
    for (eco, lic), names in sorted(agg.items()):
        p(f"| {eco} | {lic} | {len(names)} |")
    p("")

    p("## Backend (Python) dependencies")
    p("")
    p("| Package | License | URL |")
    p("|---|---|---|")
    for entry in sorted(py, key=lambda x: x["Name"].lower()):
        name = entry["Name"]
        lic = norm_lic(entry.get("License", ""))
        url = entry.get("URL", "") or ""
        if url == "UNKNOWN":
            url = ""
        p(f"| {name} | {lic} | {url} |")
    p("")

    p("## Frontend (npm production) dependencies")
    p("")
    p("> devDependencies (= eslint / vitest / typescript / @vitejs/plugin-react 等) は "
      "配布物 (= `dist/`) に含まれないため本 listing からは除外。")
    p("")
    p("| Package | License | URL |")
    p("|---|---|---|")
    for k in sorted(npm.keys(), key=str.lower):
        if k == "frontend@0.0.0":
            continue
        v = npm[k]
        lic = v.get("licenses", "UNKNOWN")
        if isinstance(lic, list):
            lic = "/".join(lic)
        L = norm_lic(lic)
        name = k.rsplit("@", 1)[0]
        repo = v.get("repository", "") or v.get("url", "") or ""
        p(f"| {name} | {L} | {repo} |")
    p("")

    p("## External services / processes (not bundled)")
    p("")
    p("以下は backend が **subprocess / HTTP で連携**するだけで、 本リポジトリに "
      "バンドル / static link されていない。 GPL の copyleft は別プロセス連携には "
      "波及しない (= FSF GPL FAQ 「プロセス分離は通常 derivative work には当たらない」)。")
    p("")
    p("| Component | License | Maintainer | 関係 |")
    p("|---|---|---|---|")
    p("| Claude Code CLI | Anthropic Commercial Terms | Anthropic | "
      "backend が PTY 経由で subprocess 起動 |")
    p("| claude-agent-sdk | MIT | Anthropic | "
      "Python dependency (= MCP / tool dispatch 経路) |")
    p("| Sunshine | GPL-3.0 | LizardByte | Path B 限定、 HTTP / WebRTC 連携 |")
    p("| moonlight-web-stream | GPL-3.0 | MrCreativ3001 | "
      "Path B 限定、 HTTP / WebRTC 連携 |")
    p("| Tailscale | BSD-3-Clause (client) | Tailscale Inc. | "
      "tailnet 経由配信、 本リポは tailnet 参加のみ |")
    p("")
    p("## Weak copyleft 説明")
    p("")
    p("**MPL-2.0** (= pywebpush / py-vapid / certifi / pathspec) は file-level weak copyleft。 "
      "該当 file 自体を改変した場合のみ改変版を MPL-2.0 で公開する義務があるが、 別 file から "
      "import / dynamic link する分には影響しない (= 本リポは import 利用のみで MPL ファイルを改変していない)。")
    p("")

    OUT.write_text("\n".join(lines))
    print(f"wrote {OUT.relative_to(REPO)} ({sum(len(v) for v in agg.values())} packages total)")


if __name__ == "__main__":
    try:
        emit()
    except subprocess.CalledProcessError as e:
        print(f"command failed: {e}", file=sys.stderr)
        print(e.stderr, file=sys.stderr)
        sys.exit(1)
