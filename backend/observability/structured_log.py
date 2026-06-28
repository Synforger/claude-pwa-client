"""structlog ベースの構造化 log writer。 ADR-012 採用。

processor chain (= 上から順に適用):
    1. structlog.contextvars.merge_contextvars : structlog.contextvars.bind_contextvars の値を merge
    2. add_trace_context                       : 自前 trace_ctx_var の trace.id / span.id を OTel field 名で追加
    3. add_iso_timestamp                       : @timestamp (= ISO 8601 UTC millisecond) を追加
    4. structlog.processors.add_log_level      : level 文字列を追加
    5. redact_processor                        : sensitive field を `***` 化 + 長文 truncate
    6. structlog.processors.JSONRenderer       : 最終 JSON 文字列化 (ensure_ascii=False で日本語そのまま)

logger 出力先:
    - structlog.PrintLoggerFactory(file=sys.stdout) で stdout (= uvicorn が拾う)
    - 別 file に書きたい場合は configure(logger_factory=...) で差し替え

OTel Semantic Conventions field 名 (= ADR-012):
    - trace.id, span.id  : current_trace_context() から
    - service.name       : 固定値 "claude-pwa-client-backend"
    - @timestamp         : ISO 8601 UTC milli

呼出例:
    from backend.observability.structured_log import logger
    logger.info("sse_event_emitted", sid="ses_abc", kind="user_message")
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Any

import structlog

from backend.observability.correlation import current_trace_context
from backend.observability.redact import redact_processor

SERVICE_NAME = "claude-pwa-client-backend"


def _add_trace_context(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """current_trace_context() の trace.id / span.id を event_dict に注入 (= OTel field 名)。"""
    ctx = current_trace_context()
    if ctx:
        if "trace.id" not in event_dict and ctx.get("trace_id"):
            event_dict["trace.id"] = ctx["trace_id"]
        if "span.id" not in event_dict and ctx.get("span_id"):
            event_dict["span.id"] = ctx["span_id"]
    return event_dict


def _add_iso_timestamp(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """@timestamp (= ISO 8601 UTC millisecond) を追加 (= ELK / OTel 慣習)。"""
    if "@timestamp" not in event_dict:
        ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        # `+00:00` を `Z` 表記に正規化 (= W3C ISO 8601 推奨)
        event_dict["@timestamp"] = ts.replace("+00:00", "Z")
    return event_dict


def _add_service_name(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """service.name を OTel Semantic Conventions field 名で追加。"""
    if "service.name" not in event_dict:
        event_dict["service.name"] = SERVICE_NAME
    return event_dict


def configure(file: Any | None = None) -> None:
    """structlog の global configure。 backend/main.py の lifespan startup で 1 回だけ呼ぶ想定。

    file: 既定 sys.stdout (= uvicorn が拾う)、 test では StringIO / 別 file に差替可能。

    test fixture で再 configure する時に出力先が反映されないと困るため reset_defaults() で
    キャッシュごと初期化する (= cache_logger_on_first_use の bound logger が前の file=
    を保持する挙動への対処)。
    """
    structlog.reset_defaults()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _add_service_name,
            _add_trace_context,
            _add_iso_timestamp,
            structlog.processors.add_log_level,
            redact_processor,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        logger_factory=structlog.PrintLoggerFactory(file=file or sys.stdout),
        # cache_logger_on_first_use=False: 最初の .info() で BoundLogger を materialize して cache
        # すると、 test fixture の再 configure() で出力先 (= file=) が反映されない。 cache を切ると
        # 毎回 BoundLogger 生成 (= ホット path で数 μs 増、 production の loop hot path にいないので OK)。
        cache_logger_on_first_use=False,
    )


# import 時に 1 回 configure (= test も含めて統一 setup)。 main.py の lifespan で再呼出しても idempotent。
configure()

logger = structlog.get_logger("cpc")


def get_logger(name: str | None = None) -> Any:
    """名前付き logger を返す (= module 別に名前を付けると filter 用途で便利)。"""
    return structlog.get_logger(name or "cpc")
