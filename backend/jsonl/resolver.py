"""jsonl_path 解決の 1 入口 (= backend-F-27 / crosscut-F-27)。

旧来 chat.py の fork_session / delete_session / restart_session 等は jsonl path を
得るために 3 経路を別々に直叩きしていた:

  1. `pty_runner.jsonl_path_for_session(sid)` (= watcher 経由 binding)
  2. `jsonl_watcher._cwd_to_project_dir(cwd, account_id=...)` (= project dir 列挙)
  3. project_dir 配下を直接 `glob("*.jsonl")` で走査 (= fork / scan-only 用)

これらを `resolve_jsonl(sid, prefer=...)` 1 本に統合する。 副 path (= watcher.py /
runner.py) は touch せず、 consumer 側のみ resolver を経由するよう rewire する。

prefer の意味:
- "live": watcher binding (= claude が今 write 中の jsonl)。 chat tail / status SSE 用。
- "project_dir": account / cwd から逆引きした project dir (= 過去 jsonl 列挙のベース)。
- "scan": project_dir 配下の全 jsonl を mtime desc で返す (= fork uuid 検索 / GC scan 用)。

戻り値:
- "live" → `Path | None` (= 単一)
- "project_dir" → `Path | None` (= 単一 dir)
- "scan" → `list[Path]` (= mtime desc、 空 list あり)

monkeypatch 互換: 内部実装は `pty_runner.jsonl_path_for_session` /
`jsonl_watcher._cwd_to_project_dir` の **module attribute** を都度 lookup する。 既存
test (= `monkeypatch.setattr(pty_runner, "jsonl_path_for_session", ...)`) はそのまま効く。
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional, Union, overload

import backend.jsonl.watcher as _jsonl_watcher
import backend.terminal.runner as _pty_runner
from backend.state import sessions_meta

Prefer = Literal["live", "project_dir", "scan"]


def _project_dir(session_id: str) -> Optional[Path]:
    """sid → 該当 account の projects dir 配下の cwd ハッシュ dir を返す。
    cwd / account の bind は AGENTS config + SessionDef.account_id 経由。"""
    from backend.config import AGENTS  # noqa: PLC0415

    meta = sessions_meta.get(session_id)
    if meta is None:
        return None
    cwd = (AGENTS.get(meta.agent_id) or {}).get("cwd")
    if not cwd:
        # fallback: live binding の親 dir (= 確定済 jsonl があるならその dir)
        live = _pty_runner.jsonl_path_for_session(session_id)
        return live.parent if live else None
    return _jsonl_watcher._cwd_to_project_dir(cwd, account_id=meta.account_id)


@overload
def resolve_jsonl(session_id: str, *, prefer: Literal["live"]) -> Optional[Path]: ...
@overload
def resolve_jsonl(session_id: str, *, prefer: Literal["project_dir"]) -> Optional[Path]: ...
@overload
def resolve_jsonl(session_id: str, *, prefer: Literal["scan"]) -> list[Path]: ...


def resolve_jsonl(
    session_id: str, *, prefer: Prefer = "live"
) -> Union[Optional[Path], list[Path]]:
    """jsonl_path 3 経路 (= live / project_dir / scan) を 1 関数で統合する。

    各 prefer の意味は module docstring 参照。 副作用なし、 毎回新しく resolve する
    (= キャッシュしない、 watcher が rotate を反映するため)。
    """
    if prefer == "live":
        return _pty_runner.jsonl_path_for_session(session_id)
    if prefer == "project_dir":
        return _project_dir(session_id)
    if prefer == "scan":
        pd = _project_dir(session_id)
        if pd is None or not pd.is_dir():
            return []
        return sorted(pd.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    raise ValueError(f"unknown prefer: {prefer!r}")
