"""backend/jsonl/predicates.py の unit test (= backend-F-05)。

session_status.is_user_prompt と confirm.py._is_plain_user_prompt の判定ズレを根絶する
ための共通 predicate 集約。 既存 test (test_jsonl_routes.py 内 is_user_prompt 系) と
同じ semantics を保つことを確認しつつ、 集約 module 側でも単体カバレッジを付ける。
"""
from backend.jsonl import predicates as p


def _user_str(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def _user_list(*blocks):
    return {"type": "user", "message": {"role": "user", "content": list(blocks)}}


def _text(t):
    return {"type": "text", "text": t}


# --- is_user_prompt ------------------------------------------------------

def test_is_user_prompt_plain_string():
    assert p.is_user_prompt(_user_str("hello")) is True


def test_is_user_prompt_plain_text_block():
    assert p.is_user_prompt(_user_list(_text("hi"))) is True


def test_is_user_prompt_empty_rejected():
    assert p.is_user_prompt(_user_str("")) is False
    assert p.is_user_prompt(_user_str("   ")) is False
    assert p.is_user_prompt(_user_list(_text(""))) is False


def test_is_user_prompt_harness_xml_rejected():
    # slash command の XML 内部表現はユーザ発話扱いしない
    assert p.is_user_prompt(_user_str("<command-name>/clear</command-name>")) is False
    assert p.is_user_prompt(_user_list(_text("<local-command-stdout>x</local-command-stdout>"))) is False


def test_is_user_prompt_interrupt_marker_rejected():
    # `[Request interrupted by user]` は busy 永続化の元凶 (2026-06-04 真因)
    assert p.is_user_prompt(_user_str("[Request interrupted by user]")) is False
    assert p.is_user_prompt(_user_str("  [REQUEST INTERRUPTED BY USER]  ")) is False
    assert p.is_user_prompt(_user_list(_text("[Request interrupted by user]"))) is False


def test_is_user_prompt_mixed_blocks_uses_plain_side():
    # interrupt marker + 通常 text の list は通常 text 側で True (= 安全側に倒さない)
    line = _user_list(_text("[Request interrupted by user]"), _text("hello"))
    assert p.is_user_prompt(line) is True


def test_is_user_prompt_tool_result_rejected():
    line = {"type": "user", "message": {"content": [{"type": "tool_result", "content": "r"}]}}
    assert p.is_user_prompt(line) is False


def test_is_user_prompt_sidechain_meta_rejected():
    assert p.is_user_prompt({"type": "user", "isSidechain": True, "message": {"content": "x"}}) is False
    assert p.is_user_prompt({"type": "user", "isMeta": True, "message": {"content": "x"}}) is False


def test_is_user_prompt_non_user_type_rejected():
    assert p.is_user_prompt({"type": "assistant", "message": {"content": "x"}}) is False


# --- is_sidechain / is_meta ----------------------------------------------

def test_is_sidechain_meta_basic():
    assert p.is_sidechain({"isSidechain": True}) is True
    assert p.is_sidechain({}) is False
    assert p.is_meta({"isMeta": True}) is True
    assert p.is_meta({}) is False


# --- is_harness_xml_text -------------------------------------------------

def test_is_harness_xml_text():
    assert p.is_harness_xml_text("<command-name>foo</command-name>") is True
    assert p.is_harness_xml_text("<local-command-stdout>x</local-command-stdout>") is True
    assert p.is_harness_xml_text("[Request interrupted by user]") is True
    assert p.is_harness_xml_text("hello") is False
    assert p.is_harness_xml_text("") is False
    assert p.is_harness_xml_text("   ") is False
    # 非 string は False
    assert p.is_harness_xml_text(None) is False  # type: ignore[arg-type]


# --- session_status の re-export 後方互換 --------------------------------

def test_session_status_reexports_is_user_prompt():
    """旧来の `from backend.jsonl.session_status import is_user_prompt` 経路が、
    `predicates.is_user_prompt` と同一関数を指すことを担保 (= 委譲の break 防止)。"""
    from backend.jsonl import session_status
    assert session_status.is_user_prompt is p.is_user_prompt
