"""タブの記録の並び (= backend/jsonl/chain.py) と、 終わった会話の控えの起点 (= backend/jsonl/history.py)。

担保する事:
1. 画面を閉じている間に会話が入れ替わっても、 開いた時に前の会話の残り (= 締めの作業と入れ替えの発話) から
   今の会話まで繋がって流れる (= 流し直し / 履歴 GET / live の 3 経路とも同じ通しの位置)
2. 今の会話の記録が前の会話の offset より育っても、 今の会話の頭を飛ばさない
3. 起点は積んだ時に決まり、 古い記録が消えても動かない
"""
import json

import backend.jsonl.routes as jr
import backend.routes.unified_stream as us
import backend.state as state_mod
from backend.jsonl import chain, history

SID = "ses_chain"


def _line(uuid: str, text: str) -> str:
    return json.dumps({"type": "user", "uuid": uuid, "message": {"content": text}}) + "\n"


def _write(path, *pairs) -> None:
    path.write_text("".join(_line(u, t) for u, t in pairs), encoding="utf-8")


def _texts(pairs) -> list[str]:
    return [json.loads(raw)["message"]["content"] for raw, _pos in pairs]


def _rolled_over(tmp_path):
    """前の会話 (= 締めの作業まで) を終えて、 今の会話が始まったタブ。 返り値 (前, 今, 画面が見ていた位置)。"""
    prev = tmp_path / "prev.jsonl"
    _write(prev, ("p1", "before"), ("p2", "seen last"))
    seen = prev.stat().st_size  # 画面はここまで見て閉じた
    _write(prev, ("p1", "before"), ("p2", "seen last"),
           ("p3", "please wrap up"), ("p4", "wrapping up"))
    history.record_end(SID, "prev", str(prev))
    cur = tmp_path / "cur.jsonl"
    _write(cur, ("c1", "rollover start"), ("c2", "next session"))
    return prev, cur, seen


# --- 控えの起点 -------------------------------------------------------------

def test_bases_follow_the_ended_records_in_order(tmp_path):
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    _write(a, ("a1", "x"))
    _write(b, ("b1", "yy"), ("b2", "zz"))
    history.record_end(SID, "a", str(a))
    history.record_end(SID, "b", str(b))
    assert history.ended(SID) == [(a, 0), (b, a.stat().st_size)]
    assert history.next_base(SID) == a.stat().st_size + b.stat().st_size


def test_base_does_not_move_when_an_ended_record_is_deleted(tmp_path):
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    _write(a, ("a1", "x"))
    _write(b, ("b1", "y"))
    history.record_end(SID, "a", str(a))
    history.record_end(SID, "b", str(b))
    before = history.next_base(SID)
    a.unlink()
    b.unlink()
    assert history.next_base(SID) == before


def test_base_does_not_move_when_the_oldest_entry_drops_off(tmp_path):
    paths = [tmp_path / f"{i}.jsonl" for i in range(history.MAX_ENTRIES + 1)]
    for i, p in enumerate(paths):
        _write(p, (f"u{i}", "x" * (i + 1)))
    for i, p in enumerate(paths[:-1]):
        history.record_end(SID, str(i), str(p))
    base_of_last = history.ended(SID)[-1][1]
    history.record_end(SID, "last", str(paths[-1]))
    assert len(history.ended(SID)) == history.MAX_ENTRIES
    assert history.ended(SID)[-2][1] == base_of_last


def test_entries_written_before_bases_get_them_oldest_first(tmp_path):
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    _write(a, ("a1", "x"))
    _write(b, ("b1", "y"))
    history.SESSION_HISTORY_PATH.write_text(json.dumps({SID: [
        {"claude_sid": "b", "ended_at": 2, "jsonl_path": str(b)},
        {"claude_sid": "a", "ended_at": 1, "jsonl_path": str(a)},
    ]}), encoding="utf-8")
    assert history.ended(SID) == [(a, 0), (b, a.stat().st_size)]


# --- つないだ記録を読む -----------------------------------------------------

def test_reopening_after_a_rollover_replays_the_rest_of_the_previous_session(tmp_path):
    prev, cur, seen = _rolled_over(tmp_path)
    pairs, end = chain.read(chain.segments(SID, cur), seen, 500)
    assert _texts(pairs) == ["please wrap up", "wrapping up", "rollover start", "next session"]
    assert end == prev.stat().st_size + cur.stat().st_size
    assert [pos for _raw, pos in pairs] == sorted(pos for _raw, pos in pairs)


def test_opening_without_an_offset_shows_the_previous_session_under_a_short_one(tmp_path):
    _prev, cur, _seen = _rolled_over(tmp_path)
    pairs, _end = chain.read(chain.segments(SID, cur), None, 500)
    assert _texts(pairs) == ["before", "seen last", "please wrap up", "wrapping up",
                             "rollover start", "next session"]


def test_the_window_is_the_last_lines_across_the_sessions(tmp_path):
    _prev, cur, _seen = _rolled_over(tmp_path)
    pairs, _end = chain.read(chain.segments(SID, cur), None, 3)
    assert _texts(pairs) == ["wrapping up", "rollover start", "next session"]


def test_an_offset_inside_the_current_session_reads_only_its_tail(tmp_path):
    prev, cur, _seen = _rolled_over(tmp_path)
    first_line = len(_line("c1", "rollover start").encode())
    pairs, _end = chain.read(chain.segments(SID, cur), prev.stat().st_size + first_line, 500)
    assert _texts(pairs) == ["next session"]


def test_a_current_session_longer_than_the_previous_offset_keeps_its_head(tmp_path):
    """file ごとの位置だった頃は、 前の会話の offset を今の会話の中の位置と読んで、 頭を飛ばしていた。"""
    prev, cur, _seen = _rolled_over(tmp_path)
    _write(cur, *[(f"c{i}", "long " * 20) for i in range(20)])
    assert cur.stat().st_size > prev.stat().st_size
    pairs, _end = chain.read(chain.segments(SID, cur), prev.stat().st_size, 500)
    assert len(pairs) == 20


def test_without_a_running_session_the_ended_one_is_still_shown(tmp_path):
    _rolled_over(tmp_path)
    pairs, _end = chain.read(chain.segments(SID, None), None, 500)
    assert _texts(pairs)[-1] == "wrapping up"


# --- 3 経路 (= 流し直し / 履歴 GET / live) ---------------------------------

def test_stream_replay_carries_the_previous_session(isolated_state, tmp_path, monkeypatch):
    _prev, cur, seen = _rolled_over(tmp_path)
    monkeypatch.setattr("backend.jsonl.routes.jsonl_path_for_session", lambda s: cur)
    frames = us._replay_frames(SID, seen)
    texts = [f["ev"].get("text") for f in frames if f["ev"].get("type") == "user_message"]
    assert texts == ["please wrap up", "wrapping up", "rollover start", "next session"]


def test_history_get_carries_the_previous_session(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    prev, cur, _seen = _rolled_over(tmp_path)
    monkeypatch.setattr(jr, "_latest_jsonl", lambda sid: cur)
    app = FastAPI()
    app.include_router(jr.router)
    data = TestClient(app).get(f"/jsonl/history/{SID}").json()
    texts = [e.get("text") for e in data["events"] if e.get("type") == "user_message"]
    assert texts[0] == "before" and texts[-1] == "next session"
    assert data["pos"] == prev.stat().st_size + cur.stat().st_size


def test_live_lines_carry_the_position_across_the_sessions(isolated_state, tmp_path, monkeypatch):
    """`/clear` など口を通らない切り替えも、 見張りが見つけて控えに積み、 今の会話の行を前の会話の後ろに置く。"""
    state_mod.stream_states[SID] = state_mod.StreamState(agent_id="a")
    state_mod.agent_status[SID] = state_mod._make_agent_status("a")
    prev = tmp_path / "prev.jsonl"
    _write(prev, ("p1", "old"))
    cur = tmp_path / "cur.jsonl"
    _write(cur, ("c1", "new"))
    published: list[int] = []
    monkeypatch.setattr(state_mod.jsonl_event_broadcaster, "publish",
                        lambda sid, event, pos=None: published.append(pos))
    tstate = jr.SessionTailState()
    monkeypatch.setattr(jr, "_latest_jsonl", lambda sid: prev)
    jr._tick_sid(SID, tstate, now_mono=0.0)
    monkeypatch.setattr(jr, "_latest_jsonl", lambda sid: cur)
    jr._tick_sid(SID, tstate, now_mono=1.0)  # 切り替えを見つける
    jr._tick_sid(SID, tstate, now_mono=2.0)  # 今の会話の行を流す
    assert history.ended(SID) == [(prev, 0)]
    assert published[-1] == prev.stat().st_size + cur.stat().st_size
