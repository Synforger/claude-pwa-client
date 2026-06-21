"""backend.pty_discover の unit test (= backend-F-24 psutil 化検証)。

旧 pgrep + ps + lsof の subprocess 連打を psutil 1 ループに置換した経路の振舞いを
カバーする。 実プロセスを起こすと環境依存になるので、 psutil.Process の minimal stub で
回路だけ確認する。
"""
from unittest.mock import MagicMock, patch

import pytest

import backend.pty_discover as pty_discover


class _FakeProc:
    """psutil.Process の最小 stub。 children() / name() / create_time() / cwd() のみ実装。"""
    def __init__(self, pid, name=None, children=None, create_time=0.0, cwd=None):
        self.pid = pid
        self._name = name or "zsh"
        self._children = children or []
        self._create_time = create_time
        self._cwd = cwd

    def name(self):
        return self._name

    def children(self):
        return list(self._children)

    def create_time(self):
        return self._create_time

    def cwd(self):
        return self._cwd


def test_find_claude_descendant_info_returns_first_claude(monkeypatch):
    """BFS で見つかった最初の claude (= name=='claude') を pid+start+cwd で返す。"""
    claude = _FakeProc(pid=42, name="claude", create_time=1000.0, cwd="/tmp/claude-cwd")
    zsh = _FakeProc(pid=10, name="zsh", children=[claude])
    root = _FakeProc(pid=1, name="zsh", children=[zsh])

    def fake_process(pid):
        if pid == 1:
            return root
        raise RuntimeError("unexpected pid")

    with patch.object(pty_discover.psutil, "Process", side_effect=fake_process):
        info = pty_discover._find_claude_descendant_info(1)
    assert info == (42, 1000.0, "/tmp/claude-cwd")


def test_find_claude_descendant_skips_non_claude(monkeypatch):
    """name basename != 'claude' は無視する。 BFS は深さ制限内で続行。"""
    nothing = _FakeProc(pid=5, name="bash")
    root = _FakeProc(pid=1, name="zsh", children=[nothing])
    with patch.object(pty_discover.psutil, "Process", return_value=root):
        info = pty_discover._find_claude_descendant_info(1)
    assert info is None


def test_find_claude_descendant_handles_path_in_name(monkeypatch):
    """name() が絶対 path 形式 (= '/usr/local/bin/claude') でも basename で判定する。"""
    claude = _FakeProc(
        pid=99, name="/usr/local/bin/claude", create_time=2000.0, cwd="/cwd"
    )
    root = _FakeProc(pid=1, children=[claude])
    with patch.object(pty_discover.psutil, "Process", return_value=root):
        info = pty_discover._find_claude_descendant_info(1)
    assert info is not None
    assert info[0] == 99


def test_find_claude_descendant_root_not_found(monkeypatch):
    """root pid が存在しなければ None。"""
    with patch.object(
        pty_discover.psutil, "Process",
        side_effect=pty_discover.psutil.NoSuchProcess(pid=999),
    ):
        info = pty_discover._find_claude_descendant_info(999)
    assert info is None


def test_find_claude_descendant_skips_when_cwd_missing(monkeypatch):
    """cwd() が None / 空文字なら skip して BFS 続行 (= claude プロセス即終了対策)。"""
    bad_claude = _FakeProc(pid=33, name="claude", create_time=1.0, cwd=None)
    root = _FakeProc(pid=1, children=[bad_claude])
    with patch.object(pty_discover.psutil, "Process", return_value=root):
        info = pty_discover._find_claude_descendant_info(1)
    # cwd None → skip → 他に candidate 無し → None
    assert info is None


def test_find_claude_descendant_compat_wrapper(monkeypatch):
    """find_claude_descendant は info wrapper として pid だけ返す (= 互換 API)。"""
    claude = _FakeProc(pid=7, name="claude", create_time=100.0, cwd="/x")
    root = _FakeProc(pid=1, children=[claude])
    with patch.object(pty_discover.psutil, "Process", return_value=root):
        pid = pty_discover.find_claude_descendant(1)
    assert pid == 7


def test_process_start_time_and_cwd_compat(monkeypatch):
    """process_start_time / process_cwd の互換 API 経路 (= psutil 直叩き)。"""
    proc = _FakeProc(pid=77, create_time=42.0, cwd="/some/where")
    with patch.object(pty_discover.psutil, "Process", return_value=proc):
        assert pty_discover.process_start_time(77) == 42.0
        assert pty_discover.process_cwd(77) == "/some/where"
