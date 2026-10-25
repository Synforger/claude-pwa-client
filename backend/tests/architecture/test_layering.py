"""backend の層一方向性を守る機械 gate。

依存方向の真値 (= この test が法律):

    L0: _common / _internal / observability / _generated / documents / push / speech / usage / fork
        + jsonl の共有部品 (jsonl_tail / jsonl_predicates / jsonl_watcher)
    L1: terminal   (= tmux / PTY の入力口。 L0 のみ import 可)
    L2: jsonl      (= JSONL tail → SSE の出力口。 L0 / L1 を import 可)
    L3: routes / maintenance / rollover / main / cli / voice_call / device   (= orchestrator。 全層 import 可)

歴史: jsonl ↔ terminal が相互 import で双方向結合し、 同じ状態を両側から書く構造が
busy 誤表示 / 二重 spawn TOCTOU 系 bug の温床だった (= 2026-07-05 audit の層もつれ)。
共有純粋プリミティブ (jsonl_tail / jsonl_predicates) と共有 registry (jsonl_watcher)
を L0 に置いて一方向化した。 新しい共有が必要になったら L0 の folder に置く — 逆流 import
を書いた時点でこの test が落ちる。

module-level / function-level どちらの import も AST で拾う (= 遅延 import でも層違反は
層違反。 実行タイミングの問題ではなく所有権の問題)。
"""
from __future__ import annotations

import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]

# backend 配下の module (= `backend/` からの dotted 名) → 層番号。 最も長く一致した名前の層が効く
# (= `jsonl` は L2 だが、 `jsonl.jsonl_tail` は L0)。
LEVELS: dict[str, int] = {
    "_common": 0,
    "_internal": 0,
    "observability": 0,
    "_generated": 0,
    "documents": 0,
    "push": 0,
    "speech": 0,
    "usage": 0,
    "fork": 0,
    "jsonl.jsonl_tail": 0,
    "jsonl.jsonl_predicates": 0,
    "jsonl.jsonl_watcher": 0,
    "terminal": 1,
    "tier_tabs.envelope": 1,
    "jsonl": 2,
    "routes": 3,
    "maintenance": 3,
    "rollover": 3,
    "tier_tabs": 3,
    "main": 3,
    "cli": 3,
    "voice_call": 3,
    "device": 3,
}


def _level_of(module: str) -> tuple[str, int] | None:
    parts = module.split(".")
    for size in range(len(parts), 0, -1):
        name = ".".join(parts[:size])
        if name in LEVELS:
            return name, LEVELS[name]
    return None


def _iter_backend_modules():
    for f in BACKEND_ROOT.rglob("*.py"):
        parts = f.relative_to(BACKEND_ROOT).parts
        if parts[0] in ("tests", "__pycache__"):
            continue
        parts = (*parts[:-1], f.stem)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if not parts:
            continue
        yield f, ".".join(parts)


def _imported_backend_modules(tree: ast.AST):
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module, *(f"{node.module}.{a.name}" for a in node.names)]
        for mod in names:
            parts = mod.split(".")
            if parts[0] != "backend" or len(parts) < 2:
                continue
            yield ".".join(parts[1:]), getattr(node, "lineno", 0)


def test_every_backend_module_has_a_layer():
    """新 package / 新 top-level module は LEVELS への登録必須 (= 層無所属を作らない)。"""
    unknown = sorted({module.split(".")[0] for _, module in _iter_backend_modules() if _level_of(module) is None})
    assert not unknown, (
        f"layer 未定義の backend module: {unknown} — test_layering.LEVELS に層を宣言してください"
    )


def test_no_upward_imports():
    """下位層から上位層への import (= 逆流) を全 module / 全 import 形態で禁止する。"""
    violations: list[str] = []
    for f, module in _iter_backend_modules():
        mine = _level_of(module)
        if mine is None:
            continue  # test_every_backend_module_has_a_layer が別途落とす
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for target_module, lineno in _imported_backend_modules(tree):
            target = _level_of(target_module)
            if target is None:
                continue
            if target[1] > mine[1]:
                violations.append(
                    f"{f.relative_to(BACKEND_ROOT.parent)}:{lineno}: "
                    f"L{mine[1]}({mine[0]}) → L{target[1]}({target[0]})"
                )
    assert not violations, "層の逆流 import:\n  " + "\n  ".join(violations)
