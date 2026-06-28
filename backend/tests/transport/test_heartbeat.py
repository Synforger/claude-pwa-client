"""ADR-013 heartbeat の backend 側半分 (= ping → pong reply) を pure 関数で test する。

frontend transport/ws-pty.ts は 25s 間隔で {"type": "ping", "ts": <client ms>} を send し、
60s pong 不在で force close (4000, heartbeat-timeout) → 再接続する設計。 backend は
handle_text_control() で ping を即 pong に変換、 副作用なし。 PTY や tmux に触らない経路なので
WS pump 全体をモックせず関数単体で round-trip を assert する。

contracts/schema/ws-channels.yaml § pty server_to_client の text frame oneOf にも対応 (=
{"type": "pong", "ts": <int>} の shape を満たす)。
"""
from __future__ import annotations

from backend.terminal.routes import handle_text_control


def test_ping_returns_pong_echoing_ts():
    """frontend 送信 ts をそのまま echo して返す (= client が往復遅延を測れる、 lastPong も同 ts で更新)。"""
    reply = handle_text_control({"type": "ping", "ts": 1234567890})
    assert reply == {"type": "pong", "ts": 1234567890}


def test_ping_without_ts_returns_pong_with_none_ts():
    """ts が無い不正 ping でも reply は生成 (= frontend 側で ts None を skip する、 throw しない)。"""
    reply = handle_text_control({"type": "ping"})
    assert reply == {"type": "pong", "ts": None}


def test_unknown_control_type_returns_none():
    """未対応 control は無視 (= 既存 resize / input 経路は呼び出し側で扱う)。"""
    assert handle_text_control({"type": "weird_thing"}) is None


def test_resize_returns_none_handled_by_caller():
    """resize は PTY 副作用を伴うので handle_text_control では扱わず None。"""
    assert handle_text_control({"type": "resize", "rows": 24, "cols": 80}) is None


def test_input_returns_none_handled_by_caller():
    """input も PTY write_pty を呼ぶので呼び出し側で扱う、 None を返す。"""
    assert handle_text_control({"type": "input", "data": "hello"}) is None


def test_non_dict_input_safely_returns_none():
    """異常値 (= str や None) でも throw せず None を返す (= graceful)。"""
    assert handle_text_control(None) is None  # type: ignore[arg-type]
    assert handle_text_control("ping") is None  # type: ignore[arg-type]
    assert handle_text_control([{"type": "ping"}]) is None  # type: ignore[arg-type]


def test_pong_reply_matches_contracts_schema():
    """contracts/schema/ws-channels.yaml § pty server_to_client text oneOf の pong shape に
    準拠 (= 必須 {type, ts}、 type=pong 限定)。"""
    from backend._generated.ws_channels import PtyServerToClient1V1
    reply = handle_text_control({"type": "ping", "ts": 999})
    # None ts は contracts では int 必須、 ここでは ts=None を生成側で許容 (= unit test の
    # test_ping_without_ts_returns_pong_with_none_ts) してるが実 backend pump では client が
    # ts を必ず付与する想定。 schema 準拠は ts 付き reply で確認。
    parsed = PtyServerToClient1V1.model_validate(reply)
    assert parsed.type == "pong" and parsed.ts == 999
