"""jsonl_routes.py の tail 読み取りプリミティブの unit test。

`_read_complete_lines` / `_read_tail` / `_initial_offset` は SSE 配信と push 監視の
両方が依存する subtle なファイル tail ロジック (= 部分行の持ち越し、 truncate 検知、
初回 replay の行絞り)。 ファイルだけで完結する純粋関数なので fixture は tmp_path のみ。
"""
import backend.jsonl.routes as jr


# ---------------------------------------------------------------------------
# _read_complete_lines: 改行で終わる完全行だけ返し、 末尾の部分行は次回に持ち越す
# ---------------------------------------------------------------------------

def test_read_complete_lines_full(tmp_path):
    p = tmp_path / "a.jsonl"
    p.write_bytes(b"a\nb\n")
    assert jr._read_complete_lines(p, 0) == (["a", "b"], 4)


def test_read_complete_lines_partial_tail_held_back(tmp_path):
    # 末尾 "b" は \n が無い = 書き込み途中。 pos は最後の完全行直後 (= 2) までしか進めない
    p = tmp_path / "a.jsonl"
    p.write_bytes(b"a\nb")
    assert jr._read_complete_lines(p, 0) == (["a"], 2)


def test_read_complete_lines_no_new(tmp_path):
    p = tmp_path / "a.jsonl"
    p.write_bytes(b"a\n")
    assert jr._read_complete_lines(p, 2) == ([], 2)


def test_read_complete_lines_missing_file(tmp_path):
    assert jr._read_complete_lines(tmp_path / "nope.jsonl", 0) == ([], 0)


# ---------------------------------------------------------------------------
# _read_tail: (lines, new_pos, status) — ok / nochange / truncated / error
# ---------------------------------------------------------------------------

def test_read_tail_ok(tmp_path):
    p = tmp_path / "a.jsonl"
    p.write_bytes(b"a\nb\n")
    # monitor 経路は per-line byte pos 付き (= SSE id 前進の土台、 2026-07-14)
    assert jr._read_tail_with_pos(p, 0) == ([("a", 2), ("b", 4)], 4, "ok")


def test_read_tail_nochange(tmp_path):
    p = tmp_path / "a.jsonl"
    p.write_bytes(b"a\nb\n")
    assert jr._read_tail_with_pos(p, 4) == ([], 4, "nochange")


def test_read_tail_partial(tmp_path):
    p = tmp_path / "a.jsonl"
    p.write_bytes(b"a\nb")  # b は未確定
    assert jr._read_tail_with_pos(p, 0) == ([("a", 2)], 2, "ok")


def test_read_tail_truncated_resyncs_to_size(tmp_path):
    # pos がファイルサイズを超える (= rotate / truncate) → new_pos = 現 size、 status=truncated
    p = tmp_path / "a.jsonl"
    p.write_bytes(b"a\n")
    assert jr._read_tail_with_pos(p, 999) == ([], 2, "truncated")


def test_read_tail_error_on_missing(tmp_path):
    assert jr._read_tail_with_pos(tmp_path / "nope.jsonl", 5) == ([], 5, "error")


# ---------------------------------------------------------------------------
# _initial_offset: 直近 INITIAL_REPLAY_LINES 行に絞る (= 末尾 seek、 全読みしない)
# ---------------------------------------------------------------------------

def test_initial_offset_small_file_returns_zero(tmp_path):
    # 改行が INITIAL_REPLAY_LINES 以下 → 全件 replay (= 0)
    p = tmp_path / "a.jsonl"
    p.write_bytes(b"".join(f"L{i}\n".encode() for i in range(10)))
    assert jr._initial_offset(p) == 0


def test_initial_offset_boundary_equals_n(tmp_path):
    # ちょうど N 行 = 全件 (= count <= N → 0)、 旧実装と同じ境界
    p = tmp_path / "a.jsonl"
    p.write_bytes(b"".join(f"L{i}\n".encode() for i in range(jr.INITIAL_REPLAY_LINES)))
    assert jr._initial_offset(p) == 0


def test_initial_offset_large_file_keeps_last_n(tmp_path):
    n = jr.INITIAL_REPLAY_LINES
    total = n + 100
    p = tmp_path / "a.jsonl"
    p.write_bytes(b"".join(f"L{i}\n".encode() for i in range(total)))
    off = jr._initial_offset(p)
    assert off > 0
    # 「末尾から N 個目の改行の直後」 を返す = 末尾 N-1 行ぶん。 旧実装 (全読み + rfind) と
    # 同じ off-by-one を踏襲しており、 初回 replay の行数キャップとしては実害なし。
    lines, _ = jr._read_complete_lines(p, off)
    assert len(lines) == n - 1
    assert lines[0] == f"L{total - (n - 1)}"
    assert lines[-1] == f"L{total - 1}"


def test_initial_offset_empty_file(tmp_path):
    p = tmp_path / "a.jsonl"
    p.write_bytes(b"")
    assert jr._initial_offset(p) == 0


# ---------------------------------------------------------------------------
# _latest_subagent_tool / _refresh_subagent_status: Task 実行中のサブツール名抽出 (= 0-6)
# subagent transcript は <jsonl>/<sid>/subagents/agent-*.jsonl に別ファイルで書かれる
# ---------------------------------------------------------------------------
import json
import os


def _write_agent_file(subdir, name, tools, mtime=None):
    """subagents/<name>.jsonl に assistant tool_use 行を時系列で書く helper。"""
    subdir.mkdir(parents=True, exist_ok=True)
    p = subdir / name
    lines = []
    for t in tools:
        lines.append(json.dumps({
            "type": "assistant",
            "isSidechain": True,
            "message": {"role": "assistant", "content": [{"type": "tool_use", "name": t}]},
        }))
    p.write_text("\n".join(lines) + "\n")
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


# --- busy 判定 (案B: 全session 状態の backend 権威ソース) ---

def _asst(stop_reason):
    return {"type": "assistant", "message": {"role": "assistant", "stop_reason": stop_reason,
                                             "content": [{"type": "text", "text": "x"}]}}

def _user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def test_is_user_prompt_true_for_real_text():
    assert jr._is_user_prompt(_user("hello")) is True
    assert jr._is_user_prompt({"type": "user", "message": {"content": [{"type": "text", "text": "hi"}]}}) is True


def test_is_user_prompt_false_for_harness_xml():
    """claude TUI が user 行として書く harness XML (slash command / shell stdout 等) を
    ユーザ発話扱いしない (= ターミナルで /clear や ls 等を打っただけで busy が立つ事象を防ぐ)。"""
    # 文字列 content (slash command)
    assert jr._is_user_prompt(_user("<command-name>/clear</command-name>")) is False
    assert jr._is_user_prompt(_user("<command-message>clear</command-message>")) is False
    assert jr._is_user_prompt(_user("<command-args>sonnet</command-args>")) is False
    assert jr._is_user_prompt(_user("<local-command-stdout>foo</local-command-stdout>")) is False
    assert jr._is_user_prompt(_user("<local-command-stderr>err</local-command-stderr>")) is False
    # list content (text block で同じ XML)
    line = {"type": "user", "message": {"content": [{"type": "text", "text": "<command-name>/clear</command-name>"}]}}
    assert jr._is_user_prompt(line) is False


def test_is_user_prompt_false_for_interrupt_marker():
    """`[Request interrupted by user]` は claude が中断完了 marker として user 行に書く文字列で、
    新プロンプトではない。 ユーザ発話扱いすると busy=True が再点火し、 終端 stop_reason 行が
    来ないため停止ボタンが送信ボタンに戻らない (2026-06-04 真因)。"""
    # 文字列 content
    assert jr._is_user_prompt(_user("[Request interrupted by user]")) is False
    # list content (claude が実際に書く形式)
    line = {"type": "user", "message": {"content": [{"type": "text", "text": "[Request interrupted by user]"}]}}
    assert jr._is_user_prompt(line) is False
    # 大小無視 + 前後空白許容
    assert jr._is_user_prompt(_user("  [REQUEST INTERRUPTED BY USER]  ")) is False
    # interrupt marker と通常 text が混ざった list は通常 text 側で True (= 安全側に倒さない: claude が
    # 実際にこの形で書くことは無いが、 通常発話が誤って弾かれないことの担保)
    line2 = {"type": "user", "message": {"content": [
        {"type": "text", "text": "[Request interrupted by user]"},
        {"type": "text", "text": "hello"},
    ]}}
    assert jr._is_user_prompt(line2) is True


def test_is_user_prompt_true_for_task_notification():
    """background task の完了通知は表示こそ system カードに変えるが、 busy 判定では
    ユーザ発話扱いのまま残す: 完了を受けて claude が proactive turn を走らせるため、
    その間 busy=True で停止可能なのが正しい挙動 (= 停止ボタンを消さない)。"""
    text = (
        "<task-notification>\n<status>completed</status>\n"
        '<summary>Background command "x" completed (exit code 0)</summary>\n'
        "</task-notification>"
    )
    assert jr._is_user_prompt(_user(text)) is True


def test_is_user_prompt_false_for_tool_result_and_meta():
    # tool_result の user 行 (content が list で text 無し) は除外
    assert jr._is_user_prompt({"type": "user", "message": {"content": [{"type": "tool_result", "content": "r"}]}}) is False
    assert jr._is_user_prompt({"type": "user", "isMeta": True, "message": {"content": "x"}}) is False
    assert jr._is_user_prompt({"type": "user", "isSidechain": True, "message": {"content": "x"}}) is False
    assert jr._is_user_prompt(_asst("end_turn")) is False


def test_update_busy_transitions(isolated_state):
    state = isolated_state
    import backend.state as state_mod
    sid = "ses_busy"
    state.stream_states[sid] = state_mod.StreamState(agent_id="a")
    # broadcaster に 1 接続ぶん購読して notify を検出する (= 旧 単一 Event の代替)
    ev = state_mod.sessions_overview.subscribe()
    ev.clear()

    # 素ユーザ発話 → busy=True + event set
    jr._update_busy(sid, _user("go"))
    assert state.stream_states[sid].busy is True
    assert ev.is_set() is True
    ev.clear()

    # tool_use 継続 → busy=True 維持 (変化なし → event は set されない)
    jr._update_busy(sid, _asst("tool_use"))
    assert state.stream_states[sid].busy is True
    assert ev.is_set() is False

    # end_turn → busy=False + event set
    jr._update_busy(sid, _asst("end_turn"))
    assert state.stream_states[sid].busy is False
    assert ev.is_set() is True


def test_overview_broadcaster_notifies_all_subscribers():
    # 複数接続 (= 複数デバイス) を模した複数 Event が 1 回の notify で全部 set される。
    # 旧 単一 Event 共有では 1 接続の clear() が他を奪う競合があった (= その回帰防止)。
    import backend.state as state_mod
    b = state_mod.OverviewBroadcaster()
    a = b.subscribe()
    c = b.subscribe()
    assert a.is_set() is False and c.is_set() is False
    b.notify()
    assert a.is_set() is True and c.is_set() is True
    # 片方が clear しても他方は影響を受けない (= 取りこぼし解消の核)
    a.clear()
    assert c.is_set() is True
    b.unsubscribe(a)
    b.notify()
    assert c.is_set() is True  # まだ購読中


def _write_jsonl(path, lines):
    import json as _json
    with open(path, "w") as fh:
        for ln in lines:
            fh.write(_json.dumps(ln) + "\n")


def test_busy_after_idle_settles_missing_terminal_marker(tmp_path):
    # 末尾が assistant 応答 (content あり) なのに stop_reason 欠落 → idle 判定では settled=False。
    # (= claude-code #22566 / monitor 取りこぼしのバックストップ)
    from backend.jsonl.session_status import busy_after_idle, compute_busy_from_tail
    p = tmp_path / "s.jsonl"
    _write_jsonl(p, [
        {"type": "user", "message": {"content": "go"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "done"}]}},  # no stop_reason
    ])
    # 通常判定は「partial かも」 で古い user 行まで遡って busy=True にしてしまう
    assert compute_busy_from_tail(p) is True
    # idle 判定は marker 欠落を settled とみなす
    assert busy_after_idle(p) is False


def test_busy_after_idle_keeps_tool_use_busy(tmp_path):
    # 末尾が tool_use (= 長時間ツール実行中) は idle でも busy 維持 (誤って送信ボタンに戻さない)
    from backend.jsonl.session_status import busy_after_idle
    p = tmp_path / "s.jsonl"
    _write_jsonl(p, [
        {"type": "user", "message": {"content": "go"}},
        {"type": "assistant", "message": {"stop_reason": "tool_use",
                                          "content": [{"type": "tool_use", "name": "Bash", "id": "t", "input": {}}]}},
    ])
    assert busy_after_idle(p) is True


def test_busy_after_idle_terminal_is_false(tmp_path):
    from backend.jsonl.session_status import busy_after_idle
    p = tmp_path / "s.jsonl"
    _write_jsonl(p, [
        {"type": "user", "message": {"content": "go"}},
        {"type": "assistant", "message": {"stop_reason": "end_turn", "content": [{"type": "text", "text": "ok"}]}},
    ])
    assert busy_after_idle(p) is False


def test_update_busy_refusal_completes(isolated_state):
    state = isolated_state
    import backend.state as state_mod
    sid = "ses_ref"
    state.stream_states[sid] = state_mod.StreamState(agent_id="a", busy=True)
    jr._update_busy(sid, _asst("refusal"))
    assert state.stream_states[sid].busy is False


def test_update_busy_unknown_session_noop():
    # 登録されてない sid は黙って無視 (例外を投げない)
    jr._update_busy("__no_such_sid__", _user("x"))


def test_compute_busy_from_tail(tmp_path):
    p = tmp_path / "s.jsonl"
    # 末尾が tool_use → busy=True
    p.write_text("\n".join(json.dumps(x) for x in [_user("go"), _asst("tool_use")]) + "\n")
    assert jr._compute_busy_from_tail(p) is True
    # 末尾が end_turn → busy=False
    p.write_text("\n".join(json.dumps(x) for x in [_user("go"), _asst("tool_use"), _asst("end_turn")]) + "\n")
    assert jr._compute_busy_from_tail(p) is False
    # 素ユーザ発話だけ (assistant 未着) → busy=True
    p.write_text(json.dumps(_user("go")) + "\n")
    assert jr._compute_busy_from_tail(p) is True


def test_compute_busy_from_tail_missing_file(tmp_path):
    assert jr._compute_busy_from_tail(tmp_path / "nope.jsonl") is False


def test_latest_subagent_tool_returns_last_tool(tmp_path):
    jsonl = tmp_path / "ses1.jsonl"
    sub = tmp_path / "ses1" / "subagents"
    _write_agent_file(sub, "agent-a.jsonl", ["Read", "Write", "Bash"], mtime=1000)
    assert jr._latest_subagent_tool(jsonl, since=0) == "Bash"


def test_latest_subagent_tool_picks_newest_file(tmp_path):
    jsonl = tmp_path / "ses1.jsonl"
    sub = tmp_path / "ses1" / "subagents"
    _write_agent_file(sub, "agent-old.jsonl", ["Read"], mtime=1000)
    _write_agent_file(sub, "agent-new.jsonl", ["Grep"], mtime=2000)
    assert jr._latest_subagent_tool(jsonl, since=0) == "Grep"


def test_latest_subagent_tool_filters_by_since(tmp_path):
    # since (= 現 Task の started_at) より前に書かれた古い agent ファイルは無視する
    jsonl = tmp_path / "ses1.jsonl"
    sub = tmp_path / "ses1" / "subagents"
    _write_agent_file(sub, "agent-stale.jsonl", ["Read"], mtime=500)
    assert jr._latest_subagent_tool(jsonl, since=1000) is None


def test_latest_subagent_tool_no_dir(tmp_path):
    assert jr._latest_subagent_tool(tmp_path / "nope.jsonl", since=0) is None


def test_refresh_subagent_sets_and_clears(tmp_path, isolated_state):
    state = isolated_state
    sid = "ses_test"
    state.agent_status[sid] = {"current_tool": {"name": "Task", "started_at": 0}, "subagent": None}
    jsonl = tmp_path / "ses_test.jsonl"
    sub = tmp_path / "ses_test" / "subagents"
    _write_agent_file(sub, "agent-a.jsonl", ["Read"], mtime=1000)
    # Task 実行中 → last_tool が立つ
    assert jr._refresh_subagent_status(sid, jsonl) is True
    assert state.agent_status[sid]["subagent"] == {"last_tool": "Read"}
    # 変化なし → False
    assert jr._refresh_subagent_status(sid, jsonl) is False
    # Task 終了 (current_tool が落ちる) → subagent も落ちる
    state.agent_status[sid]["current_tool"] = None
    assert jr._refresh_subagent_status(sid, jsonl) is True
    assert state.agent_status[sid]["subagent"] is None


# ---------------------------------------------------------------------------
# GET /jsonl/history/{sid}: 権威スナップショットを 1 発で返す (= client=射影の状態取得)
# ---------------------------------------------------------------------------
def _hist_client(monkeypatch, jsonl_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    monkeypatch.setattr(jr, "_latest_jsonl", lambda sid: jsonl_path)
    app = FastAPI()
    app.include_router(jr.router)
    return TestClient(app)


def test_history_returns_events_and_end_pos(tmp_path, monkeypatch):
    import json
    p = tmp_path / "c.jsonl"
    lines = [
        {"type": "user", "message": {"role": "user", "content": "hi"}, "uuid": "u1"},
        {"type": "assistant", "message": {"role": "assistant",
         "content": [{"type": "text", "text": "hello"}], "stop_reason": "end_turn"}, "uuid": "a1"},
    ]
    p.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    client = _hist_client(monkeypatch, p)
    r = client.get("/jsonl/history/ses_x")
    assert r.status_code == 200
    data = r.json()
    assert data["pos"] == p.stat().st_size  # 読み終えた byte 位置 = ファイル末尾
    assert len(data["events"]) >= 2         # user + assistant が event 化される
    assert all("sid" in e for e in data["events"])  # _inject_envelope で sid が乗る


def test_history_from_offset_returns_only_the_tail(tmp_path, monkeypatch):
    import json
    p = tmp_path / "c.jsonl"
    first = json.dumps({"type": "user", "message": {"role": "user", "content": "one"}, "uuid": "u1"}) + "\n"
    p.write_text(first, encoding="utf-8")
    mid = p.stat().st_size
    p.write_text(first + json.dumps(
        {"type": "user", "message": {"role": "user", "content": "two"}, "uuid": "u2"}) + "\n", encoding="utf-8")
    client = _hist_client(monkeypatch, p)
    # from=mid → 2 件目以降だけ (= 描画済み位置からの差分)
    r = client.get(f"/jsonl/history/ses_x?from={mid}")
    data = r.json()
    assert data["pos"] == p.stat().st_size
    texts = [e.get("text") for e in data["events"] if e.get("type") == "user_message"]
    assert "two" in texts and "one" not in texts


def test_history_no_jsonl_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(jr, "_latest_jsonl", lambda sid: None)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI(); app.include_router(jr.router)
    r = TestClient(app).get("/jsonl/history/ses_x")
    assert r.status_code == 200
    assert r.json() == {"events": [], "pos": 0}


# --- 履歴 GET の tool_result 切り詰め (= 2026-07-27 転送量削減) ---

def test_shrink_tool_results_truncates_long_string_and_keeps_original_length():
    from backend.jsonl.routes import TOOL_RESULT_PREVIEW_CHARS, _shrink_tool_results
    body = "x" * (TOOL_RESULT_PREVIEW_CHARS * 10)
    ev = {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": body},
    ]}}
    _shrink_tool_results(ev)
    block = ev["message"]["content"][0]
    assert len(block["content"]) == TOOL_RESULT_PREVIEW_CHARS
    assert block["full_chars"] == len(body)          # UI の文字数表示用に元の長さを残す
    assert block["content"] == body[:TOOL_RESULT_PREVIEW_CHARS]  # 冒頭は完全一致


def test_shrink_tool_results_leaves_short_content_untouched():
    from backend.jsonl.routes import _shrink_tool_results
    ev = {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": "短い出力"},
    ]}}
    _shrink_tool_results(ev)
    block = ev["message"]["content"][0]
    assert block["content"] == "短い出力"
    assert "full_chars" not in block                  # 切り詰めてない印


def test_shrink_tool_results_handles_block_list_form():
    from backend.jsonl.routes import TOOL_RESULT_PREVIEW_CHARS, _shrink_tool_results
    parts = [{"type": "text", "text": "a" * 1500}, {"type": "text", "text": "b" * 1500}]
    ev = {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": parts},
    ]}}
    _shrink_tool_results(ev)
    block = ev["message"]["content"][0]
    total = sum(len(p["text"]) for p in block["content"] if "text" in p)
    assert total == TOOL_RESULT_PREVIEW_CHARS
    assert block["full_chars"] == 3000


def test_shrink_tool_results_never_touches_assistant_or_user_message():
    """切り詰めは type=user の tool_result 限定。 発話や応答本文は 1 文字も変えない。"""
    from backend.jsonl.routes import _shrink_tool_results
    long_text = "あ" * 50000
    for ev in (
        {"type": "assistant", "message": {"content": [{"type": "text", "text": long_text}]}},
        {"type": "user_message", "text": long_text},
    ):
        before = json.dumps(ev, ensure_ascii=False)
        _shrink_tool_results(ev)
        assert json.dumps(ev, ensure_ascii=False) == before


def test_shrink_tool_results_drops_image_payload_but_keeps_placeholder():
    """tool_result 内の画像は base64 を落とす (= UI は「画像」 プレースホルダしか出さない)。"""
    from backend.jsonl.routes import _shrink_tool_results
    ev = {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "A" * 400_000}},
        ]},
    ]}}
    _shrink_tool_results(ev)
    block = ev["message"]["content"][0]
    assert block["content"] == [{"type": "image"}]     # type は残す = 表示は不変
    assert "source" not in block["content"][0]         # 本体は落ちている
    assert len(json.dumps(ev)) < 500                   # 400KB → 数百 byte


def test_shrink_tool_results_keeps_text_when_image_is_stripped():
    """画像と短いテキストが混在しても、 テキストは 1 文字も失わない。"""
    from backend.jsonl.routes import _shrink_tool_results
    ev = {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": [
            {"type": "text", "text": "スクショを撮りました"},
            {"type": "image", "source": {"data": "B" * 100_000}},
        ]},
    ]}}
    _shrink_tool_results(ev)
    parts = ev["message"]["content"][0]["content"]
    assert parts[0] == {"type": "text", "text": "スクショを撮りました"}
    assert parts[1] == {"type": "image"}
