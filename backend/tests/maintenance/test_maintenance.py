"""cleanup_idle_pwa_sessions の閾値・attached/non-pwa 除外 + tmux format verify
(= backend-F-32) の unit test。

Sunshine restart / streamer ゾンビ reap は 2026-06-21 (backend-F-33) で backend
から外出し済 (= docs/troubleshooting/sunshine.md + LaunchAgent 別経路)、 そのため本
モジュールの旧 Sunshine 系 test は削除済み。
"""
import logging
import subprocess
import time

import backend.maintenance.maintenance as m


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


# ============================================================================
# backend-F-32: tmux list-sessions format verify + warn
# ============================================================================

def test_idle_kill_warns_on_unexpected_field_count(monkeypatch, caplog):
    """tmux 出力の field 数が期待値 (3) と違う行は skip + warn ログ。
    旧版は黙って skip するだけで tmux side の format 仕様変更を見逃す構造だった。
    """
    list_stdout = "pwa-ses_short\t0\n"  # field=2 (= 期待 3)
    kill_calls: list[str] = []
    _patch_tmux(monkeypatch, list_stdout=list_stdout, kill_calls=kill_calls)
    with caplog.at_level(logging.WARNING, logger=m.__name__):
        result = m.cleanup_idle_pwa_sessions(idle_days=7)
    assert result == 0
    assert kill_calls == []
    assert any("unexpected tmux list-sessions row" in rec.message for rec in caplog.records)


def test_idle_kill_warns_on_empty_session_name(monkeypatch, caplog):
    """field 数は正しいが session_name が空のケースも warn する。"""
    now = time.time()
    stale = now - 10 * 86400
    list_stdout = f"\t0\t{stale:.0f}\n"
    kill_calls: list[str] = []
    _patch_tmux(monkeypatch, list_stdout=list_stdout, kill_calls=kill_calls)
    with caplog.at_level(logging.WARNING, logger=m.__name__):
        result = m.cleanup_idle_pwa_sessions(idle_days=7)
    assert result == 0
    assert kill_calls == []
    assert any("suspicious session_name" in rec.message for rec in caplog.records)


# ============================================================================
# backend-F-33: Sunshine 関連 symbol は削除済
# ============================================================================

def test_sunshine_helpers_no_longer_present():
    """Sunshine restart / streamer ゾンビ reap は backend 外で管理する設計に
    切り替えた (= docs/troubleshooting/sunshine.md)。 backend module からは消えていること。"""
    for name in (
        "restart_sunshine_if_bloated",
        "_reap_zombie_streamers",
        "_has_live_streamer",
        "_phys_footprint_bytes",
        "_pgrep_one",
        "SUNSHINE_FOOTPRINT_MAX_BYTES",
        "STREAMER_ZOMBIE_SECONDS",
        "_FOOTPRINT_RE",
        "_FOOTPRINT_UNITS",
    ):
        assert not hasattr(m, name), f"backend-F-33: {name!r} should be removed"


def test_run_all_maintenance_no_sunshine_key(monkeypatch):
    """run_all_maintenance のサマリ dict にも restarted_sunshine は含まれない。"""
    # subprocess 系を全部 noop で安全に走らせる
    monkeypatch.setattr(m, "cleanup_stale_tmux_sessions", lambda: 0)
    monkeypatch.setattr(m, "cleanup_idle_pwa_sessions", lambda: 0)
    monkeypatch.setattr(m, "cleanup_stale_statusline_map", lambda: 0)
    monkeypatch.setattr(m, "cleanup_old_jsonl", lambda: 0)
    import backend.jsonl.session_status as ss
    monkeypatch.setattr(ss, "cleanup_orphan_turn_starts", lambda: 0)
    summary = m.run_all_maintenance()
    assert "restarted_sunshine" not in summary
    # 退役 / 新規追加した key を明示列挙する形で「黙って増えてない」 ことを担保する
    # (= event_journal_rotated は 2026-07-27 に journal 層ごと退役)。
    assert set(summary.keys()) == {
        "killed_tmux", "killed_idle_pwa", "removed_statusline_map",
        "removed_jsonl", "orphan_turn_starts",
    }


# --- A second backend on the same machine (a test build, a worktree) must not touch the first one's tabs ---

def test_stale_kill_leaves_everything_alone_without_tabs(monkeypatch):
    import backend._common.state as state
    kill_calls: list = []
    _patch_tmux(monkeypatch, list_stdout="pwa-ses_live\npwa-ses_other\n", kill_calls=kill_calls)
    monkeypatch.setattr(state, "sessions_meta", {})
    assert m.cleanup_stale_tmux_sessions() == 0
    assert kill_calls == []


def test_stale_kill_still_kills_sessions_missing_from_its_tabs(monkeypatch):
    import backend._common.state as state
    kill_calls: list = []
    _patch_tmux(monkeypatch, list_stdout="pwa-ses_kept\npwa-ses_gone\nclaudepwa-sentinel\n", kill_calls=kill_calls)
    monkeypatch.setattr(state, "sessions_meta", {"ses_kept": object()})
    assert m.cleanup_stale_tmux_sessions() == 1
    assert kill_calls == ["pwa-ses_gone"]


def _old_transcripts(tmp_path, names):
    """A projects folder holding transcripts last written 30 days ago."""
    project = tmp_path / "projects" / "-x"
    project.mkdir(parents=True)
    old = time.time() - 30 * 86400
    for name in names:
        path = project / name
        path.write_text("{}\n")
        import os
        os.utime(path, (old, old))
    return project


def test_jsonl_gc_deletes_nothing_without_a_bound_tab(monkeypatch, tmp_path):
    import backend.jsonl.jsonl_watcher as watcher
    project = _old_transcripts(tmp_path, ["a.jsonl", "b.jsonl"])
    monkeypatch.setattr(m._config, "CLAUDE_PROJECTS_DIRS", [tmp_path / "projects"])
    monkeypatch.setattr(watcher, "list_bindings", lambda: {})
    assert m.cleanup_old_jsonl(keep_days=14, max_bytes=10**12) == 0
    assert sorted(p.name for p in project.iterdir()) == ["a.jsonl", "b.jsonl"]


def test_jsonl_gc_deletes_old_unbound_transcripts_when_it_sees_a_bound_tab(monkeypatch, tmp_path):
    import backend.jsonl.jsonl_watcher as watcher
    project = _old_transcripts(tmp_path, ["bound.jsonl", "old.jsonl"])
    monkeypatch.setattr(m._config, "CLAUDE_PROJECTS_DIRS", [tmp_path / "projects"])
    monkeypatch.setattr(watcher, "list_bindings",
                        lambda: {"ses_a": {"confirmed": True, "jsonl_path": str(project / "bound.jsonl")}})
    assert m.cleanup_old_jsonl(keep_days=14, max_bytes=10**12) == 1
    assert sorted(p.name for p in project.iterdir()) == ["bound.jsonl"]


def test_tmux_socket_is_one_per_platform_root(tmp_path):
    from backend.terminal import runner
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    assert runner.platform_socket_name(None) is None
    assert runner.platform_socket_name("  ") is None
    assert runner.platform_socket_name(str(first)) == runner.platform_socket_name(str(first) + "/")
    assert runner.platform_socket_name(str(first)) != runner.platform_socket_name(str(second))
    assert runner.platform_socket_name(str(first)).startswith("agent-platform-")
