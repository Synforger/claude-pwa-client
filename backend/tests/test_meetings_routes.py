"""meetings.py の unit test。

掲示板は「追記された markdown」 という緩い形なので、 読む側が壊れないことを
pure 関数 (parse_board / parse_status) で押さえ、 endpoint 側は root 未設定と
id の扱い (= 存在しない / 壊れている / 木の外を指す) を押さえる。
"""
import asyncio

import pytest
from fastapi import HTTPException

import backend.routes.meetings as meetings


def _run(coro):
    return asyncio.run(coro)


def _payload(response):
    import json
    return json.loads(response.body)


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """<root>/proj/meetings/{topic,_archive/old,_template} を作って root に向ける。"""
    root = tmp_path / "state"
    active = root / "proj" / "meetings" / "sdk-bindings"
    archived = root / "proj" / "meetings" / "_archive" / "old-topic"
    template = root / "proj" / "meetings" / "_template"
    for d in (active, archived, template):
        d.mkdir(parents=True)
    (active / "board.md").write_text("# 掲示板\n\n注意書き。 発言ではない。\n", encoding="utf-8")
    (active / "status.md").write_text("", encoding="utf-8")
    (archived / "board.md").write_text("", encoding="utf-8")
    (template / "board.md").write_text("", encoding="utf-8")
    monkeypatch.setattr(meetings, "MEETINGS_ROOT", root)
    return root


# --- root が無い時 ---------------------------------------------------------

def test_unconfigured_root_is_404_not_empty(monkeypatch):
    """未設定は 404。 空配列にすると 「機能が無い」 と 「会議が 0 件」 が混ざる。"""
    monkeypatch.setattr(meetings, "MEETINGS_ROOT", None)
    with pytest.raises(HTTPException) as exc:
        _run(meetings.list_meetings())
    assert exc.value.status_code == 404


# --- 一覧 -------------------------------------------------------------------

def test_list_separates_active_and_archived_and_skips_template(tree):
    items = _payload(_run(meetings.list_meetings()))
    by_topic = {i["topic"]: i for i in items}
    assert by_topic["sdk-bindings"]["state"] == "active"
    assert by_topic["old-topic"]["state"] == "archived"
    assert "_template" not in by_topic
    assert by_topic["sdk-bindings"]["tier"] == "proj"


# --- id の扱い --------------------------------------------------------------

def test_unknown_and_malformed_ids_are_404(tree):
    for bad in ("not-base64!!", "", meetings._encode_id("proj", "no-such", "active")):
        with pytest.raises(HTTPException) as exc:
            _run(meetings.get_meeting(bad))
        assert exc.value.status_code == 404


def test_id_escaping_the_root_is_404(tree):
    """id は不透明でも手で作れる。 復号値を繋いだ先が root の外なら拒む。"""
    escaped = meetings._encode_id("../../..", "etc", "active")
    with pytest.raises(HTTPException) as exc:
        _run(meetings.get_meeting(escaped))
    assert exc.value.status_code == 404


# --- 掲示板のパース ---------------------------------------------------------

def test_parse_board_reads_four_acts_and_keeps_the_rest():
    text = """# 掲示板

使い方の注記。 発言ではないので落ちる。

## 04:10 @司令塔
指示: @swift 待機

## 04:12 @swift
報告: startStream 実装完了
テストは 12 本緑

## 04:20 @swift
異議: onError が同期前提

## 04:25 @司令塔
裁定: 通す。 契約を v2 へ

## 04:30 @godot
雑談のような行
"""
    posts = meetings.parse_board(text)
    assert [p["kind"] for p in posts] == [
        "directive", "report", "objection", "ruling", "other",
    ]
    # 見出しより前の注記は発言にならない
    assert all("使い方の注記" not in p["body"] for p in posts)
    # 続きの行は直前の発言に足される (= 千切らない)
    assert posts[1]["body"] == "startStream 実装完了\nテストは 12 本緑"
    assert posts[0]["who"] == "司令塔" and posts[0]["at"] == "04:10"


def test_parse_board_accepts_a_dated_header():
    posts = meetings.parse_board("## 2026-08-10 04:12 @swift\n報告: ok\n")
    assert posts[0]["at"] == "2026-08-10 04:12"
    assert posts[0]["who"] == "swift"


def test_parse_board_on_empty_text():
    assert meetings.parse_board("") == []


# --- 現在地のパース ---------------------------------------------------------

def test_parse_status_picks_columns_by_heading_not_position():
    text = """# 現在地

| 状態 | 担当 | 今どこ | 契約の版 | 最終確認 |
|---|---|---|---|---|
| 進行中 | @swift | startStream | v2 | 04:12 |
| 待機 | @godot | - | v1 | 03:58 |
"""
    rows = meetings.parse_status(text)
    assert rows[0] == {
        "name": "swift", "version": "v2", "state": "進行中",
        "note": "startStream", "read_at": "04:12",
    }
    assert rows[1]["name"] == "godot" and rows[1]["state"] == "待機"


def test_parse_status_without_a_name_column_is_empty():
    """見出しが読めない table は空。 誤った列を状態として出すより安全。"""
    text = "| a | b |\n|---|---|\n| 1 | 2 |\n"
    assert meetings.parse_status(text) == []


def test_parse_status_on_empty_text():
    assert meetings.parse_status("") == []


# --- 追記 -------------------------------------------------------------------

def test_append_adds_a_block_and_keeps_existing_text(tree):
    mid = meetings._encode_id("proj", "sdk-bindings", "active")
    before = (tree / "proj" / "meetings" / "sdk-bindings" / "board.md").read_text(encoding="utf-8")
    body = meetings.PostBody(who="@operator", kind="directive", body="計画書どおりに進める")
    _run(meetings.append_post(mid, body))
    after = (tree / "proj" / "meetings" / "sdk-bindings" / "board.md").read_text(encoding="utf-8")
    assert after.startswith(before)
    assert "指示: 計画書どおりに進める" in after
    posts = meetings.parse_board(after)
    assert posts[-1]["kind"] == "directive" and posts[-1]["who"] == "operator"


def test_append_rejects_a_kind_outside_the_four(tree):
    mid = meetings._encode_id("proj", "sdk-bindings", "active")
    body = meetings.PostBody(who="operator", kind="other", body="自由記述")
    with pytest.raises(HTTPException) as exc:
        _run(meetings.append_post(mid, body))
    assert exc.value.status_code == 422


def test_append_to_a_closed_meeting_is_409(tree):
    mid = meetings._encode_id("proj", "old-topic", "archived")
    body = meetings.PostBody(who="operator", kind="directive", body="まだ何か言いたい")
    with pytest.raises(HTTPException) as exc:
        _run(meetings.append_post(mid, body))
    assert exc.value.status_code == 409


def test_append_requires_who_and_body(tree):
    mid = meetings._encode_id("proj", "sdk-bindings", "active")
    for who, text in (("", "x"), ("operator", "   ")):
        with pytest.raises(HTTPException) as exc:
            _run(meetings.append_post(mid, meetings.PostBody(who=who, kind="report", body=text)))
        assert exc.value.status_code == 422
