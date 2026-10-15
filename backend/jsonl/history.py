"""pwa_sid → 終わった会話 (= claude_sid) の控えの永続化。

タブの claude の会話が終わって次の会話が起動する時 (= 自動の入れ替え / セッション終了ボタン / `/clear`) に、
終わった会話の claude_sid と記録 (= jsonl) の在処を積む。 使い道は 2 つ:

- 画面へ流す会話の並び (= backend/jsonl/chain.py)。 入れ替えの後も、 それまでの会話をタブに出し続ける
- binding が事故で消えた / 古い backup に戻った時の復旧源 (= backend ログ grep より速い参照経路)

設計:
- pwa_sid ごとに最新 N 件 (= 既定 3) を新しい順で保持。 N 件で打ち切るので肥大化しない。
- 同一 claude_sid の重複記録は無視 (= restart 連打や binding 復活で同じ id が流れ込んでも
  履歴を圧迫しない)。
- 各記録は、 タブの記録を古い順につないだ通しの位置での起点 (= `base`) を持つ。 起点は積んだ時に 1 度だけ
  決めて、 後から動かさない (= 古い記録が N 件から落ちても、 残った記録と今の会話の位置は変わらない)。
- file IO は atomic_write_text で 1 ファイル全置換。 同時書き込みは想定外 (= restart は
  UI 経由で人手の 1 回 1 回)。
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

from backend.paths import SESSION_HISTORY_PATH

logger = logging.getLogger(__name__)

MAX_ENTRIES = 3


def _load() -> dict[str, list[dict]]:
    if not SESSION_HISTORY_PATH.is_file():
        return {}
    try:
        data = json.loads(SESSION_HISTORY_PATH.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("session_history.json parse failed, starting fresh", exc_info=True)
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, list[dict]] = {}
    for k, v in data.items():
        if isinstance(k, str) and isinstance(v, list):
            out[k] = [e for e in v if isinstance(e, dict) and isinstance(e.get("claude_sid"), str)]
    return out


def _save(history: dict[str, list[dict]]) -> None:
    # state.atomic_write_text を呼ぶと jsonl.history → state → jsonl の循環が起きるので
    # ここはローカル実装 (= tmp + replace)。
    SESSION_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SESSION_HISTORY_PATH.with_suffix(SESSION_HISTORY_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(SESSION_HISTORY_PATH)


def _size(entry: dict) -> int:
    """記録の大きさ。 file が在れば今の大きさ、 消えていれば積んだ時に控えた大きさ。

    終わった会話の記録は、 次の会話が起動した後はもう伸びないので、 在る間は file が真値。
    """
    path = entry.get("jsonl_path")
    if isinstance(path, str) and path:
        try:
            return Path(path).stat().st_size
        except OSError:
            # benign: the record was deleted (= a forked tab's record is cleaned up at restart);
            # the size noted when it was stacked stands in for it below.
            pass
    size = entry.get("size")
    return size if isinstance(size, int) and size >= 0 else 0


def _with_bases(entries: list[dict]) -> list[dict]:
    """起点 (= `base`) を持たない控え (= 起点を持つ前に積まれた物) に、 古い方から積んで起点を足す。"""
    running = 0
    for entry in reversed(entries):
        if not isinstance(entry.get("base"), int):
            entry["base"] = running
        running = entry["base"] + _size(entry)
    return entries


def ended(pwa_sid: str) -> list[tuple[Optional[Path], int]]:
    """終わった会話の記録の在処と起点を、 古い順に返す (= 在処を控えていない記録は None)。"""
    out: list[tuple[Optional[Path], int]] = []
    for entry in reversed(_with_bases(_load().get(pwa_sid, []))):
        path = entry.get("jsonl_path")
        out.append((Path(path) if isinstance(path, str) and path else None, entry["base"]))
    return out


def next_base(pwa_sid: str) -> int:
    """今の会話の記録の起点 (= 最後に終わった会話の記録の直後)。 終わった会話が無ければ 0。"""
    entries = _with_bases(_load().get(pwa_sid, []))
    if not entries:
        return 0
    return entries[0]["base"] + _size(entries[0])


def record_end(pwa_sid: str, claude_sid: Optional[str], jsonl_path: Optional[str] = None) -> None:
    """pwa_sid の終了イベントを履歴に追加。 claude_sid が None or 既に先頭と同一なら no-op。"""
    if not pwa_sid or not claude_sid:
        return
    history = _load()
    entries = _with_bases(history.get(pwa_sid, []))
    if entries and entries[0].get("claude_sid") == claude_sid:
        # 同じ id が連続で来た (= binding が既に新 sid に切り替わってない時の restart 等)。
        return
    base = 0
    if entries:
        # 1 つ前の会話はもう伸びない。 大きさを控え直してから、 その直後を起点にする
        # (= file が後で消えても、 起点と今の会話の位置が動かない)。
        entries[0]["size"] = _size(entries[0])
        base = entries[0]["base"] + entries[0]["size"]
    entry = {
        "claude_sid": claude_sid,
        "ended_at": int(time.time()),
        "base": base,
    }
    if jsonl_path:
        entry["jsonl_path"] = jsonl_path
        entry["size"] = _size(entry)
    entries.insert(0, entry)
    history[pwa_sid] = entries[:MAX_ENTRIES]
    try:
        _save(history)
        logger.info("session_history: recorded end pwa_sid=%s claude_sid=%s (kept=%d)",
                    pwa_sid, claude_sid, len(history[pwa_sid]))
    except Exception:
        logger.exception("session_history: save failed for pwa_sid=%s", pwa_sid)
