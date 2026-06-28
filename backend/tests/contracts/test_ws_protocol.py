"""contracts/schema/ws-channels.yaml の各 channel frame schema が生成 pydantic で round-trip
できることを確認する。 W3 で実 WS pump との照合を加える前提の smoke。
"""
from __future__ import annotations

from pydantic import ValidationError
import pytest

from backend._generated import ws_channels as ws


def test_pty_client_resize_frame_roundtrips():
    """PTY channel client→server resize frame: rows/cols 必須、 型一致。"""
    # 生成 model は PtyClientToServer1V0 (= text frame oneOf の 0 番目 = resize)。
    assert hasattr(ws, "PtyClientToServer1V0"), "missing resize variant model"
    model = ws.PtyClientToServer1V0
    parsed = model.model_validate({"type": "resize", "rows": 24, "cols": 80})
    assert parsed.rows == 24 and parsed.cols == 80


def test_pty_client_ping_frame_roundtrips():
    """PTY channel client→server ping frame: ADR-013 heartbeat 25s 経路の wire 定義。"""
    assert hasattr(ws, "PtyClientToServer1V1"), "missing ping variant model"
    parsed = ws.PtyClientToServer1V1.model_validate({"type": "ping", "ts": 1234567890})
    assert parsed.ts == 1234567890


def test_pty_server_pong_frame_roundtrips():
    """PTY channel server→client pong frame: ping の ts を echo して返す (= heartbeat 完結)。"""
    assert hasattr(ws, "PtyServerToClient1V1"), "missing pong variant model"
    parsed = ws.PtyServerToClient1V1.model_validate({"type": "pong", "ts": 1234567890})
    assert parsed.type == "pong"


def test_pty_server_exit_frame_roundtrips():
    """PTY channel server→client exit / error frame: enum [exit, error]、 message optional。"""
    assert hasattr(ws, "PtyServerToClient1V0"), "missing exit/error variant model"
    parsed = ws.PtyServerToClient1V0.model_validate({"type": "exit", "message": "claude finished"})
    assert parsed.type == "exit"
    # message 不在でも OK
    parsed2 = ws.PtyServerToClient1V0.model_validate({"type": "error"})
    assert parsed2.message is None


def test_pty_resize_rejects_wrong_type_field():
    """const 'resize' 制約: 別 type を混ぜたら drift 検知。"""
    with pytest.raises(ValidationError):
        ws.PtyClientToServer1V0.model_validate({"type": "ping", "rows": 24, "cols": 80})


def test_views_set_active_sid_frame_roundtrips():
    """views channel client→server: {sid: str | null}。 null = 全タブ非表示。"""
    assert hasattr(ws, "ViewsClientToServer0V0"), "missing views set-sid model"
    parsed = ws.ViewsClientToServer0V0.model_validate({"sid": "ses_abc"})
    assert parsed.sid == "ses_abc"
    parsed_null = ws.ViewsClientToServer0V0.model_validate({"sid": None})
    assert parsed_null.sid is None


def test_views_stop_intent_frame_roundtrips():
    """views channel client→server stop intent: {type: stop, sid}。"""
    assert hasattr(ws, "ViewsClientToServer0V1"), "missing views stop model"
    parsed = ws.ViewsClientToServer0V1.model_validate({"type": "stop", "sid": "ses_abc"})
    assert parsed.sid == "ses_abc"
