"""ADR-012 sensitive field redact + 長文 truncation の動作検証。"""
from __future__ import annotations

import pytest

from backend.observability.redact import (
    REDACTED,
    SENSITIVE_KEYS,
    TRUNCATE_HEAD,
    TRUNCATE_TAIL,
    TRUNCATE_THRESHOLD,
    _truncate,
    redact,
    redact_processor,
)


# --- deny-list mask ------------------------------------------------------


@pytest.mark.parametrize("key", [
    "api_key", "API_KEY", "Api-Key",
    "x-api-key", "x_api_key",
    "anthropic_api_key", "anthropic-api-key",
    "authorization", "Authorization",
    "subscription", "endpoint", "p256dh", "auth",
    "vapid", "vapid_secret", "vapid_private_key", "private_key",
    "credentials", "password", "passwd",
    "token", "access_token", "refresh_token",
    "secret", "client_secret", "session_token",
])
def test_redact_masks_sensitive_keys_case_insensitive(key):
    out = redact({key: "some-secret-value", "ok": "kept"})
    assert out[key] == REDACTED
    assert out["ok"] == "kept"


def test_redact_nested_dict():
    out = redact({"outer": {"token": "t", "safe": 1}, "list": [{"password": "p"}, {"safe": 2}]})
    assert out["outer"]["token"] == REDACTED
    assert out["outer"]["safe"] == 1
    assert out["list"][0]["password"] == REDACTED
    assert out["list"][1]["safe"] == 2


def test_redact_preserves_non_dict_non_list_types():
    assert redact(None) is None
    assert redact(42) == 42
    assert redact(True) is True
    assert redact("short") == "short"


def test_redact_tuple_recurses_into_elements():
    out = redact(({"token": "t"}, "short", 1))
    assert isinstance(out, tuple)
    assert out[0]["token"] == REDACTED
    assert out[1] == "short"
    assert out[2] == 1


def test_redact_does_not_mutate_input():
    payload = {"api_key": "leak", "nested": {"token": "t"}}
    out = redact(payload)
    assert payload["api_key"] == "leak"
    assert payload["nested"]["token"] == "t"
    assert out["api_key"] == REDACTED


def test_sensitive_keys_is_lowercase_only():
    """deny-list の全 key は lowercase (= 大文字小文字無視 check は呼出側で .lower())。"""
    for k in SENSITIVE_KEYS:
        assert k == k.lower(), f"{k!r} is not lowercase in SENSITIVE_KEYS"


# --- 長文 truncation -----------------------------------------------------


def test_truncate_short_value_unchanged():
    s = "x" * TRUNCATE_THRESHOLD
    assert _truncate(s) == s


def test_truncate_long_value_with_marker():
    s = "x" * (TRUNCATE_THRESHOLD + 200)
    out = _truncate(s)
    assert "chars omitted" in out
    assert out.startswith("x" * TRUNCATE_HEAD)
    assert out.endswith("x" * TRUNCATE_TAIL)
    assert len(out) < len(s)


def test_redact_truncates_long_strings_in_dict():
    long_value = "y" * (TRUNCATE_THRESHOLD + 100)
    out = redact({"normal": "ok", "long": long_value})
    assert out["normal"] == "ok"
    assert "chars omitted" in out["long"]


def test_redact_truncates_bytes_via_utf8_decode():
    long_bytes = b"z" * (TRUNCATE_THRESHOLD + 100)
    out = redact({"blob": long_bytes})
    assert "chars omitted" in out["blob"]


def test_redact_keeps_undecodable_bytes_as_is():
    # 0xff は単独で UTF-8 として不正
    raw = b"\xff" * (TRUNCATE_THRESHOLD + 100)
    out = redact({"blob": raw})
    assert out["blob"] == raw  # decode 失敗時は素通し


# --- structlog processor -------------------------------------------------


def test_redact_processor_returns_dict():
    out = redact_processor(None, "info", {"api_key": "k", "msg": "hello"})
    assert isinstance(out, dict)
    assert out["api_key"] == REDACTED
    assert out["msg"] == "hello"


def test_redact_processor_does_not_mutate_input():
    payload = {"token": "t", "safe": 1}
    out = redact_processor(None, "info", payload)
    assert payload["token"] == "t"
    assert out["token"] == REDACTED
