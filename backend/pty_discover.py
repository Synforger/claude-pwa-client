"""tmux pane 配下の claude プロセスを探索して jsonl_watcher に登録する。

tmux session が生成されてから子 zsh / wrapper / claude が立ち上がるまで時間差があるので、
polling で claude プロセス (pid / cwd / 起動時刻) を捕まえて binding 登録する。

backend-F-24: 旧版は per-descendant で `pgrep -P` + `ps -p comm=` を呼び、 さらに見つけた
claude に対し `ps -p lstart=` + `lsof -d cwd` を別 subprocess で呼んでいた (= BFS depth 分
の `pgrep` + n 個の `ps` を毎 polling で fork)。 psutil は 1 系統に集約されるので、 全 BFS
+ start_time + cwd を Python 内で 1 ループにできる (= subprocess fork 数 大幅削減 + tight loop
の overhead 解消)。 psutil は package として既に backend env に入っている (= requirements.txt
で固定)。
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

import psutil


async def register_claude_when_ready(
    session_id: str, max_wait: float = 8.0, interval: float = 0.5,
) -> None:
    """tmux pane の子 claude プロセスが立ち上がるのを polling で待ち、 jsonl_watcher に登録する。

    launch_alias 経由だと claude 起動まで 1-2 秒、 環境次第でもう少しかかる。
    `max_wait` 秒以内に claude プロセスが見つからなければ諦める (= 既存 zsh のみで claude
    起動しないケース等)。
    """
    import backend.jsonl.watcher as jsonl_watcher  # 循環 import 回避のため遅延 import
    deadline = time.time() + max_wait
    while time.time() < deadline:
        await asyncio.sleep(interval)
        for pane_pid in tmux_pane_pids(session_id):
            info = _find_claude_descendant_info(pane_pid)
            if info is None:
                continue
            claude_pid, start_time, cwd = info
            jsonl_watcher.register_pending(session_id, claude_pid, cwd, start_time)
            return


def tmux_pane_pids(session_id: str) -> list[int]:
    """指定 PWA session の tmux session に属する pane の PID 一覧。"""
    # pty_runner との循環 import を避けるため遅延 import (= 関数の最初の呼出時のみ評価)
    from backend.terminal.runner import USE_TMUX_WRAP, _run_tmux, _tmux_session_name
    if not USE_TMUX_WRAP:
        return []
    r = _run_tmux("list-panes", "-t", _tmux_session_name(session_id), "-F", "#{pane_pid}", text=True)
    if r is None or r.returncode != 0:
        return []
    return [int(s) for s in r.stdout.split() if s.strip().isdigit()]


def _find_claude_descendant_info(
    root_pid: int, max_depth: int = 6,
) -> tuple[int, float, str] | None:
    """BFS で子孫プロセスを psutil で辿り、 name() の basename == 'claude' を返す。

    返り値 = (pid, create_time, cwd)。 cwd 取得失敗 (= 権限 / プロセス即終了) は None で skip。
    旧 find_claude_descendant + process_start_time + process_cwd を 1 関数に統合
    (= backend-F-24)、 psutil の 1 系統で start_time / cwd まで一気に取る。
    """
    try:
        root = psutil.Process(root_pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None
    queue: list[tuple[psutil.Process, int]] = [(root, 0)]
    while queue:
        proc, depth = queue.pop(0)
        if depth >= max_depth:
            continue
        try:
            children = proc.children()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        for child in children:
            try:
                name = child.name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            if name and Path(name).name == "claude":
                try:
                    start_time = float(child.create_time())
                    cwd = child.cwd()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                if cwd:
                    return (child.pid, start_time, cwd)
            queue.append((child, depth + 1))
    return None


def find_claude_descendant(root_pid: int, max_depth: int = 6) -> int | None:
    """旧 API 互換 wrapper (= autoresume_watchdog が pid だけ欲しい時に使う)。

    内部は _find_claude_descendant_info を呼んで pid だけ返す。 backend-F-24 で内部実装は
    psutil 1 ループ化済 (= 旧 pgrep + ps 連打は廃止)。
    """
    info = _find_claude_descendant_info(root_pid, max_depth=max_depth)
    return info[0] if info is not None else None


def process_start_time(pid: int) -> float | None:
    """互換 API: psutil 経由で create_time を返す。 旧 ps lstart より精度高い (= unix
    epoch float そのまま)。"""
    try:
        return float(psutil.Process(pid).create_time())
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def process_cwd(pid: int) -> str | None:
    """互換 API: psutil 経由で cwd を返す (= macOS は内部で lsof 相当を呼ぶ)。 旧 lsof
    fork 経路より軽い。"""
    try:
        return psutil.Process(pid).cwd() or None
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None
