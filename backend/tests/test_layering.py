"""backend の層一方向性を守る機械 gate。

依存方向の真値 (= この test が法律):

    L0: config / paths / errors / state / observability / _generated / core
    L1: terminal   (= tmux / PTY の入力口。 L0 のみ import 可)
    L2: jsonl      (= JSONL tail → SSE の出力口。 L0 / L1 を import 可)
    L3: routes / maintenance / main / cli   (= orchestrator。 全層 import 可)

歴史: jsonl ↔ terminal が相互 import で双方向結合し、 同じ状態を両側から書く構造が
busy 誤表示 / 二重 spawn TOCTOU 系 bug の温床だった (= 2026-07-05 audit の層もつれ)。
共有純粋プリミティブ (jsonl_tail / jsonl_predicates) と共有 registry (jsonl_watcher)
を core へ降ろして一方向化した。 新しい共有が必要になったら core に置く — 逆流 import
を書いた時点でこの test が落ちる。

module-level / function-level どちらの import も AST で拾う (= 遅延 import でも層違反は
層違反。 実行タイミングの問題ではなく所有権の問題)。
"""
from __future__ import annotations

import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]

# 第 1 階層 (= backend/<名前>) → 層番号。 file module (config.py 等) と package
# (core/ 等) を同列に扱う。
LEVELS: dict[str, int] = {
    "config": 0,
    "paths": 0,
    "errors": 0,
    "state": 0,
    "observability": 0,
    "_generated": 0,
    "core": 0,
    "terminal": 1,
    "jsonl": 2,
    "routes": 3,
    "maintenance": 3,
    "main": 3,
    "cli": 3,
}


def _iter_backend_modules():
    for f in BACKEND_ROOT.rglob("*.py"):
        parts = f.relative_to(BACKEND_ROOT).parts
        if parts[0] in ("tests", "__pycache__"):
            continue
        top = parts[0].removesuffix(".py")
        if top == "__init__":
            continue
        yield f, top


def _imported_backend_tops(tree: ast.AST):
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        for mod in names:
            parts = mod.split(".")
            if parts[0] != "backend" or len(parts) < 2:
                continue
            yield parts[1], getattr(node, "lineno", 0)


def test_every_backend_module_has_a_layer():
    """新 package / 新 top-level module は LEVELS への登録必須 (= 層無所属を作らない)。"""
    unknown = sorted({top for _, top in _iter_backend_modules() if top not in LEVELS})
    assert not unknown, (
        f"layer 未定義の backend module: {unknown} — test_layering.LEVELS に層を宣言してください"
    )


def test_no_upward_imports():
    """下位層から上位層への import (= 逆流) を全 module / 全 import 形態で禁止する。"""
    violations: list[str] = []
    for f, top in _iter_backend_modules():
        my_level = LEVELS.get(top)
        if my_level is None:
            continue  # test_every_backend_module_has_a_layer が別途落とす
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for target_top, lineno in _imported_backend_tops(tree):
            target_level = LEVELS.get(target_top)
            if target_level is None:
                continue
            if target_level > my_level:
                violations.append(
                    f"{f.relative_to(BACKEND_ROOT.parent)}:{lineno}: "
                    f"L{my_level}({top}) → L{target_level}({target_top})"
                )
    assert not violations, "層の逆流 import:\n  " + "\n  ".join(violations)
