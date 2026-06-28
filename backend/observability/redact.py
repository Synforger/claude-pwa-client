"""sensitive field の自動 mask。

W1 stub: API key / push subscription / VAPID secret / 個人 path 文字列を `***` に置き換える。
W3 本実装では structlog processor として組み込む + recursive nested dict / list 走査 + regex
ベースの heuristic を整える。

呼び出し例:
    >>> redact({"api_key": "sk-abc", "msg": "hello"})
    {"api_key": "***", "msg": "hello"}
"""
from __future__ import annotations

from typing import Any

# W3 で expand: regex pattern / nested 走査 / sensitive prefix / OS user path 等を整備
SENSITIVE_KEYS = frozenset({
    "api_key",
    "anthropic_api_key",
    "x_api_key",
    "authorization",
    "vapid_secret",
    "vapid_private_key",
    "private_key",
    "subscription",
    "credentials",
    "password",
    "token",
})

REDACTED = "***"


def redact(payload: Any) -> Any:
    """dict / list / 単純型を受け、 sensitive key を `***` に置き換えた値を返す (= 非破壊)。"""
    if isinstance(payload, dict):
        return {
            k: (REDACTED if k.lower() in SENSITIVE_KEYS else redact(v))
            for k, v in payload.items()
        }
    if isinstance(payload, list):
        return [redact(v) for v in payload]
    return payload
