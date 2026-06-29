"""fork.py の純ロジック test。

会話フォーク = ある行 (from_uuid) を leaf に parentUuid 鎖を根まで遡り、 その lineage
だけを残した新セッションの jsonl を作る。 実 claude jsonl を模した最小 fixture で、
(1) 鎖の遡りと打ち切り、 (2) sessionId 書換、 (3) 分岐前の枝を捨てること、
(4) 切れ目 (clean fork point) 判定、 を固定する。
"""
import json

from backend.core.fork import build_forked_lineage_lazy, is_clean_fork_point


def build_forked_lineage(source_lines, from_uuid, new_session_id):
    """test ヘルパ: 自己完結 (= src_lines だけで鎖完走) を想定した lazy 版の薄いラッパ。

    旧 build_forked_lineage は production code から消えたが、 純ロジック test では
    src_lines が自己完結している前提で書かれており、 fetch_more は呼ばれない。
    lazy 版に no-op fetch_more を渡すだけで挙動は等価 (= ValueError 含む)。
    """
    return build_forked_lineage_lazy(source_lines, from_uuid, new_session_id, lambda: None)


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
    from backend.core.fork import fork_point_status  # noqa: PLC0415
    assert fork_point_status(GROUPED, "msg_X") == "ok"


def test_status_message_id_group_with_tool_use_is_dirty():
    from backend.core.fork import fork_point_status  # noqa: PLC0415
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
    import backend.routes.chat as chat_routes  # noqa: PLC0415
    import backend.terminal.runner as pty_runner  # noqa: PLC0415
    from backend.config import AGENTS  # noqa: PLC0415
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
    import backend.jsonl.watcher as jsonl_watcher  # noqa: PLC0415
    chat_routes, parent, live = _setup_fork_env(tmp_path, monkeypatch, isolated_state)
    # live (OLD.jsonl) には無い uuid を、 古いファイルに置く
    rolled = tmp_path / "rolled.jsonl"
    rolled.write_text("\n".join(SAMPLE) + "\n", encoding="utf-8")
    live.write_text(_line("zz", None, "user") + "\n", encoding="utf-8")  # live は別内容
    monkeypatch.setattr(jsonl_watcher, "_cwd_to_project_dir", lambda cwd, account_id=None: tmp_path)
    out = chat_routes.fork_session(parent.id, {"from_uuid": "u2"})
    assert out["parent_id"] == parent.id
    new = tmp_path / f"{out['resume_session_id']}.jsonl"
    assert _uuids(new.read_text().splitlines()) == ["u1", "a1", "u2"]


def test_lineage_root_resolved_returns_true_when_chain_completes():
    """parentUuid 鎖が根 (= null) まで到達してれば True。 build_forked_lineage の完走判定に使う。"""
    from backend.core.fork import lineage_root_resolved  # noqa: PLC0415
    lines = [
        _line("u1", None, "user"),
        _assistant("a1", "u1"),
        _line("u2", "a1", "user"),
    ]
    assert lineage_root_resolved(lines, "u2") is True


def test_lineage_root_resolved_returns_false_when_parent_missing():
    """親 uuid がファイル内に無ければ False = 別 jsonl にまたがってる、 lazy stitching が要る印。"""
    from backend.core.fork import lineage_root_resolved  # noqa: PLC0415
    lines = [
        _line("u2", "a1", "user"),       # 親 a1 は別 jsonl にある想定
        _assistant("a2", "u2"),
    ]
    assert lineage_root_resolved(lines, "u2") is False


def test_lineage_root_resolved_returns_false_when_from_uuid_absent():
    from backend.core.fork import lineage_root_resolved  # noqa: PLC0415
    assert lineage_root_resolved([_line("u1", None, "user")], "ghost") is False


def test_fork_endpoint_stitches_lineage_across_rolled_files(tmp_path, monkeypatch, isolated_state):
    """claude が会話 compact / session roll で 1 会話を複数 jsonl に分割しているケース。
    from_uuid を含む jsonl 単体では parentUuid 鎖が途中で切れる (= 親が別 jsonl) ため
    旧版は途中で打ち切って古い context を全部失った (2026-06-05 真因)。 同 project dir の
    関連 jsonl 群も結合して source_lines にすることで、 鎖を最後まで辿って full lineage を
    新 jsonl に書き出す。"""
    import backend.jsonl.watcher as jsonl_watcher  # noqa: PLC0415
    # 古い jsonl (= rolled) に root u1,a1、 新しい jsonl (= live) に u2,a2,u3。 u2 の親 a1 は
    # 別ファイル。 旧実装は live だけ source にして u2 から始まる短い lineage しか書けなかった。
    rolled_lines = [
        _line("u1", None, "user"),
        _assistant("a1", "u1"),
    ]
    live_lines = [
        _line("u2", "a1", "user"),       # 親 a1 は rolled.jsonl にある
        _assistant("a2", "u2"),
        _line("u3", "a2", "user"),
    ]
    chat_routes, parent, live = _setup_fork_env(tmp_path, monkeypatch, isolated_state, live_lines)
    rolled = tmp_path / "rolled.jsonl"
    rolled.write_text("\n".join(rolled_lines) + "\n", encoding="utf-8")
    monkeypatch.setattr(jsonl_watcher, "_cwd_to_project_dir", lambda cwd, account_id=None: tmp_path)
    out = chat_routes.fork_session(parent.id, {"from_uuid": "u3"})
    new = tmp_path / f"{out['resume_session_id']}.jsonl"
    # full lineage: rolled の u1,a1 + live の u2,a2,u3 を時系列順で 5 行揃う
    assert _uuids(new.read_text().splitlines()) == ["u1", "a1", "u2", "a2", "u3"]


def test_build_forked_lineage_lazy_self_contained_does_not_call_fetch_more():
    """src_lines 内で鎖が完走するケース、 fetch_more は 1 回も呼ばれない。 large project dir で
    無関係な jsonl を読まない (= fork が重くならない) ことの最小単位の担保。"""
    from backend.core.fork import build_forked_lineage_lazy  # noqa: PLC0415
    src = [
        _line("u1", None, "user"),
        _assistant("a1", "u1"),
        _line("u2", "a1", "user"),
    ]
    calls = {"count": 0}
    def fetch_more():
        calls["count"] += 1
        return None
    out = build_forked_lineage_lazy(src, "u2", "NEW", fetch_more)
    assert _uuids(out) == ["u1", "a1", "u2"]
    assert calls["count"] == 0


def test_build_forked_lineage_lazy_pulls_only_needed_files():
    """親 uuid が src_lines に無い時だけ fetch_more が呼ばれ、 親が見つかった時点で停止。
    候補 jsonl が複数あっても鎖完走後は呼ばれない。"""
    from backend.core.fork import build_forked_lineage_lazy  # noqa: PLC0415
    src = [
        _line("u2", "a1", "user"),       # 親 a1 は src に無い
        _assistant("a2", "u2"),
    ]
    file1 = [_assistant("a1", "u1")]      # a1 はここ
    file2 = [_line("u1", None, "user")]   # u1 (= 根) はここ
    file3 = [_line("ZZZ", None, "user")]  # 鎖完走後は呼ばれない
    fetches = [file1, file2, file3]
    def fetch_more():
        return fetches.pop(0) if fetches else None
    out = build_forked_lineage_lazy(src, "u2", "NEW", fetch_more)
    assert _uuids(out) == ["u1", "a1", "u2"]
    assert len(fetches) == 1  # file3 は残ったまま (= 呼ばれてない)


def test_build_forked_lineage_lazy_walks_through_system_rows():
    """parentUuid 鎖の中間に type='system' 行があっても完走する。 実機 jsonl で claude が
    note / caveat を system 行として鎖に挟むケースを実装が見逃してた (2026-06-05 真因、
    1475 行あるべき lineage が leaf 1 行だけになってた)。"""
    from backend.core.fork import build_forked_lineage_lazy  # noqa: PLC0415
    src = [
        _line("u1", None, "user"),
        _line("s1", "u1", "system"),       # 鎖の中間に system 行
        _assistant("a1", "s1"),
        _line("u2", "a1", "user"),
    ]
    out = build_forked_lineage_lazy(src, "u2", "NEW", lambda: None)
    assert _uuids(out) == ["u1", "s1", "a1", "u2"]  # system 行も lineage に含めて完走


def test_build_forked_lineage_lazy_walks_through_attachment_rows():
    """type='attachment' (= ファイル添付情報) も鎖の中間に入るケースを抜け落とさない。"""
    from backend.core.fork import build_forked_lineage_lazy  # noqa: PLC0415
    src = [
        _line("u1", None, "user"),
        _line("at1", "u1", "attachment"),
        _assistant("a1", "at1"),
    ]
    out = build_forked_lineage_lazy(src, "a1", "NEW", lambda: None)
    assert _uuids(out) == ["u1", "at1", "a1"]


def test_build_forked_lineage_lazy_stops_when_fetch_returns_none():
    """fetch_more が None を返したら、 そこまでの鎖で確定する (= 無限ループしない)。"""
    from backend.core.fork import build_forked_lineage_lazy  # noqa: PLC0415
    src = [_line("u2", "a1", "user")]  # 親 a1 はどこにも無い
    out = build_forked_lineage_lazy(src, "u2", "NEW", lambda: None)
    assert _uuids(out) == ["u2"]  # 鎖は u2 だけで打ち切り


def test_fork_endpoint_lazy_stops_reading_when_root_resolved(tmp_path, monkeypatch, isolated_state):
    """src_path 単体で鎖が完走するケースでは他 jsonl を 1 個も読まない (= lazy 振る舞い検証)。
    無関係な大きい jsonl が project dir にあっても fork POST は src_path だけ触る。"""
    import backend.jsonl.watcher as jsonl_watcher  # noqa: PLC0415
    # src_path に full lineage (= root から leaf まで揃ってる)
    full = [
        _line("u1", None, "user"),
        _assistant("a1", "u1"),
        _line("u2", "a1", "user"),
    ]
    chat_routes, parent, _ = _setup_fork_env(tmp_path, monkeypatch, isolated_state, full)
    # ノイズ jsonl を 5 個生やしておく (= 読まれたら _check 経路で uuid 衝突しないが、 行数が増える)
    for i in range(5):
        (tmp_path / f"noise-{i}.jsonl").write_text(
            _line(f"x{i}", None, "user") + "\n", encoding="utf-8",
        )
    monkeypatch.setattr(jsonl_watcher, "_cwd_to_project_dir", lambda cwd, account_id=None: tmp_path)
    out = chat_routes.fork_session(parent.id, {"from_uuid": "u2"})
    new = tmp_path / f"{out['resume_session_id']}.jsonl"
    # full lineage が新 jsonl に書かれる (= 3 行、 ノイズ x[i] は混ざらない)
    assert _uuids(new.read_text().splitlines()) == ["u1", "a1", "u2"]


def test_fork_endpoint_not_found_across_all_files(tmp_path, monkeypatch, isolated_state):
    from fastapi import HTTPException  # noqa: PLC0415
    import backend.jsonl.watcher as jsonl_watcher  # noqa: PLC0415
    chat_routes, parent, _ = _setup_fork_env(tmp_path, monkeypatch, isolated_state)
    monkeypatch.setattr(jsonl_watcher, "_cwd_to_project_dir", lambda cwd, account_id=None: tmp_path)
    try:
        chat_routes.fork_session(parent.id, {"from_uuid": "ghost-uuid"})
    except HTTPException as e:
        assert e.status_code == 404
        return
    raise AssertionError("expected 404 when uuid is in no file")


# --- フォーク産タブ削除時の jsonl GC ---
# build_forked_lineage で書き出した新 jsonl は claude --resume の入口。 タブを消したら
# このファイルも消える (= ディスク蓄積しない) のが期待動作。 元タブの jsonl は触らない。

import asyncio  # noqa: E402


def test_delete_fork_session_removes_its_jsonl(tmp_path, monkeypatch, isolated_state):
    import backend.routes.chat as chat_routes  # noqa: PLC0415
    import backend.jsonl.watcher as jsonl_watcher  # noqa: PLC0415
    chat_routes, parent, src = _setup_fork_env(tmp_path, monkeypatch, isolated_state)
    monkeypatch.setattr(jsonl_watcher, "_cwd_to_project_dir", lambda cwd, account_id=None: tmp_path)
    # フォーク作成 → 新 jsonl がある状態を確認
    forked = chat_routes.fork_session(parent.id, {"from_uuid": "u2"})
    new_path = tmp_path / f"{forked['resume_session_id']}.jsonl"
    assert new_path.exists()
    # フォーク産タブを DELETE
    asyncio.get_event_loop().run_until_complete(
        chat_routes.delete_session(forked["id"], _="ok")
    )
    # 新 jsonl は消える、 元タブの jsonl (= OLD.jsonl) は残る
    assert not new_path.exists()
    assert src.exists()


def test_delete_normal_session_does_not_touch_jsonl(tmp_path, monkeypatch, isolated_state):
    """通常タブ (= resume_session_id 無し) の DELETE では project dir の jsonl を絶対に触らない。
    フォーク GC ロジックが暴発しないかの安全弁テスト。"""
    import backend.routes.chat as chat_routes  # noqa: PLC0415
    chat_routes, parent, src = _setup_fork_env(tmp_path, monkeypatch, isolated_state)
    asyncio.get_event_loop().run_until_complete(
        chat_routes.delete_session(parent.id, _="ok")
    )
    assert src.exists()


# --- フォーク産タブ restart の通常タブ化 ---
# fork タブで restart を押した時、 resume_session_id を残したままだと
# `claude --resume <同一 id>` が走って claude CLI が重複起動を検知し rc=0 で即 exit する
# (= 2026-06-04 実機確認、 ターミナルが変わらず「終了してない」 ように見える)。 restart は
# 文脈リセット + プロセスリセットのセマンティクスに揃えるべきで、 fork の親文脈引き継ぎは
# 初回 spawn で完了した役目。 restart のタイミングで通常タブ化し fork jsonl も掃除する。


def test_restart_fork_session_promotes_to_normal_tab(tmp_path, monkeypatch, isolated_state):
    import backend.routes.chat as chat_routes  # noqa: PLC0415
    import backend.jsonl.watcher as jsonl_watcher  # noqa: PLC0415
    chat_routes, parent, _src = _setup_fork_env(tmp_path, monkeypatch, isolated_state)
    monkeypatch.setattr(jsonl_watcher, "_cwd_to_project_dir", lambda cwd, account_id=None: tmp_path)
    forked = chat_routes.fork_session(parent.id, {"from_uuid": "u2"})
    fork_jsonl = tmp_path / f"{forked['resume_session_id']}.jsonl"
    assert fork_jsonl.exists()
    # ensure_pty_session_for と内部副作用は noop に差し替え (= restart の通常タブ化部分のみを検証)
    from backend.terminal.routes import ensure_pty_session_for as real_spawn  # noqa: F401, PLC0415
    async def _noop(_sid, **_kwargs):
        return None
    import backend.terminal.routes as pty_routes  # noqa: PLC0415
    import backend.terminal.runner as pty_runner  # noqa: PLC0415
    monkeypatch.setattr(pty_routes, "ensure_pty_session_for", _noop)
    monkeypatch.setattr(pty_runner, "kill_tmux_session", lambda sid: True)
    # restart 実行
    asyncio.get_event_loop().run_until_complete(
        chat_routes.restart_session(forked["id"], _="ok")
    )
    # resume_session_id は剥がれて通常タブ化、 parent_id は派生履歴として残す
    from backend.state import sessions_meta  # noqa: PLC0415
    promoted = sessions_meta[forked["id"]]
    assert promoted.resume_session_id is None
    assert promoted.parent_id == parent.id
    # 役目を終えた fork jsonl は掃除される
    assert not fork_jsonl.exists()


def test_restart_normal_session_keeps_meta_unchanged(tmp_path, monkeypatch, isolated_state):
    """通常タブ (= resume_session_id 無し) の restart では meta を一切触らない安全弁テスト。"""
    import backend.routes.chat as chat_routes  # noqa: PLC0415
    chat_routes, parent, _ = _setup_fork_env(tmp_path, monkeypatch, isolated_state)
    async def _noop(_sid, **_kwargs):
        return None
    import backend.terminal.routes as pty_routes  # noqa: PLC0415
    import backend.terminal.runner as pty_runner  # noqa: PLC0415
    monkeypatch.setattr(pty_routes, "ensure_pty_session_for", _noop)
    monkeypatch.setattr(pty_runner, "kill_tmux_session", lambda sid: True)
    asyncio.get_event_loop().run_until_complete(
        chat_routes.restart_session(parent.id, _="ok")
    )
    from backend.state import sessions_meta  # noqa: PLC0415
    assert sessions_meta[parent.id].resume_session_id is None  # 元から None
    assert sessions_meta[parent.id].parent_id is None  # 通常タブのまま


def test_restart_passes_prefer_fresh_to_ensure_pty(tmp_path, monkeypatch, isolated_state):
    """restart は ensure_pty_session_for を `prefer_fresh=True` で呼ぶ (= autoresume race 回避)。

    直前 claude プロセスの shutdown 前に `claude --resume <直前 sid>` が走ると重複起動検知で
    rc=0 即 exit する race を防ぐため、 restart 経路は autoresume を skip して通常 alias 直行
    する設計 (= 2026-06-29 root cause 修正)。
    """
    import backend.routes.chat as chat_routes  # noqa: PLC0415
    chat_routes, parent, _ = _setup_fork_env(tmp_path, monkeypatch, isolated_state)
    captured = {}
    async def _spy(sid, **kwargs):
        captured["sid"] = sid
        captured["kwargs"] = kwargs
    import backend.terminal.routes as pty_routes  # noqa: PLC0415
    import backend.terminal.runner as pty_runner  # noqa: PLC0415
    monkeypatch.setattr(pty_routes, "ensure_pty_session_for", _spy)
    monkeypatch.setattr(pty_runner, "kill_tmux_session", lambda sid: True)
    asyncio.get_event_loop().run_until_complete(
        chat_routes.restart_session(parent.id, _="ok")
    )
    assert captured["sid"] == parent.id
    assert captured["kwargs"].get("prefer_fresh") is True


def test_create_session_invokes_ensure_pty(tmp_path, monkeypatch, isolated_state):
    """POST /sessions (= 新規タブ作成) は ensure_pty_session_for を呼ぶ (= 新 sid spawn 完結)。

    `/jsonl/stream/all` の起動 sweep は接続時点の sessions_meta snapshot しか見ないので、
    接続継続中に新 sid を追加しても spawn が走らない → 「ターミナルを表示」 を押すまで
    chat view 単独では起動が完結しない症状を、 create_session 自身が ensure を踏むことで根治
    (= 2026-06-29 修正)。 prefer_fresh は default の False (= 通常経路、 autoresume 許可)。
    """
    import backend.routes.sessions as sess_routes  # noqa: PLC0415
    captured = {}
    async def _spy(sid, **kwargs):
        captured["sid"] = sid
        captured["kwargs"] = kwargs
    import backend.terminal.routes as pty_routes  # noqa: PLC0415
    monkeypatch.setattr(pty_routes, "ensure_pty_session_for", _spy)
    result = asyncio.get_event_loop().run_until_complete(
        sess_routes.create_session({"agent_id": "agent_a", "title": "fresh"})
    )
    assert captured["sid"] == result["id"]
    # prefer_fresh は明示しない (= default False、 通常経路で autoresume 許可)
    assert captured["kwargs"].get("prefer_fresh", False) is False
