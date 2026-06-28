"""sensitive field の自動 mask + 長文 head/tail truncation。

ADR-012 採用 (= deny-list ベース + structlog processor 統合):
    - SENSITIVE_KEYS に該当する key の value は `***` に置き換え (= 大文字小文字無視)
    - 長文 (= TRUNCATE_THRESHOLD 超) は head + tail で省略 (= log file 肥大防止)
    - structlog の processor として組み込むため `redact_processor(logger, method, event_dict)` も提供

99-references.md § 12-3 で列挙された SENSITIVE_KEYS:
    api_key / apiKey / authorization / subscription / endpoint / p256dh / auth / vapid /
    secret / password / token + 派生 (= api-key / x-api-key / private_key 等)

長文 truncation policy:
    - threshold = 400 chars (= 通常の SSE event payload は 100-300、 余裕を持って)
    - head = 200, tail = 100、 中間に `... <N omitted> ...` marker
"""
from __future__ import annotations

from typing import Any

SENSITIVE_KEYS = frozenset({
    # API 認証系
    "api_key",
    "apikey",
    "api-key",
    "x-api-key",
    "x_api_key",
    "anthropic_api_key",
    "anthropic-api-key",
    "authorization",
    # Push subscription
    "subscription",
    "endpoint",
    "p256dh",
    "auth",
    # VAPID secret
    "vapid",
    "vapid_secret",
    "vapid_private_key",
    "private_key",
    # 一般
    "credentials",
    "password",
    "passwd",
    "token",
    "access_token",
    "refresh_token",
    "secret",
    "client_secret",
    "session_token",
})

REDACTED = "***"
TRUNCATE_THRESHOLD = 400
TRUNCATE_HEAD = 200
TRUNCATE_TAIL = 100


def _is_sensitive(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    return key.lower() in SENSITIVE_KEYS


def _truncate(value: str) -> str:
    n = len(value)
    if n <= TRUNCATE_THRESHOLD:
        return value
    omitted = n - TRUNCATE_HEAD - TRUNCATE_TAIL
    return f"{value[:TRUNCATE_HEAD]}... <{omitted} chars omitted> ...{value[-TRUNCATE_TAIL:]}"


def redact(payload: Any) -> Any:
    """dict / list / 単純型を受け、 sensitive key を `***` に置き換え + 長文 truncate した値を返す (= 非破壊)。

    recursive walk: dict は key 毎に判定、 list は各要素に再帰、 str は長さ閾値で truncate。
    bytes は decode 試行で str 化してから truncate (= 失敗時はそのまま)。
    """
    if isinstance(payload, dict):
        out: dict[Any, Any] = {}
        for k, v in payload.items():
            if _is_sensitive(k):
                out[k] = REDACTED
            else:
                out[k] = redact(v)
        return out
    if isinstance(payload, list):
        return [redact(v) for v in payload]
    if isinstance(payload, tuple):
        return tuple(redact(v) for v in payload)
    if isinstance(payload, str):
        return _truncate(payload)
    if isinstance(payload, bytes):
        try:
            return _truncate(payload.decode("utf-8"))
        except UnicodeDecodeError:
            return payload
    return payload


def redact_processor(logger: Any, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """structlog processor として使う。 event_dict を非破壊で walk 後の dict を返す。

    structlog は processor chain の戻り値を次 processor に渡すため、 dict のまま返す。
    """
    return redact(event_dict)
