"""サスティナビリティ維持タスク群: stale tmux session kill / 古い JSONL 削除 /
statusline map cleanup。 backend lifespan task の起動時 + 定期実行で呼ばれる。

恒久的に増えていくリソース (= 放置すると無限蓄積する) を機械的に整理する箇所。
backend logs (RotatingFileHandler) / uploads/tmp (1h GC) は別経路で既対策済み、
このモジュールは以下を担当:

  1. PWA タブ削除後の残骸 tmux session の kill
  2. 古い JSONL ファイル (~/.claude/projects/) の自動削除 (mtime + quota)
  3. 古い statusline map ファイルの削除 (対応 tmux session 無いもの)

2026-06-21 (backend-F-33): Sunshine restart / streamer ゾンビ reap の管理を
backend から完全に切り離した。 backend が画面共有 daemon の生死管理を担うの
は責務違反 (= claude 経路と無関係、 別マシンで backend を動かす運用が阻害)
だったため、 `docs/sunshine-runbook.md` の運用手順 + LaunchAgent watchdog に
外出し。 旧 `restart_sunshine_if_bloated` / `_reap_zombie_streamers` /
`_has_live_streamer` / `_phys_footprint_bytes` / `_pgrep_one` /
`SUNSHINE_FOOTPRINT_MAX_BYTES` / `STREAMER_ZOMBIE_SECONDS` / `_FOOTPRINT_RE`
/ `_FOOTPRINT_UNITS` は本 file から削除済み。
"""
from __future__ import annotations

import asyncio
import logging
import subprocess
import time
from pathlib import Path

import backend.config as _config

logger = logging.getLogger(__name__)


# 保持基準: mtime が KEEP_DAYS 日以内 = 残す、 それより古いものは削除候補。
# 加えて、 残った合計が MAX_BYTES を超える場合は古い方から削除して quota 内に収める。
# 実機観測 (2026-06-04) で 468MB / 168 ファイルまで蓄積していたので、 quota を 500MB に
# 引き下げて 24h ループで効くようにする (= 旧 1GB 設定だと threshold まで届かず KEEP_DAYS
# だけが効いていて、 mtime 新しめのファイルが溜まり続けていた)。 KEEP_DAYS も 30→14 に
# 短縮、 普段の試行錯誤履歴は十分カバーしつつ蓄積速度を半分にする。
JSONL_KEEP_DAYS = 14
JSONL_MAX_BYTES = 500 * 1024 * 1024  # 500 MB
# 定期実行間隔。 起動時に 1 回 + この間隔で繰り返し。 24h → 12h に短縮して quota 超過の
# 滞留時間を半減する (= 上の threshold 改定とセット)。
MAINTENANCE_INTERVAL_SEC = 12 * 3600

# アイドル pwa-* tmux session を kill する閾値。 session_attached=0 かつ session_activity が
# この日数より古ければ tmux session (+ 配下の claude プロセス) を kill する。 sessions_meta
# は触らないので PWA のタブ一覧には残り、 次にタブを開いた時に新規 spawn される (= 「使わない
# けどタブだけ残しておく」 運用に合わせた設計)。 7→5 日に短縮、 claude プロセス 1 個あたり
# RSS 100-300MB を抱えるので長期累積を抑える。
IDLE_SESSION_KILL_DAYS = 5

# tmux list-sessions -F の format token 数。 不一致なら format 仕様が変わったか、
# tmux side が想定外の出力 (= 改行混じり session_name 等) を吐いている (= backend-F-32)。
_TMUX_IDLE_LIST_FIELDS = 3


def cleanup_stale_tmux_sessions() -> int:
    """sessions_meta に登録されていない pwa-ses_* tmux session を kill する。
    PWA タブを UI から削除した時点で sessions_meta から消えるが、 backend 経路を経ずに
    削除されたケース (= 旧バックエンドの残骸 / 手動削除) で tmux session だけ残るのを掃除。"""
    try:
        from backend.state import sessions_meta
    except ImportError:
        return 0
    try:
        r = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            capture_output=True, text=True, timeout=2.0,
        )
    except (subprocess.TimeoutExpired, OSError):
        return 0
    if r.returncode != 0:
        return 0
    killed = 0
    for name in r.stdout.splitlines():
        if not name.startswith("pwa-"):
            continue
        sid = name[4:]  # "pwa-ses_xxx" → "ses_xxx"
        if sid in sessions_meta:
            continue
        try:
            subprocess.run(
                ["tmux", "kill-session", "-t", name],
                capture_output=True, timeout=2.0,
            )
            logger.info("maintenance: killed stale tmux session %s", name)
            killed += 1
        except (subprocess.TimeoutExpired, OSError):
            pass
    return killed


def cleanup_idle_pwa_sessions(idle_days: int = IDLE_SESSION_KILL_DAYS) -> int:
    """非 attached の pwa-* tmux session のうち、 最終 activity が idle_days より古いものを
    kill する。 sessions_meta は触らず PWA のタブ一覧には残す (= 次回 open で再 spawn される)。
    アイドル claude プロセスが RSS 100-300MB を抱えたまま無期限に残るのを防ぐ。"""
    try:
        r = subprocess.run(
            ["tmux", "list-sessions",
             "-F", "#{session_name}\t#{session_attached}\t#{session_activity}"],
            capture_output=True, text=True, timeout=2.0,
        )
    except (subprocess.TimeoutExpired, OSError):
        return 0
    if r.returncode != 0:
        return 0
    cutoff = time.time() - idle_days * 86400
    killed = 0
    for line in r.stdout.splitlines():
        parts = line.split("\t")
        # backend-F-32: tmux list-sessions の format 解釈ガード。 旧版は黙って
        # skip するだけだったので tmux 側の format 仕様変更を観測できなかった。
        # 個数違いは warn ログに残し、 fmt 監視の入口を作る。
        if len(parts) != _TMUX_IDLE_LIST_FIELDS:
            logger.warning(
                "maintenance: unexpected tmux list-sessions row (fields=%d, expected=%d): %r",
                len(parts), _TMUX_IDLE_LIST_FIELDS, line,
            )
            continue
        name, attached, activity_str = parts
        # session 名 sanity: 空文字 / 改行混入は format 破綻のサイン
        if not name or "\n" in name:
            logger.warning(
                "maintenance: tmux list-sessions returned suspicious session_name %r",
                name,
            )
            continue
        if not name.startswith("pwa-"):
            continue
        if attached != "0":
            continue
        try:
            activity = float(activity_str)
        except ValueError:
            continue
        if activity >= cutoff:
            continue
        try:
            subprocess.run(
                ["tmux", "kill-session", "-t", name],
                capture_output=True, timeout=2.0,
            )
            logger.info(
                "maintenance: killed idle pwa session %s (idle=%.1fd)",
                name, (time.time() - activity) / 86400,
            )
            killed += 1
        except (subprocess.TimeoutExpired, OSError):
            pass
    return killed


def cleanup_stale_statusline_map() -> int:
    """設定で指定された statusline の tmux-session-map ディレクトリから、 対応する
    tmux session が既に存在しない pwa-* エントリを削除する。 statusline スクリプトが
    書く map ファイルが tmux session 終了後も残り続けるので、 起動時に整理する。"""
    map_dir_raw = _config.TMUX_SESSION_MAP_DIR
    if not map_dir_raw:
        return 0
    map_dir = Path(map_dir_raw).expanduser()
    if not map_dir.is_dir():
        return 0
    try:
        r = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            capture_output=True, text=True, timeout=2.0,
        )
    except (subprocess.TimeoutExpired, OSError):
        return 0
    existing = set(r.stdout.splitlines()) if r.returncode == 0 else set()
    removed = 0
    for f in map_dir.iterdir():
        if not f.is_file() or not f.name.startswith("pwa-"):
            continue
        if f.name in existing:
            continue
        try:
            f.unlink()
            logger.info("maintenance: removed stale statusline map %s", f.name)
            removed += 1
        except OSError:
            pass
    return removed


def cleanup_old_jsonl(
    keep_days: int = JSONL_KEEP_DAYS,
    max_bytes: int = JSONL_MAX_BYTES,
) -> int:
    """~/.claude/projects/*/*.jsonl を mtime 順で整理する。

    1. mtime が keep_days 日以前のものを削除 (= ただし現在 PWA タブが bind 中の jsonl は除く)
    2. それでも全体合計が max_bytes を超える場合は更に古い方から削除して quota 内に収める

    quota は project 単位でなく全 project の合計で見る (= project 数だけ掛け算で蓄積するのを防ぐ)。
    binding 中の jsonl は長期 idle でも削除しない (= backend 再起動 / Mac 再起動跨ぎで復帰した
    アクティブセッションが「14 日無書き込み」 で削除される事故を塞ぐ)。

    claude CLI の会話ログは turn ごとに append され、 /clear で新ファイルが切られるが、
    自動 cleanup が無いので無限に蓄積する (= 実機で 468 MB / 168 ファイルの蓄積を確認)。

    複数アカウント (= ACCOUNTS で CLAUDE_CONFIG_DIR を指定) の場合は、 各アカウントの
    projects dir を全部対象に走査する (= quota は全アカウント合計で見る)。
    """
    bases = [b for b in _config.CLAUDE_PROJECTS_DIRS if b.is_dir()]
    if not bases:
        return 0
    # 現在 PWA タブが bind 中の jsonl は idle でも保護する。
    bound_paths: set[str] = set()
    try:
        import backend.jsonl.watcher as jsonl_watcher  # noqa: PLC0415
        for info in jsonl_watcher.list_bindings().values():
            jp = info.get("jsonl_path")
            if info.get("confirmed") and jp:
                bound_paths.add(str(Path(jp).resolve()))
    except Exception:
        logger.exception("jsonl gc: failed to collect bound paths")
    cutoff = time.time() - keep_days * 86400
    deleted = 0
    # 全 project を 1 リストに集約 (= quota は全体合計で見る)
    all_files: list[tuple[Path, float, int]] = []
    for base in bases:
        for proj_dir in base.iterdir():
            if not proj_dir.is_dir():
                continue
            for f in proj_dir.glob("*.jsonl"):
                try:
                    st = f.stat()
                    all_files.append((f, st.st_mtime, st.st_size))
                except OSError:
                    continue
    all_files.sort(key=lambda x: x[1])  # mtime 古い順
    # Step 1: keep_days より古いものを削除 (bound は除外)
    survivors: list[tuple[Path, float, int]] = []
    for f, mt, sz in all_files:
        if str(f.resolve()) in bound_paths:
            survivors.append((f, mt, sz))
            continue
        if mt < cutoff:
            try:
                f.unlink()
                deleted += 1
                logger.info(
                    "jsonl gc: removed by age %s (age=%.1fd, size=%dKB)",
                    f.name, (time.time() - mt) / 86400, sz // 1024,
                )
                continue
            except OSError:
                pass
        survivors.append((f, mt, sz))
    # Step 2: 残量が全体 quota 超なら古い方から削除 (bound は除外)
    total = sum(sz for _, _, sz in survivors)
    for f, _mt, sz in survivors:
        if total <= max_bytes:
            break
        if str(f.resolve()) in bound_paths:
            continue
        try:
            f.unlink()
            total -= sz
            deleted += 1
            logger.info(
                "jsonl gc: removed by quota %s (size=%dKB, remaining=%dMB)",
                f.name, sz // 1024, total // (1024 * 1024),
            )
        except OSError:
            pass
    if deleted:
        logger.info("jsonl gc: total %d files deleted", deleted)
    return deleted


def run_all_maintenance() -> dict:
    """全 cleanup を 1 回実行 + 結果サマリを返す。 起動時と定期 loop の両方で呼ぶ。

    2026-06-21 (backend-F-33): Sunshine restart / streamer ゾンビ reap は本 file
    から外出し済 (= docs/sunshine-runbook.md + LaunchAgent 別経路)。 backend
    summary からも `restarted_sunshine` キーを削除。
    """
    from backend.jsonl.session_status import cleanup_orphan_turn_starts  # noqa: PLC0415
    return {
        "killed_tmux": cleanup_stale_tmux_sessions(),
        "killed_idle_pwa": cleanup_idle_pwa_sessions(),
        "removed_statusline_map": cleanup_stale_statusline_map(),
        "removed_jsonl": cleanup_old_jsonl(),
        "orphan_turn_starts": cleanup_orphan_turn_starts(),
    }


async def maintenance_loop(interval_sec: int = MAINTENANCE_INTERVAL_SEC) -> None:
    """定期 maintenance: interval_sec ごとに全 cleanup を実行。"""
    logger.info("maintenance_loop started (interval=%ds)", interval_sec)
    try:
        while True:
            try:
                await asyncio.sleep(interval_sec)
                summary = run_all_maintenance()
                logger.info("maintenance tick: %s", summary)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("maintenance_loop iteration failed")
    except asyncio.CancelledError:
        logger.info("maintenance_loop cancelled")
        raise
