"""Writes a tab's conversation, up to a cut point, as a new claude session record: the fork and the move of a
tab to another account both start from it. Reads the tab's record, builds the chain with `fork.py` and writes it
into the projects folder the new session must be opened from.

Used by `routes/sessions.py` (= the fork) and `accounts/account_move.py` (= moving a tab to another account).
"""
from __future__ import annotations

import logging
import uuid
from enum import Enum
from pathlib import Path
from typing import NamedTuple

from fastapi import HTTPException

from backend._common.config import AGENTS, cwd_to_project_dir, default_account_id
from backend._common.errors import raise_error
from backend._common.state import atomic_write_text, sessions_meta
from backend.fork.fork import (
    build_forked_lineage_lazy,
    fork_point_status,
    latest_clean_fork_point,
    latest_cut_through_tool_results,
)
from backend.jsonl import resolver as jsonl_resolver
from backend.jsonl.jsonl_tail import split_jsonl_text

logger = logging.getLogger(__name__)


class LineageCut(str, Enum):
    """Where `write_lineage` ends the conversation when it is not told a message to end at."""
    # the latest finished turn or prompt of the operator (= nothing of a turn that is still going is carried)
    CLEAN_TURN = "clean_turn"
    # the end of the conversation, without the rows a usage limit wrote: the tool results of the turn it stopped stay
    THROUGH_TOOL_RESULTS = "through_tool_results"


class WrittenLineage(NamedTuple):
    """The new claude session `write_lineage` wrote: its id, whether it was written for another account, and the
    record's path."""
    claude_id: str
    moved: bool
    path: Path


def write_lineage(session_id: str, from_uuid: str | None, target_account_id: str | None, *,
                  cut: LineageCut = LineageCut.CLEAN_TURN) -> WrittenLineage:
    """Write the conversation of a tab up to `from_uuid` (or, when it is `None`, up to the point `cut` names) as a
    new claude session, in the projects folder of `target_account_id` when that is another account. Used by the fork
    and by moving a tab's account."""
    parent = sessions_meta[session_id]

    # from_uuid を含む jsonl を探す。 claude は途中で session id をロール (= compact / 継続)
    # することがあり、 画面に残る古いメッセージは前のファイルに居る一方、 live binding
    # は今 open 中の新ファイルを返す。 そのため「今のファイルだけ」 でなく同じ cwd の
    # project dir 内の全 jsonl を新しい順に走査して、 uuid を実際に含むファイルを source
    # にする (= uuid は一意なので確実に当たる)。
    live = jsonl_resolver.resolve_jsonl(session_id, prefer="live")
    project_dir = jsonl_resolver.resolve_jsonl(session_id, prefer="project_dir")
    # fork 専用フォールバック: cwd 解決不能でも live があれば「live と同じ dir」 を使う
    # (= 過去 behavior 互換、 resolver 一般 API はこの fallback を持たない)。
    if project_dir is None and live is not None:
        project_dir = live.parent

    candidates: list = []
    if live is not None and live.exists():
        candidates.append(live)
    if project_dir is not None and project_dir.is_dir():
        others = sorted(
            (p for p in project_dir.glob("*.jsonl") if p != live),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        candidates.extend(others)  # 全部走査。 ハード上限 (旧 40 / 拡張 200) は長期 cwd で
        # 「祖先 uuid が範囲外」 で lineage を中途半端に打ち切る事故の元だったので撤廃。
        # 自然な上限は maintenance.cleanup_old_jsonl (= 14 日 / 500MB 自動掃除) が引いてくれる。

    if from_uuid:
        needle = from_uuid.encode("utf-8")
        src_path = None
        for p in candidates:
            try:
                if needle in p.read_bytes():
                    src_path = p
                    break
            except OSError:
                continue

        if src_path is None:
            logger.warning(
                "fork: from_uuid not found session=%s uuid=%s scanned=%d dir=%s",
                session_id, from_uuid, len(candidates), project_dir,
            )
            raise_error(404, "message_not_found", "この会話のログに該当メッセージが見つかりません")

        # まず src_path 単体で fork point の妥当性 (= tool 行で切れてないか) を確認。
        # 大半のフォークは src_path の中で会話が閉じてて、 ここで全部完結する。
        src_lines = split_jsonl_text(src_path.read_text(encoding="utf-8"))
        status = fork_point_status(src_lines, from_uuid)
        if status != "ok":
            raise_error(400, "cannot_fork_here", "この位置からは分岐できません (= user 発言か完了したターンのみ)")
    else:
        # 位置指定なし: live jsonl の末尾から最初の安全な切れ目を採る。 道具の実行中に
        # 呼ばれてもそこまで下がるので、 呼び出し側は位置を気にしなくてよい。
        # Only the tab's own conversation: another file of the folder is another tab's conversation.
        src_path = live if live is not None and live.exists() else None
        if src_path is None:
            raise_error(404, "message_not_found", "この会話のログが見つかりません")
        src_lines = split_jsonl_text(src_path.read_text(encoding="utf-8"))
        from_uuid = (latest_cut_through_tool_results(src_lines) if cut is LineageCut.THROUGH_TOOL_RESULTS
                     else latest_clean_fork_point(src_lines))
        if from_uuid is None:
            raise_error(400, "cannot_fork_here", "引き継げる切れ目がまだありません (= ターンの完了を待ってください)")

    # lazy stitching: build_forked_lineage_lazy が鎖を辿りながら、 親 uuid が src_lines に
    # 無い時だけ fetch_more で次の jsonl を 1 個取りに来る。 鎖が src_lines 内で閉じれば
    # 追加 jsonl は読まれない (= 大半のケース)。 同 cwd の他 jsonl は新しい順に提供。
    other_iter = None
    if project_dir is not None and project_dir.is_dir():
        other_iter = iter(sorted(
            (p for p in project_dir.glob("*.jsonl") if p != src_path),
            key=lambda p: p.stat().st_mtime, reverse=True,
        ))
    extra_files: list[str] = []

    def fetch_more():
        if other_iter is None:
            return None
        try:
            nxt = next(other_iter)
        except StopIteration:
            return None
        try:
            lines = split_jsonl_text(nxt.read_text(encoding="utf-8"))
        except OSError:
            return []  # 1 ファイルだけ読み損ねても次へ進めるよう空 list を返す
        extra_files.append(nxt.name)
        return lines

    new_claude_id = str(uuid.uuid4())
    try:
        forked = build_forked_lineage_lazy(src_lines, from_uuid, new_claude_id, fetch_more)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not forked:
        raise_error(400, "empty_conversation", "分岐対象の会話が空です")
    logger.info(
        "fork: session=%s src=%s from_uuid=%s extra_files=%d -> new_jsonl=%s.jsonl rows=%d",
        session_id, src_path.name, from_uuid, len(extra_files),
        new_claude_id, len(forked),
    )

    # 新 jsonl は project dir (= 同 cwd hash) に置く。 新タブは agent を継承 = 同 cwd で spawn
    # するので claude --resume がこの新 jsonl を確実に見つける。
    #
    # アカウントを移す時は **移し先の** projects dir に置く。 spawn 時の CLAUDE_CONFIG_DIR は
    # new_meta.account_id で決まるので、 lineage を元のアカウント配下に置いたままだと
    # `claude --resume` が見つけられず空タブになる (= 2026-07-22 の空タブ事故と同じ構造)。
    # 会話ログの行はアカウント固有の識別子を持たない (= cwd / gitBranch / version / userType のみ)
    # ので、 置き場所を変えるだけで移し先から読める。
    # account_id が None のタブ (= 古い時期に作られた) は既定 account と等価。 素の比較だと
    # 「既定 account へ移す」 が移行扱いになり、 同じ場所に置き直して title に札が付く。
    current_account = parent.account_id or default_account_id()
    moving = bool(target_account_id) and target_account_id != current_account
    if moving:
        cwd = (AGENTS.get(parent.agent_id) or {}).get("cwd")
        if not cwd:
            raise_error(400, "cwd_unresolved", "この会話の作業ディレクトリが解決できません")
        dest_dir = cwd_to_project_dir(cwd, account_id=target_account_id)
        dest_dir.mkdir(parents=True, exist_ok=True)
    else:
        dest_dir = src_path.parent
    dest = dest_dir / f"{new_claude_id}.jsonl"
    atomic_write_text(dest, "\n".join(forked) + "\n")
    return WrittenLineage(new_claude_id, moving, dest)
