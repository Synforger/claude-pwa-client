"""ADR-012 backend silent `except: pass` audit。

設計書 04-w3 § 完了判定 § 4 の repo 内実装 (= repo 外の scripts でなく backend pytest 寄せ、
ADR-017 に従う形)。 AST で全 except handler を走査し、 body が `pass` のみ (= silent swallow)
かつ前後に `# benign:` marker がない箇所を違反として列挙する。

許容 marker:
    - handler 行末 / 直前行 / 直後 2 行のいずれかに `# benign:` が含まれていれば silent OK
    - 例: `except Exception:  # benign: caller already retries`
    - 例: `# benign: best-effort cleanup\nexcept Exception: pass`

許容しない:
    - 素の `except Exception: pass`
    - 多段の `except: pass`

許容範囲外の見落とし対策 (= 「log を入れて欲しいのに silent」 を防ぐ):
    - logger.* 呼出は body の statement にあれば自動で「silent でない」 と判定される
    - benign 判定は marker comment が必須、 author が場面ごとに why を書く義務
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_DIR = REPO_ROOT / "backend"


def _find_silent_except_handlers() -> list[tuple[Path, ast.ExceptHandler, list[str]]]:
    """backend/ 配下の .py を AST で走査、 body が `pass` のみの ExceptHandler を返す。

    tests/ 配下は除外 (= test 内の silent pass は intentional な fixture / smoke 用に許容)。
    """
    found: list[tuple[Path, ast.ExceptHandler, list[str]]] = []
    for py in sorted(BACKEND_DIR.rglob("*.py")):
        if "/tests/" in str(py):
            continue
        try:
            source_lines = py.read_text(encoding="utf-8").splitlines()
            tree = ast.parse("\n".join(source_lines))
        except (SyntaxError, OSError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            body = node.body
            if body and all(isinstance(s, ast.Pass) for s in body):
                found.append((py, node, source_lines))
    return found


def _has_benign_marker(source_lines: list[str], lineno: int) -> bool:
    """handler の行 ± 周辺 (= 直前行〜直後 2 行) に `# benign:` comment があるか。"""
    start = max(0, lineno - 2)  # 0-indexed 換算で 1 行前を含める
    end = min(len(source_lines), lineno + 2)
    window = "\n".join(source_lines[start:end])
    return "# benign:" in window


def test_no_silent_except_pass_without_benign_marker():
    """silent `except: pass` は `# benign: <reason>` を必ず添える。"""
    violations: list[str] = []
    for path, node, source_lines in _find_silent_except_handlers():
        if not _has_benign_marker(source_lines, node.lineno):
            violations.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
    assert violations == [], (
        "silent `except: pass` (or `except Exception: pass`) found without `# benign: <reason>` comment.\n"
        "Either add a benign marker explaining why swallowing is intentional, or replace with a logger.* call.\n"
        "Violations:\n  " + "\n  ".join(violations)
    )


def test_finder_picks_up_known_silent_pattern(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """audit ロジック自体の smoke: 故意に silent pattern を作って検出されるか確認。"""
    fake_pkg = tmp_path / "backend"
    fake_pkg.mkdir()
    sample = fake_pkg / "sample.py"
    sample.write_text(
        "def f():\n"
        "    try:\n"
        "        do()\n"
        "    except Exception:\n"
        "        pass\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("backend.tests.observability.test_except_audit.BACKEND_DIR", fake_pkg)
    found = _find_silent_except_handlers()
    assert any(str(p).endswith("sample.py") for p, _, _ in found)


def test_finder_skips_handler_with_log_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """body に statement (= 例えば logger.exception()) があれば silent 判定対象外。"""
    fake_pkg = tmp_path / "backend"
    fake_pkg.mkdir()
    sample = fake_pkg / "sample.py"
    sample.write_text(
        "import logging\n"
        "logger = logging.getLogger('x')\n"
        "def f():\n"
        "    try:\n"
        "        do()\n"
        "    except Exception:\n"
        "        logger.exception('failed')\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("backend.tests.observability.test_except_audit.BACKEND_DIR", fake_pkg)
    found = _find_silent_except_handlers()
    assert not any(str(p).endswith("sample.py") for p, _, _ in found)


def test_benign_marker_recognized(tmp_path: Path):
    """`# benign:` marker は handler 行 + 前後行のどこにあっても認識される。"""
    src = [
        "def f():",
        "    try:",
        "        do()",
        "    except Exception:  # benign: cleanup race",
        "        pass",
    ]
    assert _has_benign_marker(src, lineno=4) is True


def test_benign_marker_recognized_above_handler(tmp_path: Path):
    src = [
        "def f():",
        "    try:",
        "        do()",
        "    # benign: cleanup race",
        "    except Exception:",
        "        pass",
    ]
    assert _has_benign_marker(src, lineno=5) is True
