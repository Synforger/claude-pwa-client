#!/usr/bin/env python3
"""W2 residue detector — 3 種の同型 regression を機械列挙する.

Phase J-7 / J-8 / J-9 で観測された 3 パターン:

  A: 状態の二重管理   — features の useState と state/<store>.js export の同名衝突
                       (= J-9: useChatStream.loading vs state/ephemeral.loading)
  B: store-orphan     — state/*.js の setter export を誰も呼ばない / 値を誰も
                       subscribe しない dead export (= 二重管理の裏返し)
  C: position-anchor — CSS position: absolute の class が、 親 wrapper に
                       position: relative を持つかの簡易チェック (= J-8)

3 件まとめて 1 表で stdout に出す。 重複 / 誤検知が混じる前提で human filter を
通す。 git pre-commit には**入れない** (= 既存 W2 構造で大量に hit して noise に
なる、 修復時の sweep でだけ走らせる前提)。

Usage:
  python3 .tooling/local-ci/audit-w2-residue.py
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
SRC = REPO / "frontend" / "src"
ALLOWLIST_PATH = Path(__file__).with_name("audit-w2-residue-allowlist.txt")


# ---------------- helpers ----------------


def load_allowlist() -> set[tuple[str, str, str]]:
    """allowlist file から (audit, file, name) tuple set を返す。 line は無視 (= 0 扱い)."""
    out: set[tuple[str, str, str]] = set()
    if not ALLOWLIST_PATH.exists():
        return out
    for raw in ALLOWLIST_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(":", 3)
        if len(parts) < 4:
            continue
        audit, file, _line_no, name = parts[0], parts[1], parts[2], parts[3]
        out.add((audit, file, name))
    return out


def is_allowed(audit: str, finding: dict, allowlist: set) -> bool:
    return (audit, finding["file"], finding["name"]) in allowlist

def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def state_files() -> list[Path]:
    return sorted(p for p in (SRC / "state").glob("*.js")
                  if not p.name.startswith("_") and p.name not in {"_store.js"} and not p.name.endswith(".test.js"))


def feature_use_files() -> list[Path]:
    out: list[Path] = []
    for p in (SRC / "features").rglob("use*.js"):
        if p.name.endswith(".test.js"):
            continue
        out.append(p)
    return sorted(out)


def all_jsx_js_files() -> list[Path]:
    out: list[Path] = []
    for ext in ("*.js", "*.jsx"):
        for p in SRC.rglob(ext):
            if p.name.endswith(".test.js") or p.name.endswith(".test.jsx"):
                continue
            out.append(p)
    return sorted(out)


# ---------------- Audit A: 状態二重管理 ----------------

INITIAL_RE = re.compile(r"const\s+INITIAL\s*=\s*\{([^}]+)\}", re.S)
INITIAL_KEY_RE = re.compile(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:", re.M)
SETTER_RE = re.compile(r"^export\s+function\s+(set[A-Z][a-zA-Z0-9]*)\s*\(", re.M)
USESTATE_RE = re.compile(
    r"const\s+\[\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*,\s*(set[A-Z][a-zA-Z0-9_]*)\s*\]\s*=\s*useState\b"
)
USESYNC_RE = re.compile(
    r"useSyncExternalStore\s*\(\s*(?:subscribe\w*|[a-zA-Z_]\w*)\s*,"
)


def collect_store_surface() -> dict[str, dict]:
    """state/<x>.js の (store name) -> {initial_keys, setters} を集める."""
    out: dict[str, dict] = {}
    for f in state_files():
        name = f.stem  # ephemeral / sessions / ui / push / messages / persistence / transport
        src = read(f)
        # INITIAL のキー集合 (= top-level のみ、 ネストは判定弱め)
        m = INITIAL_RE.search(src)
        keys: set[str] = set()
        if m:
            for km in INITIAL_KEY_RE.finditer(m.group(1)):
                keys.add(km.group(1))
        setters = {sm.group(1) for sm in SETTER_RE.finditer(src)}
        out[name] = {"file": f, "keys": keys, "setters": setters}
    return out


def audit_a(stores: dict[str, dict]) -> list[dict]:
    findings: list[dict] = []
    for f in feature_use_files():
        src = read(f)
        for m in USESTATE_RE.finditer(src):
            name = m.group(1)
            setter = "set" + name[0].upper() + name[1:]
            line = src.count("\n", 0, m.start()) + 1
            # store-backed と同名か?
            matched_stores: list[str] = []
            for sname, surface in stores.items():
                if name in surface["keys"] or setter in surface["setters"]:
                    matched_stores.append(sname)
            if not matched_stores:
                continue
            # consumer 数 (= 別 file から store を subscribe してる箇所が複数あれば HIGH)
            risk = "MED"
            for sname in matched_stores:
                # その store を別 file が import してる数
                imp_re = re.compile(rf"from\s+['\"][^'\"]*state/{sname}\.js['\"]")
                consumers = 0
                for cand in all_jsx_js_files():
                    if cand == f or cand.parent == stores[sname]["file"].parent:
                        continue
                    csrc = read(cand)
                    if imp_re.search(csrc):
                        consumers += 1
                if consumers >= 1:
                    risk = "HIGH"
                    break
            findings.append({
                "file": str(f.relative_to(REPO)),
                "line": line,
                "name": name,
                "matched": ", ".join(matched_stores),
                "risk": risk,
            })
    return findings


# ---------------- Audit B: store-orphan ----------------

IMPORT_NAMED_RE = re.compile(r"import\s*\{([^}]+)\}\s*from\s*['\"]([^'\"]+)['\"]")


def audit_b(stores: dict[str, dict]) -> list[dict]:
    """state/<x>.js の export setter のうち、 features / layout で誰も import してない物."""
    # store ごとに「全 file で import される named symbols 集合」 を作る
    findings: list[dict] = []
    for sname, surface in stores.items():
        importers: set[str] = set()
        path_re = re.compile(rf"['\"][^'\"]*state/{sname}\.js['\"]")
        for f in all_jsx_js_files():
            if f == surface["file"]:
                continue
            src = read(f)
            if not path_re.search(src):
                continue
            for m in IMPORT_NAMED_RE.finditer(src):
                if f"state/{sname}.js" not in m.group(2):
                    continue
                for tok in m.group(1).split(","):
                    tok = tok.strip()
                    # `setLoading as storeSetLoading` -> setLoading
                    if " as " in tok:
                        tok = tok.split(" as ")[0].strip()
                    importers.add(tok)
        for setter in sorted(surface["setters"]):
            if setter not in importers:
                # 行番号取る
                m = re.search(rf"^export\s+function\s+{re.escape(setter)}\b",
                              read(surface["file"]), re.M)
                line = read(surface["file"]).count("\n", 0, m.start()) + 1 if m else 0
                findings.append({
                    "file": str(surface["file"].relative_to(REPO)),
                    "line": line,
                    "name": setter,
                    "matched": f"{sname}.{setter}",
                    "risk": "DEAD" if setter not in {"hydrate"} else "INFO",
                })
    return findings


# ---------------- Audit C: position-anchor ----------------

ABSOLUTE_RE = re.compile(r"^\s*\.([a-zA-Z][a-zA-Z0-9_-]*)\s*\{[^}]*position:\s*absolute", re.M | re.S)


def audit_c() -> list[dict]:
    findings: list[dict] = []
    # CSS の class -> file
    css_targets: list[tuple[str, Path, int]] = []
    for css in SRC.rglob("*.css"):
        src = read(css)
        for m in ABSOLUTE_RE.finditer(src):
            cls = m.group(1)
            line = src.count("\n", 0, m.start()) + 1
            css_targets.append((cls, css, line))

    # 各 class が JSX で使われてる component を grep し、 同じ file 内に
    # position: relative の class があるか (= 弱い heuristic) で判定
    jsx_files = [f for f in all_jsx_js_files() if f.suffix == ".jsx"]
    for cls, css, line in css_targets:
        used_in: list[Path] = []
        for jsx in jsx_files:
            jsx_src = read(jsx)
            if re.search(rf"className=[`'\"][^`'\"]*\b{re.escape(cls)}\b", jsx_src):
                used_in.append(jsx)
        if not used_in:
            continue
        # 同 css file 内に relative wrapper があるか
        css_src = read(css)
        relative_classes = re.findall(r"\.([a-zA-Z][a-zA-Z0-9_-]*)\s*\{[^}]*position:\s*relative",
                                      css_src, flags=re.S)
        if relative_classes:
            risk = "LOW"  # 同 css 内に relative wrapper 候補あり
        else:
            risk = "REVIEW"  # 同 css 内に relative 無し、 他 css/JSX 経由は要確認
        findings.append({
            "file": str(css.relative_to(REPO)),
            "line": line,
            "name": f".{cls}",
            "matched": f"used in: {', '.join(str(p.relative_to(REPO)) for p in used_in[:3])}",
            "risk": risk,
        })
    return findings


# ---------------- output ----------------

def print_section(title: str, items: list[dict]) -> None:
    print(f"\n=== {title} (= {len(items)} findings) ===")
    if not items:
        print("(none)")
        return
    print(f"{'risk':<7} {'file:line':<55} {'name':<28} {'matched'}")
    print("-" * 120)
    for it in sorted(items, key=lambda x: (x["risk"], x["file"], x.get("line", 0))):
        loc = f"{it['file']}:{it.get('line', 0)}"
        print(f"{it['risk']:<7} {loc:<55} {it['name']:<28} {it['matched']}")


def main() -> int:
    allowlist = load_allowlist()
    stores = collect_store_surface()
    print(f"# W2 residue audit — {len(stores)} state stores scanned, "
          f"{len(allowlist)} allowlist entries\n")
    for sname, surface in stores.items():
        print(f"  state/{sname}.js: {len(surface['keys'])} INITIAL keys, "
              f"{len(surface['setters'])} setter exports")

    raw_a = audit_a(stores)
    raw_b = audit_b(stores)
    raw_c = audit_c()

    # allowlist で suppress
    a = [f for f in raw_a if not is_allowed("A", f, allowlist)]
    b = [f for f in raw_b if not is_allowed("B", f, allowlist)]
    c = [f for f in raw_c if not is_allowed("C", f, allowlist)]
    suppressed = (len(raw_a) - len(a)) + (len(raw_b) - len(b)) + (len(raw_c) - len(c))

    print_section("Audit A: state double-management (= J-9 同型)", a)
    print_section("Audit B: store-orphan setter exports", b)
    print_section("Audit C: CSS position:absolute anchor (= J-8 同型 heuristic)", c)

    print(f"\n# summary: A={len(a)} / B={len(b)} / C={len(c)}  "
          f"(allowlist suppressed {suppressed})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
