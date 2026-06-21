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
