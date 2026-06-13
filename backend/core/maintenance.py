"""サスティナビリティ維持タスク群: stale tmux session kill / 古い JSONL 削除 /
statusline map cleanup。 backend lifespan task の起動時 + 定期実行で呼ばれる。

恒久的に増えていくリソース (= 放置すると無限蓄積する) を機械的に整理する箇所。
backend logs (RotatingFileHandler) / uploads/tmp (1h GC) は別経路で既対策済み、
このモジュールは以下を担当:

  1. PWA タブ削除後の残骸 tmux session の kill
  2. 古い JSONL ファイル (~/.claude/projects/) の自動削除 (mtime + quota)
  3. 古い statusline map ファイルの削除 (対応 tmux session 無いもの)
  4. 肥大化した Sunshine プロセスの restart (= 画面共有 encoder のメモリリーク対策)
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import signal
import subprocess
import time
from pathlib import Path

from config import TMUX_SESSION_MAP_DIR

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

# Sunshine が画面共有 encoder のメモリをこの phys_footprint 超で抱えていたら restart
# 対象とみなす。 観測実績では idle 放置 + ゾンビストリームで 30 GB まで膨らんだ (= 大半は
# swap 退避され RSS には出ない、 phys_footprint でしか捕捉できない)。 fresh 起動直後は
# 数十 MB なので、 2 GB はリークを確実に捉えつつ正常稼働を巻き込まない閾値。
SUNSHINE_FOOTPRINT_MAX_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB


def cleanup_stale_tmux_sessions() -> int:
    """sessions_meta に登録されていない pwa-ses_* tmux session を kill する。
    PWA タブを UI から削除した時点で sessions_meta から消えるが、 backend 経路を経ずに
    削除されたケース (= 旧バックエンドの残骸 / 手動削除) で tmux session だけ残るのを掃除。"""
    try:
        from state import sessions_meta
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
        if len(parts) != 3:
            continue
        name, attached, activity_str = parts
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
    if not TMUX_SESSION_MAP_DIR:
        return 0
    map_dir = Path(TMUX_SESSION_MAP_DIR).expanduser()
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
    from config import CLAUDE_PROJECTS_DIRS  # noqa: PLC0415
    bases = [b for b in CLAUDE_PROJECTS_DIRS if b.is_dir()]
    if not bases:
        return 0
    # 現在 PWA タブが bind 中の jsonl は idle でも保護する。
    bound_paths: set[str] = set()
    try:
        import jsonl.watcher as jsonl_watcher  # noqa: PLC0415
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


_FOOTPRINT_UNITS = {"B": 1, "K": 1024, "KB": 1024, "M": 1024**2, "MB": 1024**2,
                    "G": 1024**3, "GB": 1024**3, "T": 1024**4, "TB": 1024**4}
# `footprint` コマンドの出力ヘッダ行 (= プロセス合計の phys_footprint 相当)。
# macOS のバージョンによって表記が違うので両対応する:
#   旧: `phys_footprint:  40 GB`
#   新: `sunshine [16114]: 64-bit    Footprint: 40 GB (16384 bytes per page)`
# capital F / 接頭辞無しでもマッチさせ、 サマリ表 (= MALLOC_SMALL 行等) は拾わない
# ように行頭から見る IGNORECASE で。
_FOOTPRINT_RE = re.compile(r"(?:phys_)?footprint:\s*([\d.]+)\s*([KMGT]?B)", re.IGNORECASE)
# 配信が物理的に終わっても release/streamer プロセスだけ残るケースがある (= 観測実績、
# 5 日稼働で sunshine phys_footprint 40GB まで膨張、 streamer ゾンビが watchdog の
# 「配信中なら触らない」 ガードに引っかかって sunshine が永遠に kill されなかった)。
# elapsed 秒がこの閾値を超えた streamer は配信中ではなくゾンビとみなして kill する。
# 通常の moonlight ストリームは数分〜数十分単位なので、 1 時間あれば明確にゾンビ判定で
# 良い (= 連続配信ユーザでも 1 時間で session を畳まないことはほぼ無い)。
STREAMER_ZOMBIE_SECONDS = 3600


def _pgrep_one(pattern: str, *, exact: bool = False) -> int | None:
    """pattern にマッチする最初の pid を返す (無ければ None)。 exact=True は -x (完全一致)。"""
    args = ["pgrep", "-x" if exact else "-f", pattern]
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=2.0)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if r.returncode != 0:
        return None
    lines = [ln for ln in r.stdout.split() if ln.strip()]
    return int(lines[0]) if lines else None


def _phys_footprint_bytes(pid: int) -> int | None:
    """`footprint <pid>` を parse して phys_footprint をバイトで返す。 リークは swap に
    退避されて RSS には出ないため、 swap/compressed も計上する phys_footprint で測る。"""
    try:
        r = subprocess.run(["footprint", str(pid)], capture_output=True, text=True, timeout=5.0)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if r.returncode != 0:
        return None
    m = _FOOTPRINT_RE.search(r.stdout)
    if not m:
        return None
    return int(float(m.group(1)) * _FOOTPRINT_UNITS[m.group(2).upper()])


def _reap_zombie_streamers() -> int:
    """release/streamer プロセスのうち elapsed が閾値を超えたものをゾンビとして kill する。
    moonlight stream 終了時にきれいに reap されない地雷の対策。 戻り値は kill した件数。

    elapsed 取得には `ps -o etimes= -p <pid>` を使う (etimes は経過秒、 etime は HH:MM:SS で
    parse がだるい)。 ゾンビ判定の閾値 STREAMER_ZOMBIE_SECONDS 以下なら本当に配信中の可能性が
    あるので触らない (= 配信中の停止という最悪挙動を避ける)。"""
    try:
        r = subprocess.run(
            ["pgrep", "-f", "release/streamer"],
            capture_output=True, text=True, timeout=2.0,
        )
    except (subprocess.TimeoutExpired, OSError):
        return 0
    if r.returncode != 0:
        return 0
    pids = [p for p in r.stdout.split() if p.strip().isdigit()]
    killed = 0
    for pid_str in pids:
        try:
            etime_r = subprocess.run(
                ["ps", "-o", "etimes=", "-p", pid_str],
                capture_output=True, text=True, timeout=2.0,
            )
        except (subprocess.TimeoutExpired, OSError):
            continue
        try:
            elapsed = int(etime_r.stdout.strip())
        except ValueError:
            continue
        if elapsed < STREAMER_ZOMBIE_SECONDS:
            continue
        try:
            os.kill(int(pid_str), signal.SIGKILL)
            killed += 1
            logger.info(
                "maintenance: killed zombie streamer pid=%s (elapsed=%ds)",
                pid_str, elapsed,
            )
        except (ProcessLookupError, PermissionError, OSError):
            continue
    return killed


def _has_live_streamer() -> bool:
    """配信中とみなす streamer (= elapsed が STREAMER_ZOMBIE_SECONDS 未満) が居るか。
    ゾンビ reap 後に呼ぶことで「本当に配信中」 だけを sunshine 触らない条件に絞れる。"""
    try:
        r = subprocess.run(
            ["pgrep", "-f", "release/streamer"],
            capture_output=True, text=True, timeout=2.0,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    if r.returncode != 0:
        return False
    for pid_str in r.stdout.split():
        if not pid_str.strip().isdigit():
            continue
        try:
            etime_r = subprocess.run(
                ["ps", "-o", "etimes=", "-p", pid_str],
                capture_output=True, text=True, timeout=2.0,
            )
            elapsed = int(etime_r.stdout.strip())
        except (subprocess.TimeoutExpired, OSError, ValueError):
            continue
        if elapsed < STREAMER_ZOMBIE_SECONDS:
            return True
    return False


def restart_sunshine_if_bloated() -> bool:
    """Sunshine が phys_footprint 閾値を超えて肥大化し、 かつアクティブな画面共有
    ストリームが無い時だけ kill -9 で restart する (= LaunchAgent KeepAlive が clean
    respawn)。 配信中 (= moonlight streamer プロセス在席) は使用中のペアを壊さないよう
    必ずスキップ。 Sunshine 未導入機では no-op。

    kill -9 を使う理由: SIGTERM (launchctl kickstart) 経由の graceful shutdown は
    ScreenCaptureKit / VideoToolbox の resource を中途半端に解放し respawn 後の encoder
    初期化を hang させる既知の地雷がある。 SIGKILL なら OS が resource を強制 reap する。

    2026-06-04 改修: 配信中ガードを「streamer pid 在席」 から「elapsed が短い streamer 在席」
    に絞った。 旧版は配信終了後に reap されない streamer ゾンビが居るだけで watchdog が
    永遠にスキップし続け、 5 日稼働で 40GB phys_footprint まで膨張した実例があった。 先に
    ゾンビ streamer (= 1h 以上 elapsed) を kill してから判定する。"""
    pid = _pgrep_one("sunshine", exact=True)
    if pid is None:
        return False  # 未導入 or 停止中
    # 古い streamer はゾンビとして先に reap (= 配信中ガードに引っかかる根本原因を除去)
    _reap_zombie_streamers()
    # 残った streamer (= elapsed 短い = 本当に配信中の可能性) があれば触らない
    if _has_live_streamer():
        return False
    footprint = _phys_footprint_bytes(pid)
    if footprint is None or footprint <= SUNSHINE_FOOTPRINT_MAX_BYTES:
        return False
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        return False
    logger.info(
        "maintenance: restarted bloated sunshine pid=%d (phys_footprint=%.1fGB > %.1fGB)",
        pid, footprint / 1024**3, SUNSHINE_FOOTPRINT_MAX_BYTES / 1024**3,
    )
    return True


def run_all_maintenance() -> dict:
    """全 cleanup を 1 回実行 + 結果サマリを返す。 起動時と定期 loop の両方で呼ぶ。"""
    from jsonl.session_status import cleanup_orphan_turn_starts  # noqa: PLC0415
    return {
        "killed_tmux": cleanup_stale_tmux_sessions(),
        "killed_idle_pwa": cleanup_idle_pwa_sessions(),
        "removed_statusline_map": cleanup_stale_statusline_map(),
        "removed_jsonl": cleanup_old_jsonl(),
        "restarted_sunshine": restart_sunshine_if_bloated(),
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
