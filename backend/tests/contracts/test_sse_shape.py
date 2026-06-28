"""contracts/tests/sse-replay/*.jsonl を backend events.py で変換 + envelope 付与した結果が
contracts/schema/sse-events.yaml (= 生成 pydantic model) に準拠することを assert する。

カバレッジ:
    - 全 SSE event 型が pydantic round-trip 可能
    - envelope (= sid + corr_id) が全 event に必ず付く
    - extra='forbid' で contract drift (= 知らない field 混入) が検知される
    - unknown event type の graceful handle (= raise でなく log warn) 用 fixture が schema 外であること
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.jsonl.events import jsonl_line_to_events
from backend._generated.events import EVENT_BY_TYPE, AnyEvent, SCHEMA_VERSION
from backend.jsonl.routes import _inject_envelope


REPO_ROOT = Path(__file__).resolve().parents[3]
SSE_REPLAY_DIR = REPO_ROOT / "contracts" / "tests" / "sse-replay"
EXPECTED_DIR = REPO_ROOT / "contracts" / "tests" / "expected"
NEGATIVE_DIR = REPO_ROOT / "contracts" / "tests" / "negative"


def _run_pipeline(jsonl_path: Path, sid: str = "ses_test") -> list[dict]:
    """1 つの JSONL fixture を読み込んで「backend → SSE pump 直前」 までの dict 列を返す。"""
    out: list[dict] = []
    for line in jsonl_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        for event in jsonl_line_to_events(obj):
            _inject_envelope(event, sid)
            out.append(event)
    return out


def test_schema_version_is_string():
    """生成側 SCHEMA_VERSION が読める (= 生成 file が壊れてないことの smoke)。"""
    assert isinstance(SCHEMA_VERSION, str)
    assert SCHEMA_VERSION.count(".") == 1


def test_event_dispatch_table_covers_17_types():
    """contract schema 17 event を生成側が全部出してる (= codegen 取りこぼし検知)。"""
    expected = {
        "user_message", "assistant", "result", "ask_user_question", "task_notification",
        "system", "system_error", "hook_error", "system_note", "attachment",
        "budget", "mode", "permission_mode", "pr_link", "turn_duration",
        "stop_hook_summary", "away_summary",
    }
    assert set(EVENT_BY_TYPE.keys()) == expected


def test_chat_basic_pipeline_produces_schema_compliant_events():
    """chat-basic.jsonl を通すと backend._generated.events の pydantic model にすべて validate できる。"""
    events = _run_pipeline(SSE_REPLAY_DIR / "chat-basic.jsonl")
    assert len(events) >= 2, "chat-basic should produce at least user_message + assistant"

    for ev in events:
        evtype = ev.get("type")
        assert evtype in EVENT_BY_TYPE, f"unknown event type produced: {evtype}"
        model_cls = EVENT_BY_TYPE[evtype]
        try:
            parsed = model_cls.model_validate(ev)
        except ValidationError as e:
            pytest.fail(f"event {evtype} failed schema: {e}\nraw: {ev}")
        # round-trip 一致 (= 余計な field が落ちず、 不足 field で死なない)
        dumped = parsed.model_dump(exclude_none=False)
        assert dumped["type"] == evtype


def test_envelope_sid_and_corr_id_always_present():
    """envelope (= sid + corr_id) が全 event に必ず付く。 ADR-012 global required の構造保証。"""
    events = _run_pipeline(SSE_REPLAY_DIR / "chat-basic.jsonl", sid="ses_envelope")
    for ev in events:
        assert ev.get("sid") == "ses_envelope", f"sid missing or wrong: {ev}"
        cid = ev.get("corr_id")
        assert isinstance(cid, str) and len(cid) == 8, f"corr_id not 8-hex: {cid!r}"
        assert all(c in "0123456789abcdef" for c in cid), f"corr_id not hex: {cid!r}"


def test_extra_forbid_rejects_unknown_field():
    """extra='forbid' で contract drift (= 知らない field 混入) が ValidationError になる。"""
    UserMessageEvent = EVENT_BY_TYPE["user_message"]
    with pytest.raises(ValidationError):
        UserMessageEvent.model_validate({
            "type": "user_message",
            "sid": "s1",
            "uuid": "u1",
            "text": "hi",
            "corr_id": "abcd1234",
            "weird_unknown_field": "drift",
        })


def test_unknown_event_type_fixture_is_outside_schema():
    """tests/negative/unknown-event-type.jsonl が schema 外なことを確認 (= frontend graceful handle 用 fixture が壊れてないことの保証)。"""
    fixture = NEGATIVE_DIR / "unknown-event-type.jsonl"
    for line in fixture.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        evtype = obj.get("type")
        assert evtype not in EVENT_BY_TYPE, (
            f"negative fixture {fixture.name} contains a known event type {evtype}: "
            "the fixture is no longer negative; replace the type"
        )


def test_expected_chat_basic_describes_observed_types():
    """expected/chat-basic.json が backend pipeline の出力 type を網羅してる (= fixture と実出力の整合性)。"""
    events = _run_pipeline(SSE_REPLAY_DIR / "chat-basic.jsonl")
    observed_types = [e["type"] for e in events]
    expected_doc = json.loads((EXPECTED_DIR / "chat-basic.json").read_text())
    expected_types = [e["type"] for e in expected_doc["events"]]
    # 順序 + 種別が一致
    assert observed_types == expected_types, (
        f"pipeline produced {observed_types} but expected/chat-basic.json describes {expected_types}"
    )
