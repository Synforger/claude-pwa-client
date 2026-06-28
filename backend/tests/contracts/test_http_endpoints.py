"""contracts/schema/http-endpoints.yaml の生成 pydantic model が import + round-trip できることの smoke。
W3 で実 endpoint との shape 照合を加える前提。
"""
from __future__ import annotations

from pydantic import ValidationError
import pytest

from backend._generated import http_endpoints as http


def test_post_sessions_request_requires_agent_id():
    """POST /sessions Request: agent_id 必須、 title / account_id optional。"""
    assert hasattr(http, "PostSessionsRequest"), "missing PostSessionsRequest"
    parsed = http.PostSessionsRequest.model_validate({"agent_id": "default"})
    assert parsed.agent_id == "default"
    assert parsed.title is None
    # agent_id 抜けは reject
    with pytest.raises(ValidationError):
        http.PostSessionsRequest.model_validate({"title": "x"})


def test_post_sessions_response_round_trips():
    """POST /sessions Response: sid 必須。"""
    assert hasattr(http, "PostSessionsResponse"), "missing PostSessionsResponse"
    parsed = http.PostSessionsResponse.model_validate({"sid": "ses_abc"})
    assert parsed.sid == "ses_abc"


def test_post_fork_request_requires_from_uuid():
    """POST /sessions/{sid}/fork: from_uuid 必須。"""
    assert hasattr(http, "PostSessionsSidForkRequest"), "missing fork request"
    parsed = http.PostSessionsSidForkRequest.model_validate({"from_uuid": "u-0001"})
    assert parsed.from_uuid == "u-0001"


def test_push_subscribe_request_requires_subscription():
    """POST /push/subscribe: subscription field 必須 (= dict, redact 対象、 ADR-012)。"""
    assert hasattr(http, "PostPushSubscribeRequest"), "missing push subscribe request"
    parsed = http.PostPushSubscribeRequest.model_validate({
        "subscription": {"endpoint": "https://example.com/x"}
    })
    assert "endpoint" in parsed.subscription


def test_extra_forbid_on_http_models():
    """contract drift 検知: 未知 field 混入は ValidationError。"""
    with pytest.raises(ValidationError):
        http.PostSessionsRequest.model_validate({"agent_id": "x", "weird": True})


def test_pty_send_response_shape():
    """POST /pty/{sid}/send Response: ok 必須、 delivered/incomplete optional。"""
    assert hasattr(http, "PostPtySidSendResponse"), "missing pty send response"
    parsed = http.PostPtySidSendResponse.model_validate({"ok": True, "delivered": True})
    assert parsed.ok and parsed.delivered
    parsed_min = http.PostPtySidSendResponse.model_validate({"ok": False})
    assert parsed_min.ok is False
    assert parsed_min.delivered is None
