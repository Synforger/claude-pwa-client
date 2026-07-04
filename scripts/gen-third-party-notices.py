#!/usr/bin/env python3
"""
gen-third-party-notices.py
==========================

Generate `THIRD_PARTY_NOTICES.md` from the currently-installed dependency
tree. Walks the project's active language toolchains and merges per-language
results into one alphabetical table.

Supported languages (= the script auto-skips a section if the toolchain or
the corresponding manifest is absent):

- Python  via `pip-licenses` (= reads the active env's installed packages)
- Node    via `license-checker-rseidelsohn` (= reads `frontend/` or repo root)

This script is intentionally idempotent: running it twice in succession on
an unchanged env produces an identical file (`git diff` empty).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT = REPO_ROOT / "THIRD_PARTY_NOTICES.md"


def have(name: str) -> bool:
    return shutil.which(name) is not None


def run(cmd: list[str], cwd: Path | None = None) -> str:
    try:
        out = subprocess.run(
            cmd, cwd=cwd, check=True, capture_output=True, text=True
        )
        return out.stdout
    except subprocess.CalledProcessError as exc:
        print(f"warning: {' '.join(cmd)} exited {exc.returncode}", file=sys.stderr)
        print(exc.stderr, file=sys.stderr)
        return ""
    except FileNotFoundError:
        return ""


def python_deps() -> list[dict[str, str]]:
    """Collect Python deps via pip-licenses (= JSON output)."""
    if not have("pip-licenses"):
        if have("pip"):
            print("info: installing pip-licenses into the active env", file=sys.stderr)
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "--quiet", "pip-licenses"],
                check=False,
            )
        if not have("pip-licenses"):
            return []
    raw = run(["pip-licenses", "--format", "json", "--with-urls"])
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [
        {
            "package": entry.get("Name", ""),
            "version": entry.get("Version", ""),
            "license": entry.get("License", ""),
            "source": entry.get("URL", ""),
            "lang": "python",
        }
        for entry in data
        if entry.get("Name")
    ]


def node_deps() -> list[dict[str, str]]:
    """Collect Node deps via license-checker-rseidelsohn (= JSON output)."""
    if not have("license-checker-rseidelsohn"):
        if have("npm"):
            print("info: installing license-checker-rseidelsohn globally", file=sys.stderr)
            subprocess.run(
                ["npm", "install", "-g", "--silent", "license-checker-rseidelsohn"],
                check=False,
            )
        if not have("license-checker-rseidelsohn"):
            return []

    # Search candidate roots for a node project.
    for candidate in [REPO_ROOT, REPO_ROOT / "frontend"]:
        if (candidate / "package.json").is_file():
            raw = run(["license-checker-rseidelsohn", "--json", "--production"], cwd=candidate)
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            out: list[dict[str, str]] = []
            for key, entry in data.items():
                name, _, version = key.rpartition("@")
                out.append({
                    "package": name or key,
                    "version": version,
                    "license": entry.get("licenses", ""),
                    "source": entry.get("repository", ""),
                    "lang": "node",
                })
            return out
    return []



def render(rows: Iterable[dict[str, str]]) -> str:
    rows = sorted(rows, key=lambda r: (r["lang"], r["package"].lower(), r["version"]))
    lines = [
        "# Third-Party Notices",
        "",
        "This file is **auto-generated** by `task gen-notices` (=",
        "`_core/scripts/gen-third-party-notices.py`). Do not edit by hand;",
        "re-run the generator and commit the diff.",
        "",
        "| lang | package | version | license | source |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        src = r["source"] or ""
        if src and src.startswith("http"):
            src = f"[link]({src})"
        lines.append(
            f"| {r['lang']} | {r['package']} | {r['version']} | "
            f"{r['license'] or 'UNKNOWN'} | {src} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    rows: list[dict[str, str]] = []
    rows.extend(python_deps())
    rows.extend(node_deps())
    if not rows:
        print(
            "warning: no deps collected (= no Python / Node env detected).\n"
            "Run after `task setup` so pip-licenses / npm see installed deps.",
            file=sys.stderr,
        )
        return 1
    OUTPUT.write_text(render(rows), encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(REPO_ROOT)} ({len(rows)} entries)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
