"""fork.py の純ロジック test。

会話フォーク = ある行 (from_uuid) を leaf に parentUuid 鎖を根まで遡り、 その lineage
だけを残した新セッションの jsonl を作る。 実 claude jsonl を模した最小 fixture で、
(1) 鎖の遡りと打ち切り、 (2) sessionId 書換、 (3) 分岐前の枝を捨てること、
(4) 切れ目 (clean fork point) 判定、 を固定する。
"""
import json

from fork import build_forked_lineage, is_clean_fork_point


def _line(uuid, parent, type_, **extra):
    d = {"uuid": uuid, "parentUuid": parent, "type": type_, "sessionId": "OLD"}
    d.update(extra)
    return json.dumps(d)


def _assistant(uuid, parent, stop="end_turn", content=None):
    msg = {"stop_reason": stop, "content": content if content is not None else [{"type": "text", "text": "hi"}]}
    return _line(uuid, parent, "assistant", message=msg)


# 根 u1(user) -> a1(assistant) -> u2(user) -> a2(assistant) の線形会話 + 先頭メタ行
SAMPLE = [
    json.dumps({"type": "queue-operation", "sessionId": "OLD", "operation": "x"}),
    _line("u1", None, "user"),
    _assistant("a1", "u1"),
    _line("u2", "a1", "user"),
    _assistant("a2", "u2"),
]


def _uuids(lines):
    return [json.loads(x)["uuid"] for x in lines]


def test_fork_keeps_root_to_leaf_in_order():
    out = build_forked_lineage(SAMPLE, from_uuid="u2", new_session_id="NEW")
    # u2 を leaf にすると u1 -> a1 -> u2 が残り、 a2 (分岐後) は捨てられる
    assert _uuids(out) == ["u1", "a1", "u2"]


def test_fork_rewrites_session_id():
    out = build_forked_lineage(SAMPLE, from_uuid="a2", new_session_id="NEW")
    assert all(json.loads(x)["sessionId"] == "NEW" for x in out)
    # 元の鎖 (uuid/parentUuid) はそのまま維持される
    assert _uuids(out) == ["u1", "a1", "u2", "a2"]
    assert json.loads(out[1])["parentUuid"] == "u1"


def test_fork_from_leaf_keeps_everything():
    out = build_forked_lineage(SAMPLE, from_uuid="a2", new_session_id="NEW")
    assert _uuids(out) == ["u1", "a1", "u2", "a2"]


def test_fork_meta_lines_excluded():
    # queue-operation 等の uuid を持たないメタ行は lineage に混ざらない
    out = build_forked_lineage(SAMPLE, from_uuid="a2", new_session_id="NEW")
    assert all(json.loads(x).get("type") in ("user", "assistant") for x in out)


def test_fork_unknown_uuid_raises():
    try:
        build_forked_lineage(SAMPLE, from_uuid="nope", new_session_id="NEW")
    except ValueError:
        return
    raise AssertionError("expected ValueError for unknown from_uuid")


def test_fork_stops_at_orphan_parent():
    # parentUuid がファイル内に無い (= compact/別session 由来) 行はそこが実質の根になる
    lines = [_line("x2", "MISSING", "user"), _assistant("x3", "x2")]
    out = build_forked_lineage(lines, from_uuid="x3", new_session_id="NEW")
    assert _uuids(out) == ["x2", "x3"]


def test_clean_point_user_message():
    assert is_clean_fork_point(SAMPLE, "u2") is True


def test_clean_point_assistant_text_only():
    # tool_use ブロックを含まない assistant (= テキスト回答) は切れ目
    assert is_clean_fork_point(SAMPLE, "a2") is True


def test_clean_point_rejects_assistant_with_tool_use():
    # tool_use ブロックを含む行は保留中なので不可 (stop_reason に依らず content で判定)
    content = [{"type": "text", "text": "x"}, {"type": "tool_use", "name": "Read", "id": "t1"}]
    lines = [_line("u1", None, "user"), _assistant("a1", "u1", stop="end_turn", content=content)]
    assert is_clean_fork_point(lines, "a1") is False


def test_clean_point_rejects_user_tool_result():
    # tool_result の user 行 (= ツール出力、 実プロンプトでない) は不可
    content = [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]
    lines = [_line("u1", None, "user", message={"content": content})]
    assert is_clean_fork_point(lines, "u1") is False


def test_clean_point_rejects_sidechain():
    lines = [_line("s1", None, "user", isSidechain=True)]
    assert is_clean_fork_point(lines, "s1") is False


def test_clean_point_unknown_uuid_false():
    assert is_clean_fork_point(SAMPLE, "nope") is False


# --- message.id (= assistant バブル識別子) 経由の解決 ---
# 1 つの API message が thinking 行 + text 行に分かれ、 同じ message.id を共有するケース。

def _asst_mid(uuid, parent, mid, blocks):
    msg = {"id": mid, "stop_reason": "tool_use", "content": blocks}
    return _line(uuid, parent, "assistant", message=msg)


# u1 -> [m1: think(a1) + text(a2) 同一 message.id] の clean な回答
GROUPED = [
    _line("u1", None, "user"),
    _asst_mid("a1", "u1", "msg_X", [{"type": "thinking", "thinking": "..."}]),
    _asst_mid("a2", "a1", "msg_X", [{"type": "text", "text": "answer"}]),
]


def test_status_resolves_message_id_to_clean_group():
    # frontend が送る from_uuid = message.id。 group に tool_use が無いので ok
    from fork import fork_point_status  # noqa: PLC0415
    assert fork_point_status(GROUPED, "msg_X") == "ok"


def test_status_message_id_group_with_tool_use_is_dirty():
    from fork import fork_point_status  # noqa: PLC0415
    lines = GROUPED + [_asst_mid("a3", "a2", "msg_X", [{"type": "tool_use", "name": "Read", "id": "t"}])]
    # 同 message.id に tool_use 行が混ざれば dirty
    assert fork_point_status(lines, "msg_X") == "dirty"


def test_build_lineage_from_message_id_uses_group_leaf():
    # message.id 指定 → group 最後 (a2) を leaf に鎖を遡る = u1,a1,a2 全部残る
    out = build_forked_lineage(GROUPED, from_uuid="msg_X", new_session_id="NEW")
    assert _uuids(out) == ["u1", "a1", "a2"]
    assert all(json.loads(x)["sessionId"] == "NEW" for x in out)


# --- エンドポイント (chat_routes.fork_session) の結線 test ---

def _setup_fork_env(tmp_path, monkeypatch, isolated_state, source_lines=SAMPLE):
    """親 session + source jsonl を用意し、 jsonl_path 解決を tmp に差し替える。"""
    import chat_routes  # noqa: PLC0415
    import pty_runner  # noqa: PLC0415
    from config import AGENTS  # noqa: PLC0415
    state = isolated_state
    monkeypatch.setattr(state, "save_sessions_meta", lambda: None)
    aid = next(iter(AGENTS))
    parent = state.register_session(aid, title="Chat")
    src = tmp_path / "OLD.jsonl"
    src.write_text("\n".join(source_lines) + "\n", encoding="utf-8")
    monkeypatch.setattr(pty_runner, "jsonl_path_for_session", lambda sid: src)
    return chat_routes, parent, src


def test_fork_endpoint_creates_indented_child(tmp_path, monkeypatch, isolated_state):
    chat_routes, parent, src = _setup_fork_env(tmp_path, monkeypatch, isolated_state)
    out = chat_routes.fork_session(parent.id, {"from_uuid": "u2"})
    assert out["parent_id"] == parent.id
    assert out["title"] == "Chat fork"
    assert out["agent_id"] == parent.agent_id
    # 新 jsonl が source の隣に書かれ、 ファイル名 = resume_session_id
    files = sorted(p for p in tmp_path.glob("*.jsonl") if p.name != "OLD.jsonl")
    assert len(files) == 1
    assert files[0].stem == out["resume_session_id"]
    assert _uuids(files[0].read_text().splitlines()) == ["u1", "a1", "u2"]


def test_fork_endpoint_rejects_dirty_point(tmp_path, monkeypatch, isolated_state):
    from fastapi import HTTPException  # noqa: PLC0415
    content = [{"type": "tool_use", "name": "Read", "id": "t1"}]
    lines = [_line("u1", None, "user"), _assistant("a1", "u1", content=content)]
    chat_routes, parent, _ = _setup_fork_env(tmp_path, monkeypatch, isolated_state, lines)
    try:
        chat_routes.fork_session(parent.id, {"from_uuid": "a1"})
    except HTTPException as e:
        assert e.status_code == 400
        return
    raise AssertionError("expected 400 for dirty fork point")


def test_fork_endpoint_requires_from_uuid(tmp_path, monkeypatch, isolated_state):
    from fastapi import HTTPException  # noqa: PLC0415
    chat_routes, parent, _ = _setup_fork_env(tmp_path, monkeypatch, isolated_state)
    try:
        chat_routes.fork_session(parent.id, {})
    except HTTPException as e:
        assert e.status_code == 400
        return
    raise AssertionError("expected 400 when from_uuid missing")


def test_fork_endpoint_finds_uuid_in_rolled_file(tmp_path, monkeypatch, isolated_state):
    """claude が session id をロールして、 from_uuid が live でなく project dir 内の別
    (= 古い) jsonl に居るケース。 cwd 内全 jsonl を走査して見つける。"""
    import jsonl_watcher  # noqa: PLC0415
    chat_routes, parent, live = _setup_fork_env(tmp_path, monkeypatch, isolated_state)
    # live (OLD.jsonl) には無い uuid を、 古いファイルに置く
    rolled = tmp_path / "rolled.jsonl"
    rolled.write_text("\n".join(SAMPLE) + "\n", encoding="utf-8")
    live.write_text(_line("zz", None, "user") + "\n", encoding="utf-8")  # live は別内容
    monkeypatch.setattr(jsonl_watcher, "_cwd_to_project_dir", lambda cwd: tmp_path)
    out = chat_routes.fork_session(parent.id, {"from_uuid": "u2"})
    assert out["parent_id"] == parent.id
    new = tmp_path / f"{out['resume_session_id']}.jsonl"
    assert _uuids(new.read_text().splitlines()) == ["u1", "a1", "u2"]


def test_fork_endpoint_not_found_across_all_files(tmp_path, monkeypatch, isolated_state):
    from fastapi import HTTPException  # noqa: PLC0415
    import jsonl_watcher  # noqa: PLC0415
    chat_routes, parent, _ = _setup_fork_env(tmp_path, monkeypatch, isolated_state)
    monkeypatch.setattr(jsonl_watcher, "_cwd_to_project_dir", lambda cwd: tmp_path)
    try:
        chat_routes.fork_session(parent.id, {"from_uuid": "ghost-uuid"})
    except HTTPException as e:
        assert e.status_code == 404
        return
    raise AssertionError("expected 404 when uuid is in no file")
