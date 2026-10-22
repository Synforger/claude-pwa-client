"""ensure_tmux_resilience (= tmux server 強靭化) の契約 test。

subprocess は全部スタブ: 実 tmux を起こさず「どのコマンドを打ったか」だけ検証する
(= test_maintenance.py と同じ流儀)。
"""
import subprocess

from backend.terminal import runner


class _Recorder:
    def __init__(self, has_sentinel: bool, set_rc: int = 0):
        self.calls = []
        self.has_sentinel = has_sentinel
        self.set_rc = set_rc

    def __call__(self, args, capture_output=True, timeout=None, text=False):
        self.calls.append(list(args))
        if args[1] == "set":
            return subprocess.CompletedProcess(args, self.set_rc, "", "")
        if args[1] == "has-session":
            return subprocess.CompletedProcess(args, 0 if self.has_sentinel else 1, "", "")
        if args[1] == "new-session":
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.CompletedProcess(args, 0, "", "")


def test_sets_exit_empty_and_creates_sentinel_when_absent(monkeypatch):
    rec = _Recorder(has_sentinel=False)
    monkeypatch.setattr(runner.subprocess, "run", rec)
    runner.ensure_tmux_resilience()
    verbs = [c[1] for c in rec.calls]
    assert verbs == ["set", "has-session", "new-session"]
    assert rec.calls[0][2:] == ["-s", "exit-empty", "off"]
    assert runner.SENTINEL_SESSION in rec.calls[2]
    # 番兵が maintenance の掃除対象 (= pwa- prefix) に入らないことを名前で保証
    assert not runner.SENTINEL_SESSION.startswith("pwa-")


def test_idempotent_when_sentinel_alive(monkeypatch):
    rec = _Recorder(has_sentinel=True)
    monkeypatch.setattr(runner.subprocess, "run", rec)
    runner.ensure_tmux_resilience()
    verbs = [c[1] for c in rec.calls]
    assert verbs == ["set", "has-session"]


def test_survives_tmux_failure(monkeypatch, caplog):
    def boom(args, **kw):
        raise OSError("no tmux")
    monkeypatch.setattr(runner.subprocess, "run", boom)
    runner.ensure_tmux_resilience()  # 例外を漏らさない
