"""backend/core/jsonl_tail.py の unit test (= initial_offset の移送 + 厚いカバレッジ、 F-41)。

旧 jsonl/routes._initial_offset を tail.initial_offset に移送した。 routes 内に閉じて
いた頃は INITIAL_REPLAY_LINES (= 500) 固定値ベースの test しか無かったが、 移送後は
max_lines を引数で受けるので boundary を細かく検査する。
"""
from backend.core import jsonl_tail as jt


def _write_lines(p, n, prefix="L"):
    p.write_bytes(b"".join(f"{prefix}{i}\n".encode() for i in range(n)))


def test_initial_offset_zero_for_empty_file(tmp_path):
    p = tmp_path / "a.jsonl"
    p.write_bytes(b"")
    assert jt.initial_offset(p, 10) == 0


def test_initial_offset_zero_when_lines_below_max(tmp_path):
    p = tmp_path / "a.jsonl"
    _write_lines(p, 5)
    assert jt.initial_offset(p, 10) == 0


def test_initial_offset_zero_at_exact_boundary(tmp_path):
    """改行数 == max_lines は count <= max_lines 規約で 0 (= 全件 replay)。 旧実装と
    同じ境界。"""
    p = tmp_path / "a.jsonl"
    _write_lines(p, 10)
    assert jt.initial_offset(p, 10) == 0


def test_initial_offset_keeps_last_n_minus_1_when_over(tmp_path):
    """count > max_lines 時は「末尾から max_lines 個目の改行直後」 を返す。
    = 末尾 max_lines - 1 行を replay する旧 off-by-one を踏襲。"""
    p = tmp_path / "a.jsonl"
    total = 100
    n = 50
    _write_lines(p, total)
    off = jt.initial_offset(p, n)
    assert off > 0
    lines, _ = jt.read_complete_lines(p, off)
    assert len(lines) == n - 1
    assert lines[0] == f"L{total - (n - 1)}"
    assert lines[-1] == f"L{total - 1}"


def test_initial_offset_missing_file_returns_zero(tmp_path):
    assert jt.initial_offset(tmp_path / "nope.jsonl", 10) == 0


def test_initial_offset_handles_long_lines_across_chunks(tmp_path):
    """改行を持つ長い行が chunk boundary をまたぐケースで境界を正しく検出する。
    chunk_size = 64KB なので 70KB の 1 行 + 短い末尾行で boundary 跨ぎを誘発する。"""
    p = tmp_path / "a.jsonl"
    long_line = b"x" * 70_000 + b"\n"
    p.write_bytes(long_line + b"short1\n" + b"short2\n" + b"short3\n")
    # max_lines=2 → 改行 4 個 > 2 → 「末尾から 2 個目の改行直後」 = "short3" 先頭。
    # 旧 _initial_offset の off-by-one 規約 (= 末尾 N-1 行 replay) を踏襲。
    off = jt.initial_offset(p, 2)
    lines, _ = jt.read_complete_lines(p, off)
    assert lines == ["short3"]


def test_initial_offset_only_newlines(tmp_path):
    """空行だけ (= "\\n\\n\\n\\n") でも改行数で正しく数える。"""
    p = tmp_path / "a.jsonl"
    p.write_bytes(b"\n" * 20)
    off = jt.initial_offset(p, 5)
    # 改行 20 個 > 5 → 末尾から 5 個目の改行直後 = byte 16
    assert off == 16


# --- routes._initial_offset wrapper は INITIAL_REPLAY_LINES (= 500) を渡す ---

def test_routes_initial_offset_wrapper_delegates(tmp_path):
    """routes._initial_offset が tail.initial_offset(path, INITIAL_REPLAY_LINES) を
    呼ぶことを担保 (= 旧 test_jsonl_routes との互換性)。"""
    import backend.jsonl.routes as jr
    p = tmp_path / "a.jsonl"
    _write_lines(p, jr.INITIAL_REPLAY_LINES + 10)
    # wrapper / 直接呼びで同じ off を返す
    assert jr._initial_offset(p) == jt.initial_offset(p, jr.INITIAL_REPLAY_LINES)


# --- read_complete_lines_with_pos (= per-line byte pos、 SSE id 前進の土台) ---

def test_with_pos_returns_per_line_end_positions(tmp_path):
    """各行の pos は「その行 (+ 改行) を読み終えた byte 位置」。 最終行の pos == new_pos。"""
    p = tmp_path / "a.jsonl"
    p.write_bytes(b'{"a":1}\n{"bb":2}\n')
    pairs, new_pos = jt.read_complete_lines_with_pos(p, 0)
    assert [ln for ln, _ in pairs] == ['{"a":1}', '{"bb":2}']
    assert pairs[0][1] == 8            # len('{"a":1}') + 1
    assert pairs[1][1] == 17           # 8 + len('{"bb":2}') + 1
    assert new_pos == 17
    assert pairs[-1][1] == new_pos


def test_with_pos_multibyte_utf8_positions_are_bytes(tmp_path):
    """pos は文字数でなく byte 数 (= マルチバイト日本語行でずれない)。"""
    p = tmp_path / "a.jsonl"
    line = '{"t":"日本語"}'.encode("utf-8")
    p.write_bytes(line + b"\n" + b'{"x":1}\n')
    pairs, new_pos = jt.read_complete_lines_with_pos(p, 0)
    assert pairs[0][1] == len(line) + 1
    assert new_pos == len(line) + 1 + 8


def test_with_pos_partial_trailing_line_not_consumed(tmp_path):
    """書き込み途中の不完全行は返らず pos も進まない (= read_complete_lines と同じ規約)。"""
    p = tmp_path / "a.jsonl"
    p.write_bytes(b'{"a":1}\n{"incomplete"')
    pairs, new_pos = jt.read_complete_lines_with_pos(p, 0)
    assert [ln for ln, _ in pairs] == ['{"a":1}']
    assert new_pos == 8


def test_with_pos_skips_blank_lines_but_advances_pos(tmp_path):
    """空行は行 list に入らないが、 後続行の pos は空行分も前進している。"""
    p = tmp_path / "a.jsonl"
    p.write_bytes(b"\n\n" + b'{"a":1}\n')
    pairs, new_pos = jt.read_complete_lines_with_pos(p, 0)
    assert [ln for ln, _ in pairs] == ['{"a":1}']
    assert pairs[0][1] == 10
    assert new_pos == 10


def test_plain_wrappers_delegate_to_with_pos(tmp_path):
    """read_complete_lines / read_tail は with_pos 版の薄い wrapper (= 二重実装しない)。"""
    p = tmp_path / "a.jsonl"
    p.write_bytes(b'{"a":1}\n{"b":2}\n')
    lines, new_pos = jt.read_complete_lines(p, 0)
    pairs, new_pos2 = jt.read_complete_lines_with_pos(p, 0)
    assert lines == [ln for ln, _ in pairs]
    assert new_pos == new_pos2
    tl, tp, ts = jt.read_tail(p, 0)
    twl, twp, tws = jt.read_tail_with_pos(p, 0)
    assert tl == [ln for ln, _ in twl]
    assert (tp, ts) == (twp, tws)
