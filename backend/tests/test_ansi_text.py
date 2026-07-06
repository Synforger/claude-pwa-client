"""ansi_text (= SGR 解析の pure primitives) の unit test。

tier B の ANSI 転換 (= 2026-07-07) の土台。 strip_ansi は「-e capture から plain を
導出する」 という loop の前提そのものなので、 行構造が保存されることを固定する。
"""
from __future__ import annotations

from backend.terminal.ansi_text import line_style_signatures, strip_ansi

CYAN = "\x1b[36m"
BOLD = "\x1b[1m"
RESET = "\x1b[0m"
FG_DEFAULT = "\x1b[39m"
FG256 = "\x1b[38;5;81m"


def test_strip_ansi_removes_sgr_and_other_escapes():
    ansi = f"{CYAN}❯ 1. Yes{RESET}\n  2. No\x1b[K\n\x1b]0;title\x07plain"
    assert strip_ansi(ansi) == "❯ 1. Yes\n  2. No\nplain"


def test_strip_ansi_preserves_line_count():
    ansi = f"a\n{BOLD}b\nc{RESET}\n\nd"
    assert len(strip_ansi(ansi).split("\n")) == len(ansi.split("\n"))


def test_line_style_signatures_basic():
    ansi = "\n".join([
        f"{CYAN}❯ 1. Yes{RESET}",   # styled
        "  2. No",                   # unstyled
        f"{BOLD}note{RESET}",        # styled (bold)
        "   ",                       # 可視文字なし → 空
    ])
    sigs = line_style_signatures(ansi)
    assert sigs[0] and "36" in sigs[0]
    assert sigs[1] == frozenset()
    assert sigs[2] == frozenset({"1"})
    assert sigs[3] == frozenset()


def test_line_style_signatures_state_persists_across_lines():
    # 行頭で SGR を再宣言しない capture 出力: 前行末で開いた色は次行にも効いている
    ansi = f"{CYAN}first\nsecond{RESET}\nthird"
    sigs = line_style_signatures(ansi)
    assert "36" in sigs[0]
    assert "36" in sigs[1]
    assert sigs[2] == frozenset()


def test_line_style_signatures_fg_default_clears_only_fg():
    ansi = f"{BOLD}{CYAN}x{FG_DEFAULT}y{RESET}"
    sigs = line_style_signatures(ansi)
    # x は bold+cyan、 y は bold のみ → 行集合は両方を含む
    assert sigs[0] == frozenset({"1", "36"})


def test_line_style_signatures_256_color_bundles():
    ansi = f"{FG256}sel{RESET}\nplain"
    sigs = line_style_signatures(ansi)
    assert sigs[0] == frozenset({"38;5;81"})
    assert sigs[1] == frozenset()
