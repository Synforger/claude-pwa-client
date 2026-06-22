"""pwa_sid → 直近 claude_sid 履歴の永続化。

セッション終了ボタン (= restart endpoint) で claude プロセスを kill する直前にその時点の
claude_sid を記録する。 binding が事故で消えた / 古い backup に戻った場合の復旧源として
backend ログ grep より速い参照経路を提供する。

設計:
- pwa_sid ごとに最新 N 件 (= 既定 3) を新しい順で保持。 N 件で打ち切るので肥大化しない。
- 同一 claude_sid の重複記録は無視 (= restart 連打や binding 復活で同じ id が流れ込んでも
  履歴を圧迫しない)。
- file IO は atomic_write_text で 1 ファイル全置換。 同時書き込みは想定外 (= restart は
  UI 経由で人手の 1 回 1 回)。
"""
from __future__ import annotations

import json
import logging
import time
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


def record_end(pwa_sid: str, claude_sid: Optional[str], jsonl_path: Optional[str] = None) -> None:
    """pwa_sid の終了イベントを履歴に追加。 claude_sid が None or 既に先頭と同一なら no-op。"""
    if not pwa_sid or not claude_sid:
        return
    history = _load()
    entries = history.get(pwa_sid, [])
    if entries and entries[0].get("claude_sid") == claude_sid:
        # 同じ id が連続で来た (= binding が既に新 sid に切り替わってない時の restart 等)。
        return
    entry = {
        "claude_sid": claude_sid,
        "ended_at": int(time.time()),
    }
    if jsonl_path:
        entry["jsonl_path"] = jsonl_path
    entries.insert(0, entry)
    history[pwa_sid] = entries[:MAX_ENTRIES]
    try:
        _save(history)
        logger.info("session_history: recorded end pwa_sid=%s claude_sid=%s (kept=%d)",
                    pwa_sid, claude_sid, len(history[pwa_sid]))
    except Exception:
        logger.exception("session_history: save failed for pwa_sid=%s", pwa_sid)


def get(pwa_sid: str) -> list[dict]:
    """pwa_sid の履歴を新しい順で返す (= 最大 MAX_ENTRIES 件)。"""
    return _load().get(pwa_sid, [])


def get_all() -> dict[str, list[dict]]:
    return _load()
