"""タブの記録の並び (= backend/jsonl/chain.py) と、 終わった会話の控えの起点 (= backend/jsonl/history.py)。

担保する事:
1. 画面を閉じている間に会話が入れ替わっても、 開いた時に前の会話の残り (= 締めの作業と入れ替えの発話) から
   今の会話まで繋がって流れる (= 流し直し / 履歴 GET / live の 3 経路とも同じ通しの位置)
2. 今の会話の記録が前の会話の offset より育っても、 今の会話の頭を飛ばさない
3. 起点は積んだ時に決まり、 古い記録が消えても動かない
4. 画面を長く閉じている間に直近の窓 (= 500 行) を超えて書かれても、 画面が描き終えた位置 (= since) まで
   欠けずに返す。 上限 (= 3000 行) を超える時は直近の上限までで、 届かなかった事を伝える
"""
import json

import backend.jsonl.routes as jr
import backend.routes.unified_stream as us
import backend._common.state as state_mod
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


def _numbered(path, count: int, prefix: str) -> None:
    """`<prefix>0` から `<prefix><count-1>` までの発話を 1 行ずつ書く。"""
    _write(path, *[(f"{prefix}{i}", f"{prefix}{i}") for i in range(count)])


def _pos_after(path, line_count: int) -> int:
    """path の先頭から line_count 行を読み終えた byte 位置 (= 通しの起点 0 の記録での行末の位置)。"""
    return sum(len(raw) + 1 for raw in path.read_bytes().split(b"\n")[:line_count])


def _long_tab(tmp_path, previous_count: int, current_count: int):
    """前の会話 (= p0〜) を終えて、 今の会話 (= c0〜) が走っているタブ。 返り値 (前, 今)。"""
    prev = tmp_path / "prev.jsonl"
    _numbered(prev, previous_count, "p")
    history.record_end(SID, "prev", str(prev))
    cur = tmp_path / "cur.jsonl"
    _numbered(cur, current_count, "c")
    return prev, cur


def _window(cur, since):
    return chain.read_window(chain.segments(SID, cur), since, 500, 3000)


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


# --- 画面が描き終えた位置まで遡る窓 -----------------------------------------

def test_the_window_reaches_back_to_since_past_the_recent_lines(tmp_path):
    """前の会話の後半と今の会話で 500 行を超えて書かれても、 since の直後から欠けずに返る。"""
    prev, cur = _long_tab(tmp_path, 800, 400)
    window = _window(cur, _pos_after(prev, 100))
    texts = _texts(window.lines)
    assert texts[0] == "p100" and texts[-1] == "c399"
    assert len(texts) == 700 + 400
    assert window.reached is True
    assert window.end == prev.stat().st_size + cur.stat().st_size


def test_the_window_reaches_back_to_since_inside_one_session(tmp_path):
    cur = tmp_path / "cur.jsonl"
    _numbered(cur, 1200, "c")
    window = _window(cur, _pos_after(cur, 100))
    assert _texts(window.lines)[0] == "c100" and len(window.lines) == 1100
    assert window.reached is True


def test_a_window_past_the_limit_keeps_the_latest_lines_and_says_it_did_not_reach(tmp_path):
    prev, cur = _long_tab(tmp_path, 2000, 2000)
    window = _window(cur, _pos_after(prev, 10))
    texts = _texts(window.lines)
    assert len(texts) == 3000
    assert texts[0] == "p1000" and texts[-1] == "c1999"
    assert window.reached is False


def test_the_limit_is_exact_for_reaching_since(tmp_path):
    cur = tmp_path / "cur.jsonl"
    _numbered(cur, 3500, "c")
    reached = _window(cur, _pos_after(cur, 500))      # since の後ろがちょうど 3000 行
    missed = _window(cur, _pos_after(cur, 499))       # since の後ろが 3001 行
    assert (len(reached.lines), reached.reached) == (3000, True)
    assert (len(missed.lines), missed.reached) == (3000, False)


def test_since_ahead_of_the_end_returns_the_recent_lines_as_reached(tmp_path):
    """画面の位置が記録の終わりより先を指していても、 抜けは無い (= 直近の窓を返して届いた扱い)。"""
    prev, cur = _long_tab(tmp_path, 300, 400)
    window = _window(cur, prev.stat().st_size + cur.stat().st_size + 10_000)
    assert len(window.lines) == 500
    assert _texts(window.lines)[-1] == "c399"
    assert window.reached is True


def test_without_since_the_window_is_the_recent_lines_and_is_not_measured(tmp_path):
    cur = tmp_path / "cur.jsonl"
    _numbered(cur, 1200, "c")
    window = _window(cur, None)
    assert len(window.lines) == 500 and _texts(window.lines)[0] == "c700"
    assert window.reached is False


def test_since_at_the_end_still_returns_the_recent_lines(tmp_path):
    """画面が追いついている時も、 作業中の行を取りこぼさないよう直近の窓を返す。"""
    cur = tmp_path / "cur.jsonl"
    _numbered(cur, 1200, "c")
    window = _window(cur, cur.stat().st_size)
    assert len(window.lines) == 500
    assert window.reached is True


def test_since_before_everything_returns_all_lines_as_reached(tmp_path):
    _prev, cur = _long_tab(tmp_path, 3, 3)
    window = _window(cur, 0)
    assert _texts(window.lines) == ["p0", "p1", "p2", "c0", "c1", "c2"]
    assert window.reached is True


def test_without_any_record_nothing_is_missing_when_since_is_given(isolated_state):
    assert chain.read_window([], 10, 500, 3000) == chain.Window([], 0, True)
    assert chain.read_window([], None, 500, 3000) == chain.Window([], 0, False)


# --- 3 経路 (= 流し直し / 履歴 GET / live) ---------------------------------

def test_stream_replay_carries_the_previous_session(isolated_state, tmp_path, monkeypatch):
    _prev, cur, seen = _rolled_over(tmp_path)
    monkeypatch.setattr("backend.jsonl.routes.jsonl_path_for_session", lambda s: cur)
    frames = us._replay_frames(SID, seen)
    texts = [f["ev"].get("text") for f in frames if f["ev"].get("type") == "user_message"]
    assert texts == ["please wrap up", "wrapping up", "rollover start", "next session"]


def _replayed(frames) -> list[str]:
    return [f["ev"]["text"] for f in frames if f["ev"].get("type") == "user_message"]


def _marks(frames) -> list[dict]:
    return [f for f in frames if f["ev"].get("type") == "history_refetch"]


def test_stream_replay_covers_what_was_written_beyond_the_recent_lines(isolated_state, tmp_path, monkeypatch):
    prev, cur = _long_tab(tmp_path, 800, 400)
    monkeypatch.setattr("backend.jsonl.routes.jsonl_path_for_session", lambda s: cur)
    frames = us._replay_frames(SID, _pos_after(prev, 100))
    texts = _replayed(frames)
    assert texts[0] == "p100" and texts[-1] == "c399" and len(texts) == 1100
    assert _marks(frames) == []


def test_stream_replay_past_the_limit_opens_with_one_refetch_mark(isolated_state, tmp_path, monkeypatch):
    prev, cur = _long_tab(tmp_path, 2000, 2000)
    monkeypatch.setattr("backend.jsonl.routes.jsonl_path_for_session", lambda s: cur)
    frames = us._replay_frames(SID, _pos_after(prev, 10))
    assert frames[0]["ev"] == {"type": "history_refetch", "sid": SID, "corr_id": frames[0]["ev"]["corr_id"]}
    assert frames[0]["ch"] == "jsonl" and frames[0]["pos"] is None
    assert len(_marks(frames)) == 1
    texts = _replayed(frames)
    assert len(texts) == 3000 and texts[0] == "p1000" and texts[-1] == "c1999"


def test_stream_replay_without_an_offset_carries_no_mark(isolated_state, tmp_path, monkeypatch):
    _prev, cur = _long_tab(tmp_path, 800, 400)
    monkeypatch.setattr("backend.jsonl.routes.jsonl_path_for_session", lambda s: cur)
    frames = us._replay_frames(SID, None)
    assert len(_replayed(frames)) == 500
    assert _marks(frames) == []


def test_stream_replay_with_an_offset_ahead_of_the_end_replays_the_recent_lines(isolated_state, tmp_path, monkeypatch):
    prev, cur = _long_tab(tmp_path, 300, 400)
    monkeypatch.setattr("backend.jsonl.routes.jsonl_path_for_session", lambda s: cur)
    frames = us._replay_frames(SID, prev.stat().st_size + cur.stat().st_size + 10_000)
    assert len(_replayed(frames)) == 500
    assert _marks(frames) == []


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
