"""自動の入れ替えの見張り: 条件の立ったタブへ、 締めを頼む発話を打つ。

入れ替えの流れと発話の形は `backend/routes/rollover.py`。 ここが持つのは「いつ、 どのタブへ頼むか」 だけ。

条件は agent の設定 (= `agents.<id>.rollover`) が決める。 書いていない agent のタブは見張らない。

    "rollover": {
      "working": { "context_pct": 60 },
      "idle":    { "context_pct": 40, "minutes": 50 }
    }

    working: タブの context がこの割合に届いたら、 推論中でも手が空いていても頼む (= 手が空いたタブを
             待たせると、 次に人が打つまで古い会話が残り、 その発話を古い会話が受ける)
    idle:    working の割合より下で、 context がこの割合を超えていて、 会話の記録がこの分数だけ
             更新されていなければ頼む

見張りは一定の間隔でタブを見回り、 どれかのタブが推論を始めた時 (= `UserPromptSubmit` の hook) にも
すぐ見回る。 推論を始めたタブは、 その見回りでは推論中と数える (= 画面の実況が追いつく前でも)。 見回りの
間に始まって終わった推論で working の割合を越えたタブも、 手が空いた次の見回りで頼まれる。 判定の材料は毎回、 実物から取る
(= 割合は画面が出している値、 静かな時間は会話の記録 file の最終更新、 頼んだかどうかは記録の中の発話)。
backend の記憶には持たないので、 backend を再起動しても同じ答えになる。

頼むのは 1 度に 1 つのタブだけで、 頼まれて締めへ向かっているタブが在る間は次を頼まない (= 締めは
作業 tree への commit と push を伴うことが多く、 同じ作業 tree を使う会話の締めが重なると互いの
書きかけを巻き込む)。 同じ会話へは、 人がそのタブで最後に打ってから 1 度だけ頼む (= 人が打てば未依頼に戻る)。
ただし戻っても、 前回頼んでから `REASK_AFTER_SECS` 秒が空くまでは頼み直さない。

A tab still in a turn whose record has not moved for `sleep_judgement.STALL_MINUTES` (waiting for a permission, a
tool that hangs) is not counted as closing, so it does not hold up the asks to other tabs. A tab that was asked and
whose close stalled (= judged as the sleep judges a tab, nothing but the close itself and the rollover's line keeps it
from a break after `STALL_MINUTES` of quiet) is asked once more. An ask lapses when the tab was asked twice and is
quiet, or when a usage limit stopped it: the watch asks no more, and the sleep, the stop line and the fallback no
longer count the tab as closing (`sleep_judgement.close_lapsed`). The count of asks stops at `ASKS_MAX`; at that
count a message from another tab starts it over (= new work arrived).

A tab whose claude still runs a tool's shell (= a command its Bash or Monitor tool runs in the background) is not
asked, whatever the reason, and the next tab in line is looked at instead: the conversation's end would stop those
commands (`tool_shells`). The tab is looked at again on the next look, and its quiet time includes the records of its
sub-agents, which a sub-agent running in the background keeps writing. A conversation held back that way past its
working line is told once why (`held_notice.py`), whether or not another tab is closing.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

import psutil

import backend.jsonl.jsonl_watcher as jsonl_watcher
from backend.jsonl.jsonl_predicates import AGENT_MESSAGE_OPENINGS, CLIENT_OPENINGS, ROLLOVER_OPENING, unwrap_pasted
from backend.routes.agent_messages import entered_text, lines_from_the_end
from backend.routes.overview import context_pct_of, is_busy
from backend.routes.rollover import TAG, close_envelope
from backend._common.state import sessions_meta
from backend.rollover import held_notice
from backend.rollover.tool_shells import ProcessRow, ToolShell, tool_shells
from backend.terminal.pty_discover import claude_in_pane, claude_pid_in_pane
from backend.terminal.routes import pty_send
from backend.terminal.session_resolver import agent_setting

if TYPE_CHECKING:
    from backend.sleep.sleep_judgement import SleepFacts

logger = logging.getLogger(__name__)

# 見回りの間隔。 条件は分の単位で、 頼むのがこの秒数まで遅れる。 `idle.minutes` を cache の寿命の
# 手前に置く使い方では、 その余裕 (= 寿命 − minutes) の 1/3 より短く取る。
TICK_SEC = 60.0

# Minimum gap before the same conversation is asked to close again. A tab that is spoken to by voice
# resets the "already asked" answer with every utterance, so without a gap each look would ask again.
REASK_AFTER_SECS = 300.0

# How many times one conversation is asked to close before the ask lapses (= the first ask and one more).
ASKS_MAX = 2

# Per record: how far it was read and the count of asks up to there. Only a shortcut: without it the record is read
# back from its end to the same value.
_seen: dict[str, tuple[int, int]] = {}
# Asks typed that have not reached the record yet. What is typed into a claude in a turn is queued and written only
# when the turn takes it, so the next look must not type it again; an ask that never reaches the record (typed into a
# menu) still counts, so it is not typed forever.
_pending: dict[str, int] = {}
# One reader of the counts at a time: the watch and the sleep, stop line and fallback patrols read them from their
# threads, and two reading the same rows would take an ask that reached the record off `_pending` twice.
_count_lock = threading.Lock()
# The conversations whose lapse was logged (= once each; a restart of the backend forgets and logs once more).
_lapse_logged: set[str] = set()
# When each conversation was last asked to close (= wall-clock seconds). Kept in memory only: a restart
# forgets it and may ask once more.
_asked_at: dict[str, float] = {}
# Per record: the pids of the tools' shells the last ask held back for (= the log says so when they change).
_held: dict[str, tuple[int, ...]] = {}
# 推論を始めて、 まだ見回りが見ていないタブ。 hook が入れ、 推論が終われば (= `Stop` の hook) 抜く。
_started: set[str] = set()
# 推論を始めたタブが在る時に、 間隔を待たずに見回りを起こす合図 (= 見回りの loop が作る)。
_wake: asyncio.Event | None = None


def turn_started(session_id: str) -> None:
    """そのタブが推論を始めた (= `UserPromptSubmit` の hook)。 次の見回りをすぐ起こす。"""
    _started.add(session_id)
    if _wake is not None:
        _wake.set()


def turn_ended(session_id: str) -> None:
    """そのタブの推論が終わった (= `Stop` の hook)。 見回りが見る前に終わった推論は、 推論中と数えない。"""
    _started.discard(session_id)


def settings_for(session_id: str) -> dict | None:
    """そのタブの入れ替えの条件 (= agent の値を、 タブの階層の `tiers` が置き換えた物)。 書いていなければ None。"""
    rollover = agent_setting(session_id, "rollover")
    return rollover if isinstance(rollover, dict) else None


def _number(section, key: str) -> float | None:
    value = section.get(key) if isinstance(section, dict) else None
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def due(cfg: dict, pct: int | None, idle_minutes: float, busy: bool) -> str | None:
    """頼む理由 (= working の割合に届いた `context` / 静かなまま idle の割合を超えている `idle`)。 頼まないなら
    None。 working の割合は推論中でも手が空いていても見る。 idle は手が空いている時だけ。"""
    if pct is None:
        return None
    at = _number(cfg.get("working"), "context_pct")
    if at is not None and pct >= at:
        return "context"
    if busy:
        return None
    at, quiet = _number(cfg.get("idle"), "context_pct"), _number(cfg.get("idle"), "minutes")
    if at is not None and quiet is not None and pct >= at and idle_minutes >= quiet:
        return "idle"
    return None


def _decisive(raw: bytes) -> str | None:
    """What one row of the record is to the count of asks: `operator` for the operator's words, `close` for an ask to
    close, `message` for a message from another tab, and None for anything else (= the opening of a conversation that
    rolled over or of a tier tab, and the client's notices, leave the count as it is)."""
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
    if text.startswith(AGENT_MESSAGE_OPENINGS):
        return "message"
    return None if text.startswith(CLIENT_OPENINGS) else "operator"


def fold_asks(asks: int, kind: str | None) -> int:
    """The count of asks to close after one more row of the record (`kind` from `_decisive`): the operator's words
    start it over, an ask adds one up to `ASKS_MAX`, and a message from another tab starts it over only once the ask
    lapsed by count (= new work arrived, so the tab may be asked afresh; while the first ask is open a message is part
    of the close)."""
    if kind == "operator":
        return 0
    if kind == "close":
        return min(asks + 1, ASKS_MAX)
    if kind == "message" and asks >= ASKS_MAX:
        return 0
    return asks


def _asks_from_the_end(record: Path) -> int:
    """The count of asks, read back from the end of the record to the operator's last words."""
    kinds: list[str] = []
    for raw in lines_from_the_end(record):
        kind = _decisive(raw)
        if kind == "operator":
            break
        if kind is not None:
            kinds.append(kind)
    asks = 0
    for kind in reversed(kinds):
        asks = fold_asks(asks, kind)
    return asks


def close_requests(record: Path) -> int:
    """How many times the conversation was asked to close since the operator last typed: the asks in its record and
    the ones typed that have not reached it, up to `ASKS_MAX`. 0 = not asked."""
    with _count_lock:
        return _close_requests(record)


def _close_requests(record: Path) -> int:
    key = str(record)
    try:
        size = record.stat().st_size
    except OSError:
        return min(_pending.get(key, 0), ASKS_MAX)
    offset, asks = _seen.get(key, (None, 0))
    if offset is None or size < offset:
        try:
            asks = _asks_from_the_end(record)
        except OSError:
            return min(_pending.get(key, 0), ASKS_MAX)
        if asks:
            _pending.pop(key, None)       # the record answers: a typed ask cannot be told from one it shows
        _seen[key] = (size, asks)
    elif size > offset:
        try:
            with record.open("rb") as fh:
                fh.seek(offset)
                data = fh.read(size - offset)
        except OSError:
            return min(asks + _pending.get(key, 0), ASKS_MAX)
        cut = data.rfind(b"\n") + 1      # 改行で終わっていない最後の行は書き込み途中
        for raw in data[:cut].split(b"\n"):
            kind = _decisive(raw)
            if kind == "close" and _pending.get(key):
                _pending[key] -= 1        # a typed ask reached the record, which counts it from here
            elif kind == "operator":
                _pending.pop(key, None)
            asks = fold_asks(asks, kind)
        _seen[key] = (offset + cut, asks)
    return min(asks + _pending.get(key, 0), ASKS_MAX)


def reask_allowed(last_asked_at: float | None, now: float) -> bool:
    """Whether a conversation may be asked to close now, given when it was last asked (None = never)."""
    return last_asked_at is None or now - last_asked_at >= REASK_AFTER_SECS


def asked(record: Path) -> bool:
    """Whether the conversation was asked to close (= its count of asks is 1 or more)."""
    return close_requests(record) > 0


def _close_check(session_id: str) -> tuple[bool, bool, SleepFacts]:
    """Whether the tab's close stalled (= asked, and nothing but the close itself keeps it from a break after
    `STALL_MINUTES` of quiet) and whether its ask lapsed, read the way the sleep judgement reads a tab. Blocking.
    → (stalled, lapsed, the facts read)."""
    # Imported here: the sleep package reads this module.
    from backend.sleep import sleep_judgement as judgement  # noqa: PLC0415
    from backend.sleep import sleep_sensors  # noqa: PLC0415
    left = judgement.LEFT_BY_A_STALLED_CLOSE
    facts = sleep_sensors.gather(session_id, judgement.STALL_MINUTES, ignoring=left)
    stalled = bool(facts.rollover_asks) and not judgement.judge(facts, judgement.STALL_MINUTES, ignoring=left)
    return stalled, judgement.close_lapsed(facts), facts


def last_written(record: Path) -> float:
    """When the conversation last wrote (unix seconds): the newest modification time of its record and of the records
    of its sub-agents (= the `subagents/` folder named like the record, next to it)."""
    newest = record.stat().st_mtime
    for path in record.with_suffix("").joinpath("subagents").rglob("*.jsonl"):
        try:
            newest = max(newest, path.stat().st_mtime)
        except OSError:
            continue
    return newest


def background_shells(session_id: str) -> list[ToolShell]:
    """The tools' shells the tab's claude runs (= what the end of its conversation would stop). Blocking."""
    pid = claude_pid_in_pane(session_id)
    if pid is None:
        return []
    now = time.time()
    rows: list[ProcessRow] = []
    try:
        children = psutil.Process(pid).children()
    except psutil.Error:
        return []
    for child in children:
        try:
            rows.append(ProcessRow(pid=child.pid, parent_pid=pid, command_line=" ".join(child.cmdline()),
                                   elapsed_seconds=now - child.create_time()))
        except psutil.Error:
            # benign: a child that ended while it was read runs nothing the end of the conversation could stop
            continue
    return tool_shells(rows, pid)


def _log_held(session_id: str, key: str, reason: str, shells: list[ToolShell]) -> None:
    pids = tuple(sorted(shell.pid for shell in shells))
    if _held.get(key) == pids:
        return
    _held[key] = pids
    logger.info("rollover: held session=%s reason=%s background=%s", session_id, reason,
                ",".join(str(pid) for pid in pids))


def _log_lapse(session_id: str, key: str, facts: SleepFacts) -> None:
    if key in _lapse_logged:
        return
    _lapse_logged.add(key)
    logger.info("rollover: lapsed session=%s asks=%s limit_stop=%s quiet_minutes=%s", session_id,
                facts.rollover_asks, bool(facts.ends_in_limit_stop),
                None if facts.quiet_minutes is None else int(facts.quiet_minutes))


async def _ask(sid: str, key: str, reason: str, pct: int | None, idle_minutes: int, now: float, again: bool) -> None:
    meta = sessions_meta.get(sid)
    text = close_envelope(sid, reason, pct, idle_minutes, child=meta is not None and meta.child)
    result = await pty_send(sid, {"text": text, "enter": True}, None)
    if result.get("ok"):
        with _count_lock:
            _pending[key] = _pending.get(key, 0) + 1
        _asked_at[key] = now
    logger.info("rollover: asked session=%s reason=%s context_pct=%s idle_minutes=%d%s ok=%s",
                sid, reason, pct, idle_minutes, " again=1" if again else "", result.get("ok"))


async def _tell_the_held(wanted: list[tuple[bool, float, str, str, int, str]]) -> dict[str, list[ToolShell]]:
    """Tell each conversation past its working line that its tools' commands hold back, once.
    → the shells read, by tab (= the asks that follow read them from here)."""
    shells_of: dict[str, list[ToolShell]] = {}
    for _, _, sid, reason, pct, key in wanted:
        if reason != "context" or not await asyncio.to_thread(claude_in_pane, sid):
            continue
        record = Path(key)
        if await asyncio.to_thread(held_notice.was_told, key, record):
            continue
        shells = shells_of[sid] = await asyncio.to_thread(background_shells, sid)
        if not shells:
            continue
        why_not = await asyncio.to_thread(held_notice.blocker, sid, record)
        line = _number((settings_for(sid) or {}).get("working"), "context_pct")
        await held_notice.tell(sid, key, reason, pct, line, shells, why_not)
    return shells_of


def _moved_since(sid: str, key: str, written: float) -> bool:
    """Whether the tab is at work now, or its record moved since `written` was read of it: what "quiet" rests on, read
    again just before a quiet tab is typed into. A record that cannot be read counts as moved."""
    if is_busy(sid) or sid in _started:
        return True
    try:
        return last_written(Path(key)) != written
    except OSError:
        return True


async def tick() -> str | None:
    """Look over every tab once and ask one tab at most: a new ask first, else once more a tab whose close stalled.
    → the id of the tab asked (None when none was)."""
    # Imported here: the sleep package reads this module.
    from backend.sleep.sleep_judgement import STALL_MINUTES  # noqa: PLC0415
    now = time.time()
    started = set(_started)
    _started.clear()
    records: set[str] = set()
    wanted: list[tuple[bool, float, str, str, int, str]] = []   # (静かでないか, −静かな分数, タブ, 理由, 割合, 記録)
    stalled: list[tuple[float, str, int, str]] = []            # (- quiet minutes, tab, context %, record)
    closing = False
    written: dict[str, float] = {}      # each record's last write as this look read it
    for sid in list(sessions_meta):
        cfg = settings_for(sid)
        record = jsonl_watcher.get_jsonl_for(sid) if cfg is not None else None
        if record is None:
            continue
        key = str(record)
        records.add(key)
        try:
            written[key] = last_written(record)
            idle_minutes = (now - written[key]) / 60
        except OSError:
            continue
        busy = is_busy(sid) or sid in started
        pct = context_pct_of(sid)
        reason = due(cfg, pct, idle_minutes, busy)
        # Read every tab, condition or not: a stalled close is looked at whatever the condition, and after a restart
        # of the backend the asks are only in the record. In a thread: a record seen first is read back from its end,
        # then only from where it stopped, and nothing else waits meanwhile.
        asks = await asyncio.to_thread(close_requests, record)
        # 頼まれて締めへ向かっている。 頼んだ直後は、 推論が始まっても記録がまだ古いので、 頼んだ時刻でも数える
        if busy and asks and (idle_minutes < STALL_MINUTES or now - _asked_at.get(key, 0) < STALL_MINUTES * 60):
            closing = True
        elif reason is not None and not asks:
            wanted.append((reason != "idle", -idle_minutes, sid, reason, pct, key))
        elif asks and not busy:
            stalled.append((-idle_minutes, sid, pct, key))
    for table in (_seen, _asked_at, _held):
        for key in [k for k in table if k not in records]:
            del table[key]
    for key in [k for k in _pending if k not in records]:
        del _pending[key]
    _lapse_logged.intersection_update(records)
    held_notice.forget(records)
    shells_of = await _tell_the_held(wanted)
    if closing:
        return None
    # 静かなタブを、 静かな時間の長い順に。 推論中のタブはその後。
    for _, minus_idle, sid, reason, pct, key in sorted(wanted):
        if not reask_allowed(_asked_at.get(key), now) or not await asyncio.to_thread(claude_in_pane, sid):
            continue
        shells = shells_of[sid] if sid in shells_of else await asyncio.to_thread(background_shells, sid)
        if shells:
            _log_held(sid, key, reason, shells)
            continue
        if reason == "idle" and _moved_since(sid, key, written[key]):
            continue
        _held.pop(key, None)
        await _ask(sid, key, reason, pct, int(-minus_idle), now, again=False)
        return sid
    for minus_idle, sid, pct, key in sorted(stalled):
        if not reask_allowed(_asked_at.get(key), now) or not await asyncio.to_thread(claude_in_pane, sid):
            continue
        is_stalled, lapsed, facts = await asyncio.to_thread(_close_check, sid)
        if lapsed:
            _log_lapse(sid, key, facts)
            continue
        if not is_stalled or facts.rollover_asks != 1 or _moved_since(sid, key, written[key]):
            continue
        # Asked again with its quiet minutes: the screen reads the reason as `idle` or `context` only
        await _ask(sid, key, "idle", pct, int(facts.quiet_minutes or -minus_idle), now, again=True)
        return sid
    return None


async def rollover_loop(interval_sec: float = TICK_SEC) -> None:
    """interval_sec ごとに見回る。 その間にどれかのタブが推論を始めたら、 待たずに見回る。"""
    global _wake
    _wake = asyncio.Event()
    logger.info("rollover_loop started (interval=%ds)", interval_sec)
    try:
        while True:
            try:
                try:
                    await asyncio.wait_for(_wake.wait(), interval_sec)
                except TimeoutError:
                    # benign: the interval elapsed without a turn starting; that is the regular look
                    pass
                _wake.clear()
                await tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("rollover_loop iteration failed")
    except asyncio.CancelledError:
        logger.info("rollover_loop cancelled")
        raise
