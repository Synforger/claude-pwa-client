"""ADR-012 inspector: /debug/state endpoint の中身組立。

backend の in-memory state を 1 枚の dict に scoop して frontend debug panel が読みやすい形で返す。
- sensitive field は redact 経由
- 巨大 field (= 完全 message 履歴) は count + head/tail だけ抜く (= response size 爆発防止)
- 触らない方が安全な field (= asyncio.Queue 本体) は size だけ返す
"""
from __future__ import annotations

from typing import Any

from backend.observability.redact import redact


def _safe_attr(obj: Any, name: str, default: Any = None) -> Any:
    """getattr の安全版。 例外時は default を返す (= debug endpoint は壊れた state でも 200 で返す)。"""
    try:
        return getattr(obj, name, default)
    except Exception:
        return default


def _summarize_collection(value: Any, head: int = 3) -> Any:
    """list / dict / set を「サイズ + 先頭 N 件」 だけ抜く (= 巨大 collection の response size 爆発防止)。

    head 件は redact() を通す。
    """
    if isinstance(value, dict):
        keys = list(value.keys())
        return {
            "type": "dict",
            "size": len(keys),
            "keys_head": keys[:head],
        }
    if isinstance(value, list):
        return {
            "type": "list",
            "size": len(value),
            "head": redact(value[:head]),
        }
    if isinstance(value, set):
        return {
            "type": "set",
            "size": len(value),
            "head": redact(list(value)[:head]),
        }
    return None


def snapshot() -> dict[str, Any]:
    """全 in-memory state を 1 dict に scoop する (= /debug/state レスポンス本体)。

    ベスト effort: 取れない field は None / "unavailable" にして、 partial でも返す。 production の
    backend が部分壊れでも /debug/state で原因が見えるべき (= 「壊れてるから debug できません」 NG)。
    """
    out: dict[str, Any] = {}

    # backend.state — sessions / streams / status / overview など in-memory state の集合点
    try:
        import backend.state as bs

        out["sessions_meta"] = _summarize_collection(_safe_attr(bs, "sessions_meta", {}))
        out["stream_states"] = _summarize_collection(_safe_attr(bs, "stream_states", {}))
        out["sessions_overview"] = _summarize_collection(_safe_attr(bs, "sessions_overview", {}))
        out["agent_status"] = _summarize_collection(_safe_attr(bs, "agent_status", {}))
        broadcaster = _safe_attr(bs, "jsonl_event_broadcaster")
        if broadcaster is not None:
            subs = _safe_attr(broadcaster, "_subscribers", None)
            if isinstance(subs, dict):
                out["jsonl_event_broadcaster"] = {
                    "subscriber_keys_count": len(subs),
                    "subscriber_keys_head": list(subs.keys())[:5],
                }
            else:
                out["jsonl_event_broadcaster"] = {"available": True}
        else:
            out["jsonl_event_broadcaster"] = {"available": False}
    except Exception as e:  # pragma: no cover - defensive
        out["backend_state_error"] = str(e)

    # observability metrics snapshot
    try:
        from backend.observability.metrics import metrics

        out["metrics"] = metrics.snapshot()
    except Exception as e:  # pragma: no cover - defensive
        out["metrics_error"] = str(e)

    # event_journal の現在 sequence (= replay の進捗目安)
    try:
        from backend.observability.event_journal import _sequencer

        out["event_journal"] = {"current_seq": _sequencer.peek()}
    except Exception as e:  # pragma: no cover - defensive
        out["event_journal_error"] = str(e)

    return out


__all__ = ["snapshot"]
