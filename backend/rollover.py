"""自動の入れ替えの見張り: 条件の立ったタブへ、 締めを頼む発話を打つ。

入れ替えの流れと発話の形は `backend/routes/rollover.py`。 ここが持つのは「いつ、 どのタブへ頼むか」 だけ。

条件は agent の設定 (= `agents.<id>.rollover`) が決める。 書いていない agent のタブは見張らない。

    "rollover": {
      "working": { "context_pct": 60 },
      "idle":    { "context_pct": 40, "minutes": 50 }
    }

    working: 推論中のタブの context がこの割合に届いたら頼む (= 手が空いているタブには打たない。
             人が返事を読んでいる・打っている最中の会話を締めない)
    idle:    手が空いているタブの context がこの割合を超えていて、 会話の記録がこの分数だけ
             更新されていなければ頼む

見張りは一定の間隔でタブを見回る。 判定の材料は毎回、 実物から取る (= 割合は画面が出している値、
静かな時間は会話の記録 file の最終更新、 頼んだかどうかは記録の中の発話)。 backend の記憶には持たない
ので、 backend を再起動しても同じ答えになる。

頼むのは 1 度に 1 つのタブだけで、 頼まれて締めへ向かっているタブが在る間は次を頼まない (= 締めは
作業 tree への commit と push を伴うことが多く、 同じ作業 tree を使う会話の締めが重なると互いの
書きかけを巻き込む)。 同じタブへは、 人がそのタブで最後に打ってから 1 度だけ頼む (= 人が打てば数え直す)。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

import backend.core.jsonl_watcher as jsonl_watcher
from backend.core.jsonl_predicates import AGENT_MESSAGE_OPENINGS, ROLLOVER_OPENING, unwrap_pasted
from backend.routes.agent_messages import entered_text, lines_from_the_end
from backend.routes.overview import context_pct_of, is_busy
from backend.routes.rollover import TAG, close_envelope
from backend.state import sessions_meta
from backend.terminal.pty_discover import claude_in_pane
from backend.terminal.routes import pty_send
from backend.terminal.session_resolver import resolve_agent_cfg

logger = logging.getLogger(__name__)

# 見回りの間隔。 条件は分の単位で、 頼むのがこの秒数まで遅れる。 `idle.minutes` を cache の寿命の
# 手前に置く使い方では、 その余裕 (= 寿命 − minutes) の 1/3 より短く取る。
TICK_SEC = 60.0

# 記録ごとの「読んだ位置」 と「最後に端末から入った、 人の発話か締めを頼む発話」。 読み直しを省くためだけの
# 物で、 無くなれば記録を末尾から読み直して同じ値になる。
_seen: dict[str, tuple[int, str | None]] = {}
# 締めを頼む発話を打ったが、 まだ記録に現れていない会話。 推論中の claude へ打った発話は積まれて、
# 作業の合間に渡るまで記録に書かれない。 その間に次の見回りが同じ発話をもう 1 度打たないための物。
_pending: set[str] = set()


def settings_for(session_id: str) -> dict | None:
    """そのタブの agent の入れ替えの条件。 書いていなければ None。"""
    rollover = (resolve_agent_cfg(session_id) or {}).get("rollover")
    return rollover if isinstance(rollover, dict) else None


def _number(section, key: str) -> float | None:
    value = section.get(key) if isinstance(section, dict) else None
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def due(cfg: dict, pct: int | None, idle_minutes: float, busy: bool) -> str | None:
    """頼む理由 (= 推論中に割合へ届いた `context` / 静かなまま割合を超えている `idle`)。 頼まないなら None。"""
    if pct is None:
        return None
    if busy:
        at = _number(cfg.get("working"), "context_pct")
        return "context" if at is not None and pct >= at else None
    at, quiet = _number(cfg.get("idle"), "context_pct"), _number(cfg.get("idle"), "minutes")
    if at is not None and quiet is not None and pct >= at and idle_minutes >= quiet:
        return "idle"
    return None


def _decisive(raw: bytes) -> str | None:
    """記録の 1 行が、 人の打った発話なら `operator`、 締めを頼む発話なら `close`。 どちらでもなければ None
    (= 別のタブからの連絡と、 起動し直した会話の最初の発話は、 頼んだかどうかを変えない)。"""
    if b'"user"' not in raw and b"queued_command" not in raw:
        return None
    try:
        row = json.loads(raw)
    except ValueError:
        return None
    text = entered_text(row) if isinstance(row, dict) else None
    if text is None or not text.strip():
        return None
    text = unwrap_pasted(text).lstrip()
    if text.startswith(ROLLOVER_OPENING):
        return "close" if f'<{TAG} phase="close"' in text else None
    return None if text.startswith(AGENT_MESSAGE_OPENINGS) else "operator"


def asked(record: Path) -> bool:
    """その会話に、 締めをもう頼んであるか (= 人が最後に打った発話より後に、 締めを頼む発話が在る)。"""
    key = str(record)
    try:
        size = record.stat().st_size
    except OSError:
        return False
    offset, kind = _seen.get(key, (None, None))
    if offset is None or size < offset:
        try:
            kind = next((k for raw in lines_from_the_end(record) if (k := _decisive(raw))), None)
        except OSError:
            return key in _pending
        _seen[key] = (size, kind)
        if kind == "close":
            _pending.discard(key)
    elif size > offset:
        try:
            with record.open("rb") as fh:
                fh.seek(offset)
                data = fh.read(size - offset)
        except OSError:
            return kind == "close" or key in _pending
        cut = data.rfind(b"\n") + 1      # 改行で終わっていない最後の行は書き込み途中
        for raw in data[:cut].split(b"\n"):
            found = _decisive(raw)
            if found == "close":
                _pending.discard(key)     # 打った発話が記録に現れた。 ここから先は記録が答える
            kind = found or kind
        _seen[key] = (offset + cut, kind)
    return kind == "close" or key in _pending


async def tick() -> str | None:
    """全部のタブを 1 回見回り、 頼むべきタブが在れば 1 つにだけ頼む。 → 頼んだタブの id (= 無ければ None)。"""
    now = time.time()
    records: set[str] = set()
    wanted: list[tuple[bool, float, str, str, int, str]] = []   # (静かでないか, −静かな分数, タブ, 理由, 割合, 記録)
    closing = False
    for sid in list(sessions_meta):
        cfg = settings_for(sid)
        record = jsonl_watcher.get_jsonl_for(sid) if cfg is not None else None
        if record is None:
            continue
        records.add(str(record))
        try:
            idle_minutes = (now - record.stat().st_mtime) / 60
        except OSError:
            continue
        busy = is_busy(sid)
        if busy and asked(record):
            closing = True          # 頼まれて締めへ向かっている
            continue
        pct = context_pct_of(sid)
        reason = due(cfg, pct, idle_minutes, busy)
        if reason is not None and not asked(record):
            wanted.append((reason != "idle", -idle_minutes, sid, reason, pct, str(record)))
    for key in [k for k in _seen if k not in records]:
        del _seen[key]
    _pending.intersection_update(records)
    if closing:
        return None
    # 静かなタブを、 静かな時間の長い順に。 推論中のタブはその後。
    for _, minus_idle, sid, reason, pct, key in sorted(wanted):
        if not claude_in_pane(sid):
            continue
        idle_minutes = int(-minus_idle)
        result = await pty_send(sid, {"text": close_envelope(sid, reason, pct, idle_minutes), "enter": True}, None)
        if result.get("ok"):
            _pending.add(key)
        logger.info("rollover: asked session=%s reason=%s context_pct=%s idle_minutes=%d ok=%s",
                    sid, reason, pct, idle_minutes, result.get("ok"))
        return sid
    return None


async def rollover_loop(interval_sec: float = TICK_SEC) -> None:
    """interval_sec ごとに見回る。"""
    logger.info("rollover_loop started (interval=%ds)", interval_sec)
    try:
        while True:
            try:
                await asyncio.sleep(interval_sec)
                await tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("rollover_loop iteration failed")
    except asyncio.CancelledError:
        logger.info("rollover_loop cancelled")
        raise
