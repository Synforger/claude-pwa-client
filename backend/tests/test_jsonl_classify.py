"""backend/jsonl/session_status.classify_jsonl_line の unit test (= backend-F-04)。

旧版は update_busy / compute_busy_from_tail / busy_after_idle が 1 行 → 状態の分岐を
それぞれ自前で書いていた (= stop_reason 文字列比較が 3 箇所、 INTERRUPT marker の扱いが
微妙にズレ)。 classify_jsonl_line に集約したことで、 ここを厚く検査すれば 3 関数すべての
busy 遷移が一貫することを保証できる。
"""
from backend.jsonl.session_status import LineKind, classify_jsonl_line


def _asst(stop_reason=None, content=None):
    msg = {"role": "assistant", "content": content or [{"type": "text", "text": "x"}]}
    if stop_reason is not None:
        msg["stop_reason"] = stop_reason
    return {"type": "assistant", "message": msg}


def _user_str(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def _user_list(*blocks):
    return {"type": "user", "message": {"role": "user", "content": list(blocks)}}


# --- IN_PROGRESS / END / OTHER (= assistant) -----------------------------

def test_classify_assistant_tool_use_is_in_progress():
    assert classify_jsonl_line(_asst("tool_use")) is LineKind.IN_PROGRESS


def test_classify_assistant_end_turn_is_end():
    assert classify_jsonl_line(_asst("end_turn")) is LineKind.END


def test_classify_assistant_other_stop_reasons_are_end():
    for sr in ("max_tokens", "refusal", "pause_turn", "model_context_window_exceeded"):
        assert classify_jsonl_line(_asst(sr)) is LineKind.END


def test_classify_assistant_no_stop_reason_is_other():
    # 末尾 partial 行 (= claude-code #22566 で観測される marker 欠落) は OTHER。
    # busy_after_idle はこれを idle 時 settled として扱い、 通常判定は古い行へ遡る。
    assert classify_jsonl_line(_asst(None)) is LineKind.OTHER


# --- START / INTERRUPT (= user) ------------------------------------------

def test_classify_user_plain_prompt_is_start():
    assert classify_jsonl_line(_user_str("hello")) is LineKind.START
    assert classify_jsonl_line(_user_list({"type": "text", "text": "hi"})) is LineKind.START


def test_classify_interrupt_marker_string_is_interrupt():
    assert classify_jsonl_line(_user_str("[Request interrupted by user]")) is LineKind.INTERRUPT
    assert classify_jsonl_line(_user_str("  [REQUEST INTERRUPTED BY USER]  ")) is LineKind.INTERRUPT


def test_classify_interrupt_marker_list_is_interrupt():
    line = _user_list({"type": "text", "text": "[Request interrupted by user]"})
    assert classify_jsonl_line(line) is LineKind.INTERRUPT


def test_classify_mixed_interrupt_and_text_is_start():
    # INTERRUPT marker + 通常 text の list は通常 text 側で START (= 安全側に倒さない)
    line = _user_list(
        {"type": "text", "text": "[Request interrupted by user]"},
        {"type": "text", "text": "hello"},
    )
    assert classify_jsonl_line(line) is LineKind.START


def test_classify_harness_xml_is_other():
    # slash command XML はユーザ発話扱いしない (= predicates.is_user_prompt で弾く)
    assert classify_jsonl_line(_user_str("<command-name>/clear</command-name>")) is LineKind.OTHER


def test_classify_user_tool_result_is_other():
    line = {"type": "user", "message": {"content": [{"type": "tool_result", "content": "r"}]}}
    assert classify_jsonl_line(line) is LineKind.OTHER


def test_classify_sidechain_meta_is_other():
    assert classify_jsonl_line({"type": "user", "isSidechain": True, "message": {"content": "x"}}) is LineKind.OTHER
    assert classify_jsonl_line({"type": "user", "isMeta": True, "message": {"content": "x"}}) is LineKind.OTHER


def test_classify_non_user_non_assistant_is_other():
    for t in ("mode", "permission-mode", "attachment", "pr-link", "system"):
        assert classify_jsonl_line({"type": t}) is LineKind.OTHER


def test_classify_non_dict_is_other():
    assert classify_jsonl_line(None) is LineKind.OTHER  # type: ignore[arg-type]
    assert classify_jsonl_line("string") is LineKind.OTHER  # type: ignore[arg-type]


# --- update_busy が classify 経由になっていることの動的回帰 (INTERRUPT 経路) ---

def test_update_busy_interrupt_marker_clears_busy(isolated_state):
    """[Request interrupted by user] marker で busy=False に落ちる。 旧 update_busy は
    is_user_prompt 経由で INTERRUPT を弾いていたため busy 据置 (= 結果 OK だが意図が
    曖昧)。 classify_jsonl_line 経由で明示的に INTERRUPT 分岐に流すことを担保する。"""
    import backend.state as state_mod
    from backend.jsonl.session_status import update_busy
    state = isolated_state
    sid = "ses_int"
    state.stream_states[sid] = state_mod.StreamState(agent_id="a", busy=True)
    update_busy(sid, _user_str("[Request interrupted by user]"))
    assert state.stream_states[sid].busy is False


# --- queue-aware busy (= turn 実行中送信で積んだ queue が残る間は END でも busy 維持) ---

def test_update_busy_queued_send_keeps_busy_on_end(isolated_state):
    """queue に未処理送信が残る間は turn 完了 (END) を見ても busy=True を維持する
    (= 「1 個目の turn は終わったが queue の 2 個目をこれから処理する」 無言時間を推論中で繋ぐ)。"""
    import backend.state as state_mod
    from backend.jsonl.session_status import update_busy
    state = isolated_state
    sid = "ses_q1"
    state.stream_states[sid] = state_mod.StreamState(agent_id="a", busy=True, queued_sends=1)
    update_busy(sid, _asst("end_turn"))
    assert state.stream_states[sid].busy is True
    assert state.stream_states[sid].queued_sends == 1


def test_update_busy_start_consumes_queued_send(isolated_state):
    """queue message が JSONL に素ユーザ発話 (START) として現れたら queued_sends を 1 減らす。
    最後の 1 個を消化した後の END では busy=False に戻る。"""
    import backend.state as state_mod
    from backend.jsonl.session_status import update_busy
    state = isolated_state
    sid = "ses_q2"
    state.stream_states[sid] = state_mod.StreamState(agent_id="a", busy=True, queued_sends=1)
    update_busy(sid, _user_str("second message"))  # START → queue 1 個消化
    assert state.stream_states[sid].queued_sends == 0
    assert state.stream_states[sid].busy is True     # turn 進行中
    update_busy(sid, _asst("end_turn"))              # queue 空 → END で解除
    assert state.stream_states[sid].busy is False


def test_update_busy_interrupt_clears_queue(isolated_state):
    """中断で queue の後続送信も破棄され busy=False に落ちる (= 張り付き防止)。"""
    import backend.state as state_mod
    from backend.jsonl.session_status import update_busy
    state = isolated_state
    sid = "ses_q3"
    state.stream_states[sid] = state_mod.StreamState(agent_id="a", busy=True, queued_sends=2)
    update_busy(sid, _user_str("[Request interrupted by user]"))
    assert state.stream_states[sid].queued_sends == 0
    assert state.stream_states[sid].busy is False


def test_update_busy_user_stopped_clears_queue(isolated_state):
    """Stop 押下 (user_stopped) は queue が残っていても busy=False を強制 + queue クリア。"""
    import backend.state as state_mod
    from backend.jsonl.session_status import update_busy
    state = isolated_state
    sid = "ses_q4"
    state.stream_states[sid] = state_mod.StreamState(
        agent_id="a", busy=True, queued_sends=1, user_stopped=True
    )
    update_busy(sid, _asst("tool_use"))  # 何を見ても user_stopped で False
    assert state.stream_states[sid].busy is False
    assert state.stream_states[sid].queued_sends == 0


# --- queue counting: slash command は queue に数えない (= 2026-07-09 「/command 後の推論中残り」) ---

def test_note_queue_skips_slash_command(isolated_state):
    """slash command (= is_slash) は turn 中送信でも queue に数えない (= START で減らず
    busy 永久張り付きになる主因を断つ)。 素プロンプトは従来通り queue に積む。"""
    import backend.state as state_mod
    from backend.terminal.routes import _note_queue_on_unconfirmed
    state = isolated_state
    sid = "ses_slash"
    state.stream_states[sid] = state_mod.StreamState(agent_id="a", busy=True)
    # slash command は confirmed:False でも queue に積まない
    _note_queue_on_unconfirmed(sid, was_busy=True, is_slash=True, result={"confirmed": False})
    assert state.stream_states[sid].queued_sends == 0
    # 素プロンプトは従来通り queue に積む (= 処理中は推論中を維持し続ける)
    _note_queue_on_unconfirmed(sid, was_busy=True, is_slash=False, result={"confirmed": False})
    assert state.stream_states[sid].queued_sends == 1


def test_note_queue_skips_when_not_busy_or_confirmed(isolated_state):
    """was_busy=False (= picker 等) / confirmed:True は queue でないので数えない。"""
    import backend.state as state_mod
    from backend.terminal.routes import _note_queue_on_unconfirmed
    state = isolated_state
    sid = "ses_nq"
    state.stream_states[sid] = state_mod.StreamState(agent_id="a", busy=False)
    _note_queue_on_unconfirmed(sid, was_busy=False, is_slash=False, result={"confirmed": False})
    _note_queue_on_unconfirmed(sid, was_busy=True, is_slash=False, result={"confirmed": True})
    assert state.stream_states[sid].queued_sends == 0
