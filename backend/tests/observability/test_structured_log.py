"""ADR-012 structlog ベース構造化 log writer の動作検証。

確認項目:
    - JSON 1 line で出力される
    - service.name (= OTel Semantic Conventions) が必ず付く
    - @timestamp が ISO 8601 UTC Z 表記
    - level / event が structlog 標準で付く
    - trace_context_scope 内で trace.id / span.id が注入される
    - scope 外 (= ContextVar 未設定) では trace.id / span.id が出ない
    - sensitive field (= api_key 等) は自動 redact
    - 長文 (= TRUNCATE_THRESHOLD 超) は head + tail に truncate
    - 日本語が ensure_ascii=False でそのまま出力
    - structlog.contextvars.bind_contextvars で global context が merge される
"""
from __future__ import annotations

import io
import json
import re

import pytest
import structlog

from backend.observability.correlation import new_traceparent, parse_traceparent, trace_context_scope
from backend.observability.structured_log import SERVICE_NAME, configure, get_logger, logger


@pytest.fixture
def captured() -> io.StringIO:
    """1 行ずつ JSON が書き込まれる buffer。 各 test の冒頭で configure() を差し替える。

    cache_logger_on_first_use=False なので、 既に import 済の module top-level `logger` も
    再 configure 後の出力先 (= 本 buf) に書き出す。
    """
    buf = io.StringIO()
    configure(file=buf)
    yield buf
    configure()


def _last_line(buf: io.StringIO) -> dict:
    raw = buf.getvalue().strip().splitlines()
    assert raw, "no log lines emitted"
    return json.loads(raw[-1])


def test_log_emits_json_with_service_name(captured):
    logger.info("hello", k="v")
    line = _last_line(captured)
    assert line["service.name"] == SERVICE_NAME
    assert line["event"] == "hello"
    assert line["k"] == "v"
    assert line["level"] == "info"


def test_log_timestamp_iso_8601_z(captured):
    logger.info("ts_test")
    line = _last_line(captured)
    ts = line["@timestamp"]
    # ISO 8601 with millisecond + Z (例: 2026-06-28T07:46:26.944Z)
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$", ts), ts


def test_log_injects_trace_id_and_span_id_within_scope(captured):
    ctx = parse_traceparent(new_traceparent())
    assert ctx is not None
    with trace_context_scope(ctx):
        logger.info("traced")
    line = _last_line(captured)
    assert line["trace.id"] == ctx["trace_id"]
    assert line["span.id"] == ctx["span_id"]


def test_log_omits_trace_fields_outside_scope(captured):
    logger.info("untraced")
    line = _last_line(captured)
    assert "trace.id" not in line
    assert "span.id" not in line


def test_log_redacts_sensitive_field(captured):
    logger.info("authn_attempt", api_key="sk-leak-me", user="ok")
    line = _last_line(captured)
    assert line["api_key"] == "***"
    assert line["user"] == "ok"


def test_log_truncates_long_value(captured):
    long_val = "x" * 1000
    logger.info("big_payload", body=long_val)
    line = _last_line(captured)
    assert "chars omitted" in line["body"]
    assert len(line["body"]) < len(long_val)


def test_log_keeps_japanese_unescaped(captured):
    logger.info("日本語イベント", msg="こんにちは")
    line = _last_line(captured)
    assert line["event"] == "日本語イベント"
    assert line["msg"] == "こんにちは"


def test_log_merges_contextvars(captured):
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(sid="ses_xyz", user_id="u1")
    try:
        logger.info("bound")
    finally:
        structlog.contextvars.clear_contextvars()
    line = _last_line(captured)
    assert line["sid"] == "ses_xyz"
    assert line["user_id"] == "u1"


def test_get_logger_returns_named_logger(captured):
    sub = get_logger("cpc.sub")
    sub.info("from_sub")
    line = _last_line(captured)
    assert line["event"] == "from_sub"


def test_log_does_not_overwrite_explicit_service_name(captured):
    """呼出側が明示的に service.name を渡したら尊重 (= 多 service テスト fixture 用)。"""
    logger.info("override", **{"service.name": "test-runner"})
    line = _last_line(captured)
    assert line["service.name"] == "test-runner"


def test_log_does_not_overwrite_explicit_timestamp(captured):
    """呼出側が明示的に @timestamp を渡したら尊重 (= replay の元 ts を保持)。"""
    logger.info("replayed", **{"@timestamp": "2020-01-01T00:00:00.000Z"})
    line = _last_line(captured)
    assert line["@timestamp"] == "2020-01-01T00:00:00.000Z"
