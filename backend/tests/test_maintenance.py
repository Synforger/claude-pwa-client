"""maintenance.restart_sunshine_if_bloated の判定分岐 + footprint parser の regression
+ cleanup_idle_pwa_sessions の閾値・attached/non-pwa 除外。

外部コマンド (pgrep / footprint / os.kill / tmux) は monkeypatch でスタブし、
「配信中はスキップ」「閾値未満はスキップ」「肥大化 + idle のみ kill」を固定する。
"""
import signal
import subprocess
import time

import maintenance as m


def test_footprint_parse_units():
    assert m._FOOTPRINT_RE.search("phys_footprint: 30 GB").groups() == ("30", "GB")
    assert m._FOOTPRINT_RE.search("    phys_footprint: 38 MB").groups() == ("38", "MB")


def _patch(monkeypatch, *, sunshine_pid, streamer_pid, footprint_bytes, killed):
    def fake_pgrep(pattern, *, exact=False):
        if "sunshine" in pattern:
            return sunshine_pid
        if "streamer" in pattern:
            return streamer_pid
        return None

    monkeypatch.setattr(m, "_pgrep_one", fake_pgrep)
    monkeypatch.setattr(m, "_phys_footprint_bytes", lambda pid: footprint_bytes)
    monkeypatch.setattr(m.os, "kill", lambda pid, sig: killed.append((pid, sig)))


def test_skip_when_sunshine_absent(monkeypatch):
    killed = []
    _patch(monkeypatch, sunshine_pid=None, streamer_pid=None,
           footprint_bytes=99 * 1024**3, killed=killed)
    assert m.restart_sunshine_if_bloated() is False
    assert killed == []


def test_skip_when_streaming(monkeypatch):
    """配信中 (= streamer 在席) は肥大化していても使用中ペアを壊さないため触らない。"""
    killed = []
    _patch(monkeypatch, sunshine_pid=100, streamer_pid=200,
           footprint_bytes=99 * 1024**3, killed=killed)
    assert m.restart_sunshine_if_bloated() is False
    assert killed == []


def test_skip_when_under_threshold(monkeypatch):
    killed = []
    _patch(monkeypatch, sunshine_pid=100, streamer_pid=None,
           footprint_bytes=m.SUNSHINE_FOOTPRINT_MAX_BYTES - 1, killed=killed)
    assert m.restart_sunshine_if_bloated() is False
    assert killed == []


def test_kill_when_bloated_and_idle(monkeypatch):
    killed = []
    _patch(monkeypatch, sunshine_pid=100, streamer_pid=None,
           footprint_bytes=m.SUNSHINE_FOOTPRINT_MAX_BYTES + 1, killed=killed)
    assert m.restart_sunshine_if_bloated() is True
    assert killed == [(100, signal.SIGKILL)]


def test_skip_when_footprint_unavailable(monkeypatch):
    killed = []
    _patch(monkeypatch, sunshine_pid=100, streamer_pid=None,
           footprint_bytes=None, killed=killed)
    assert m.restart_sunshine_if_bloated() is False
    assert killed == []


def _patch_tmux(monkeypatch, *, list_stdout, kill_calls):
    """tmux list-sessions の出力をスタブ、 kill-session 呼び出しを記録する。"""
    def fake_run(args, **kwargs):
        if args[:2] == ["tmux", "list-sessions"]:
            return subprocess.CompletedProcess(args, 0, stdout=list_stdout, stderr="")
        if args[:2] == ["tmux", "kill-session"]:
            kill_calls.append(args[3])  # -t <name>
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected subprocess call: {args}")

    monkeypatch.setattr(m.subprocess, "run", fake_run)


def test_idle_kill_only_pwa_non_attached_older_than_threshold(monkeypatch):
    now = time.time()
    fresh = now - 1 * 86400         # 1日前 → 残す
    stale = now - 10 * 86400        # 10日前 → kill
    list_stdout = "\n".join([
        f"pwa-ses_fresh\t0\t{fresh:.0f}",            # 非attached 新鮮 → 残す
        f"pwa-ses_stale\t0\t{stale:.0f}",            # 非attached 古い → kill
        f"pwa-ses_attached_stale\t1\t{stale:.0f}",   # attached なら古くても触らない
        f"other-session\t0\t{stale:.0f}",            # pwa-* でない → 触らない
    ]) + "\n"
    kill_calls: list[str] = []
    _patch_tmux(monkeypatch, list_stdout=list_stdout, kill_calls=kill_calls)
    assert m.cleanup_idle_pwa_sessions(idle_days=7) == 1
    assert kill_calls == ["pwa-ses_stale"]


def test_idle_kill_empty_list(monkeypatch):
    kill_calls: list[str] = []
    _patch_tmux(monkeypatch, list_stdout="", kill_calls=kill_calls)
    assert m.cleanup_idle_pwa_sessions(idle_days=7) == 0
    assert kill_calls == []


def test_idle_kill_tmux_timeout(monkeypatch):
    """tmux list-sessions が応答しない時は 0 件返して例外を漏らさない。"""
    def fake_run(args, **kwargs):
        raise subprocess.TimeoutExpired(args, 2.0)

    monkeypatch.setattr(m.subprocess, "run", fake_run)
    assert m.cleanup_idle_pwa_sessions(idle_days=7) == 0
