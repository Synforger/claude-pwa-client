"""pty_runner の単体テスト。

claude を直接 spawn する関数はテスト中に走らせると I/O と subprocess 起動が要るので、
end-to-end は `/bin/cat` を代用 spawn して PTY ポンプ全体 (= spawn → write → read → terminate)
を検証する。 pure な防御コード (= env 検出 / 引数バリデーション / exit 後 no-op) は
直接 unit test。
"""
import asyncio
import os

import pytest

import backend.terminal.runner as pty_runner


@pytest.fixture
def restore_pty_sessions():
    """test 終了時に pty_runner.pty_sessions を綺麗にする。"""
    snap = dict(pty_runner.pty_sessions)
    yield
    # 残ったセッションは強制終了
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(pty_runner.shutdown_all())
    finally:
        loop.close()
    pty_runner.pty_sessions.clear()
    pty_runner.pty_sessions.update(snap)


@pytest.fixture
def restore_env():
    snap = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(snap)


def test_spawn_rejects_anthropic_base_url(restore_env):
    """ANTHROPIC_BASE_URL が親 env に残ってたら起動拒否 (= proxy 経由を防ぐ)。"""
    os.environ["ANTHROPIC_BASE_URL"] = "http://localhost:8765/proxy"
    with pytest.raises(RuntimeError, match="ANTHROPIC_BASE_URL"):
        asyncio.run(pty_runner.spawn_pty_session("test-rejects-base-url"))


def test_spawn_rejects_empty_claude_path(monkeypatch, restore_env):
    """CLAUDE_PATH が空文字 / None だと spawn 拒否。"""
    os.environ.pop("ANTHROPIC_BASE_URL", None)
    monkeypatch.setattr(pty_runner, "CLAUDE_PATH", "")
    with pytest.raises(RuntimeError, match="CLAUDE_PATH"):
        asyncio.run(pty_runner.spawn_pty_session("test-rejects-empty-path"))


def test_write_and_resize_after_exit_are_noops():
    """exit_event が立ってる session に write / resize しても OSError を投げない。"""
    # 最小限の fake session、 master_fd は閉じた状態
    import types

    fake_proc = types.SimpleNamespace(returncode=0)
    session = pty_runner.PtySession(
        session_id="closed",
        process=fake_proc,  # type: ignore[arg-type]
        master_fd=-1,
        output_queue=asyncio.Queue(),
        exit_event=asyncio.Event(),
    )
    session.exit_event.set()

    # どちらも例外ナシで早期 return すれば OK
    pty_runner.write_pty(session, b"ignored")
    pty_runner.resize_pty(session, 40, 120)


def test_capture_tmux_scrollback_disabled_when_no_wrap(monkeypatch):
    """USE_TMUX_WRAP=False では capture は常に b''。"""
    monkeypatch.setattr(pty_runner, "USE_TMUX_WRAP", False)
    assert pty_runner.capture_tmux_scrollback("anything") == b""


def test_has_tmux_session_disabled_when_no_wrap(monkeypatch):
    monkeypatch.setattr(pty_runner, "USE_TMUX_WRAP", False)
    assert pty_runner.has_tmux_session("anything") is False


def test_capture_tmux_scrollback_returns_empty_on_unknown(monkeypatch):
    """tmux に存在しない session を指したら returncode!=0 で空 bytes。"""
    monkeypatch.setattr(pty_runner, "USE_TMUX_WRAP", True)
    # 存在しないだろう name を渡す (= 仮に存在しても無害な空 capture)
    out = pty_runner.capture_tmux_scrollback("__nonexistent_test_session__")
    assert out == b""


def test_tmux_session_name_sanitizes_special_chars():
    """tmux に渡せない記号 (`.`, `:`, ` `) を `_` 化、 prefix で衝突避け。"""
    assert pty_runner._tmux_session_name("foo") == "pwa-foo"
    assert pty_runner._tmux_session_name("foo.bar:baz qux") == "pwa-foo_bar_baz_qux"
    assert pty_runner._tmux_session_name("alpha-1_2") == "pwa-alpha-1_2"


def test_write_pty_control_mode_emits_send_keys():
    """control mode の write_pty は master fd に send-keys -H コマンドを書く。"""
    import types

    r, w = os.pipe()
    try:
        session = pty_runner.PtySession(
            session_id="cm-write",
            process=types.SimpleNamespace(returncode=None),  # type: ignore[arg-type]
            master_fd=w,
            output_queue=asyncio.Queue(),
            exit_event=asyncio.Event(),
            control_mode=True,
        )
        pty_runner.write_pty(session, b"hi")
        written = os.read(r, 4096).decode("latin-1")
        # tmux_name は pwa-<sanitized>、 入力 "hi" = 68 69 の hex
        assert written == "send-keys -t pwa-cm-write -H 68 69\n"
    finally:
        os.close(r)
        os.close(w)


def test_resize_pty_control_mode_emits_refresh_client():
    """control mode の resize_pty は master fd に refresh-client -C を書く。"""
    import types

    r, w = os.pipe()
    try:
        session = pty_runner.PtySession(
            session_id="cm-resize",
            process=types.SimpleNamespace(returncode=None),  # type: ignore[arg-type]
            master_fd=w,
            output_queue=asyncio.Queue(),
            exit_event=asyncio.Event(),
            control_mode=True,
        )
        pty_runner.resize_pty(session, rows=30, cols=100)
        written = os.read(r, 4096).decode("latin-1")
        # cols,rows の順 (= refresh-client -C は <cols>,<rows>)
        assert written == "refresh-client -C 100,30\n"
    finally:
        os.close(r)
        os.close(w)


# --- backend-F-53: _build_send_keys_chain helper -----------------------------


def test_build_send_keys_chain_single_line_text_no_enter():
    args, chained = pty_runner._build_send_keys_chain("pwa-x", text="hello")
    assert chained is False
    assert args == [["send-keys", "-t", "pwa-x", "-l", "hello"]]


def test_build_send_keys_chain_text_with_enter_chained():
    """Enter は text と同じ subprocess の `;` chain に入る (= paste race 防止)。"""
    args, chained = pty_runner._build_send_keys_chain("pwa-x", text="hi", enter=True)
    assert chained is True
    # 1 invocation の中に text と Enter が同居
    assert args[0] == [
        "send-keys", "-t", "pwa-x", "-l", "hi",
        ";", "send-keys", "-t", "pwa-x", "Enter",
    ]


def test_build_send_keys_chain_key_only():
    args, chained = pty_runner._build_send_keys_chain("pwa-x", key="Escape")
    assert chained is False
    assert args == [["send-keys", "-t", "pwa-x", "Escape"]]


def test_build_send_keys_chain_enter_only():
    """text 無し + key 無し + enter のみ (= 救済 Enter 経路) は別 invocation で Enter。"""
    args, chained = pty_runner._build_send_keys_chain("pwa-x", enter=True)
    assert chained is False
    assert args == [["send-keys", "-t", "pwa-x", "Enter"]]


def test_build_send_keys_chain_empty_no_args():
    args, chained = pty_runner._build_send_keys_chain("pwa-x")
    assert args == []
    assert chained is False


# --- backend-F-22: get_pane_cursor_y ----------------------------------------


def test_get_pane_cursor_y_returns_none_when_no_wrap(monkeypatch):
    monkeypatch.setattr(pty_runner, "USE_TMUX_WRAP", False)
    assert pty_runner.get_pane_cursor_y("anything") is None


def test_get_pane_cursor_y_parses_stdout(monkeypatch):
    """tmux が `3\\n` を返したら 3 を返す。 失敗時 (= rc!=0) は None。"""
    import types as _types
    monkeypatch.setattr(pty_runner, "USE_TMUX_WRAP", True)
    monkeypatch.setattr(
        pty_runner, "_run_tmux",
        lambda *args, **kw: _types.SimpleNamespace(returncode=0, stdout="3\n"),
    )
    assert pty_runner.get_pane_cursor_y("any") == 3
    monkeypatch.setattr(
        pty_runner, "_run_tmux",
        lambda *args, **kw: _types.SimpleNamespace(returncode=1, stdout=""),
    )
    assert pty_runner.get_pane_cursor_y("any") is None


# --- backend-F-49: prompt_ready signal --------------------------------------


def test_enqueue_output_sets_prompt_ready_on_bracketed_paste():
    """zsh が prompt 末尾で出す `\\x1b[?2004h` を _enqueue_output が見たら prompt_ready set。"""
    session = pty_runner.PtySession(
        session_id="px",
        process=None,  # type: ignore[arg-type]
        master_fd=-1,
        output_queue=asyncio.Queue(),
        exit_event=asyncio.Event(),
    )
    assert not session.prompt_ready.is_set()
    pty_runner._enqueue_output(session, b"prompt> \x1b[?2004h")
    assert session.prompt_ready.is_set()


def test_enqueue_output_does_not_set_prompt_ready_for_plain_text():
    session = pty_runner.PtySession(
        session_id="px2",
        process=None,  # type: ignore[arg-type]
        master_fd=-1,
        output_queue=asyncio.Queue(),
        exit_event=asyncio.Event(),
    )
    pty_runner._enqueue_output(session, b"random data")
    assert not session.prompt_ready.is_set()


def test_spawn_cat_roundtrip(restore_env, restore_pty_sessions, monkeypatch):
    """`/bin/cat` を代用 spawn して PTY ポンプ全体を検証。

    cat は stdin を stdout にそのまま返すので、 write_pty → output_queue から
    同じバイト列が読めれば PTY pump が機能してる。 さらに terminate で
    exit_event が立つことも確認。

    USE_TMUX_WRAP=False に倒すのは、 test 終了後に tmux サーバ内にゴミセッションを
    残さないため (= test 環境を汚さない)。 tmux 込みの動作確認は別途
    integration test または smoketest で行う。
    """
    os.environ.pop("ANTHROPIC_BASE_URL", None)
    # spawn は PTY_INITIAL_ARGV で起動するので、 ここを `/bin/cat` 1 個に差替えて
    # echo 子プロセスを試す。 CLAUDE_PATH は validation 用に残ってるので空でない値を入れる。
    monkeypatch.setattr(pty_runner, "PTY_INITIAL_ARGV", ["/bin/cat"])
    monkeypatch.setattr(pty_runner, "CLAUDE_PATH", "/bin/true")
    monkeypatch.setattr(pty_runner, "USE_TMUX_WRAP", False)

    async def scenario() -> None:
        session = await pty_runner.spawn_pty_session("roundtrip-test")
        assert session.process.returncode is None
        assert session.session_id == "roundtrip-test"

        marker = b"hello via PTY"
        pty_runner.write_pty(session, marker + b"\n")

        # PTY echo (= cat の出力) を最大 2 秒待つ。 PTY 経由なので OPOST が NL→CRLF に
        # 変換 + ICRNL が CR→NL に変換するため、 元の "\n" は受信側で "\r\n" として
        # 流れてくることがある。 substring 判定で吸収する。
        received = bytearray()
        deadline = asyncio.get_event_loop().time() + 2.0
        while marker not in bytes(received) and asyncio.get_event_loop().time() < deadline:
            try:
                chunk = await asyncio.wait_for(session.output_queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            received.extend(chunk)
        assert marker in bytes(received), (
            f"expected {marker!r} in received={bytes(received)!r}"
        )

        await pty_runner.terminate_pty_session(session, timeout=2.0)
        assert session.exit_event.is_set()

    asyncio.run(scenario())


def test_list_pane_alternate_states_parses_batch_output(monkeypatch):
    """list-panes -a の一括出力を {session_name: alternate_on} に parse する
    (= detector loop の per-session subprocess 集約経路)。"""
    import asyncio

    class _R:
        returncode = 0
        stdout = "pwa-ses_a\t0\npwa-ses_b\t1\nother-session\t0\n"

    monkeypatch.setattr(pty_runner, "USE_TMUX_WRAP", True)
    monkeypatch.setattr(pty_runner, "_run_tmux", lambda *a, **k: _R())
    states = asyncio.run(pty_runner.list_pane_alternate_states())
    assert states == {"pwa-ses_a": False, "pwa-ses_b": True, "other-session": False}


def test_list_pane_alternate_states_none_on_failure(monkeypatch):
    """tmux 失敗 (= None) / USE_TMUX_WRAP=False は None (= caller は per-session fallback)。"""
    import asyncio

    monkeypatch.setattr(pty_runner, "USE_TMUX_WRAP", True)
    monkeypatch.setattr(pty_runner, "_run_tmux", lambda *a, **k: None)
    assert asyncio.run(pty_runner.list_pane_alternate_states()) is None

    monkeypatch.setattr(pty_runner, "USE_TMUX_WRAP", False)
    assert asyncio.run(pty_runner.list_pane_alternate_states()) is None


# --- 検証付き paste 展開 (= 2026-07-10 「複数行 paste で本文が二重」 根治) ---


def test_build_send_keys_chain_multiline_pastes_once(monkeypatch):
    """複数行 text の paste-buffer chain は **1 回だけ** (= 旧無条件 2 回が本文二重の原因)。"""
    import subprocess as sp
    import types
    monkeypatch.setattr(
        pty_runner.subprocess, "run",
        lambda *a, **k: types.SimpleNamespace(returncode=0, stdout=b"", stderr=b""),
    )
    args, chained = pty_runner._build_send_keys_chain("pwa-x", text="line1\nline2")
    assert chained is False
    assert len(args) == 1
    pastes = [i for i, tok in enumerate(args[0]) if tok == "paste-buffer"]
    assert len(pastes) == 1
    assert "-d" in args[0]  # buffer は 1 回で使い切り削除


def test_paste_placeholder_ids_and_delta():
    """プレースホルダ番号の集合差分で「新形成」 を判定 (= 会話 log の過去 echo は無視)。"""
    before = "old chat: [Pasted text #1 +30 lines] was here\n❯ "
    after_formed = before + "\n❯ [Pasted text #2 +12 lines]"
    after_literal = before + "\nline1\nline2"
    assert pty_runner.paste_placeholder_ids(before) == frozenset({"1"})
    assert pty_runner.paste_formed_placeholder(before, after_formed) is True
    assert pty_runner.paste_formed_placeholder(before, after_literal) is False
    assert pty_runner.paste_formed_placeholder("", "") is False


def test_send_text_two_stage_expands_only_when_placeholder_formed(monkeypatch):
    """複数行送信: プレースホルダが形成された時だけ展開 paste (= text 送信 2 回目) を送る。"""
    calls = []
    def fake_send(sid, text=None, key=None, enter=False):
        calls.append({"text": text, "key": key, "enter": enter})
        return True
    captures = ["❯ ", "❯ [Pasted text #1 +3 lines]"]  # before / after
    monkeypatch.setattr(pty_runner, "tmux_send_keys", fake_send)
    monkeypatch.setattr(pty_runner, "capture_pane_ansi_tail", lambda sid: captures.pop(0))
    asyncio.run(pty_runner.send_text_two_stage("ses_x", "a\nb\nc"))
    text_sends = [c for c in calls if c["text"]]
    assert len(text_sends) == 2  # 本 paste + 展開 paste
    assert calls[-1]["enter"] is True


def test_send_text_two_stage_no_expand_when_pasted_literally(monkeypatch):
    """プレースホルダが形成されない (= 本文がそのまま入った) なら展開 paste を送らない
    (= これが二重文字の再発防止の核心)。"""
    calls = []
    def fake_send(sid, text=None, key=None, enter=False):
        calls.append({"text": text, "key": key, "enter": enter})
        return True
    captures = ["❯ ", "❯ a\n  b\n  c"]  # before / after: 本文が直接入った
    monkeypatch.setattr(pty_runner, "tmux_send_keys", fake_send)
    monkeypatch.setattr(pty_runner, "capture_pane_ansi_tail", lambda sid: captures.pop(0))
    asyncio.run(pty_runner.send_text_two_stage("ses_x", "a\nb\nc"))
    text_sends = [c for c in calls if c["text"]]
    assert len(text_sends) == 1  # 1 回だけ = 二重にならない
    assert calls[-1]["enter"] is True


def test_send_text_two_stage_single_line_unchanged(monkeypatch):
    """1 行 text は従来通り capture なしの単純 2 段 (= wipe → send → Enter)。"""
    calls = []
    def fake_send(sid, text=None, key=None, enter=False):
        calls.append({"text": text, "enter": enter})
        return True
    def no_capture(sid):
        raise AssertionError("single-line must not capture")
    monkeypatch.setattr(pty_runner, "tmux_send_keys", fake_send)
    monkeypatch.setattr(pty_runner, "capture_pane_ansi_tail", no_capture)
    asyncio.run(pty_runner.send_text_two_stage("ses_x", "hello"))
    assert [c for c in calls if c["text"]] == [{"text": "hello", "enter": False}]
    assert calls[-1]["enter"] is True


# --- tmux socket 隔離 (= 2026-07-15 resume storm 事故対応) ---

def test_tmux_base_argv_default_socket(monkeypatch):
    """CPC_TMUX_SOCKET 未設定 = default socket (= 本番はこれ)。"""
    import backend.terminal.runner as runner
    monkeypatch.setattr(runner, "TMUX_SOCKET_NAME", None)
    assert runner.tmux_base_argv() == [runner.TMUX_BIN]


def test_tmux_base_argv_isolated_socket(monkeypatch):
    """socket 指定時は -L が入る (= e2e backend は cpc-e2e に隔離、 本番 pwa-* に触れない)。"""
    import backend.terminal.runner as runner
    monkeypatch.setattr(runner, "TMUX_SOCKET_NAME", "cpc-e2e")
    assert runner.tmux_base_argv() == [runner.TMUX_BIN, "-L", "cpc-e2e"]


def test_run_tmux_uses_base_argv(monkeypatch):
    """_run_tmux が tmux_base_argv 経由で argv を組む (= 直書き回帰の防止)。"""
    import backend.terminal.runner as runner
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        class R:
            returncode = 0
            stdout = b""
            stderr = b""
        return R()
    monkeypatch.setattr(runner, "TMUX_SOCKET_NAME", "sock-x")
    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    runner._run_tmux("list-sessions")
    assert seen["argv"][:3] == [runner.TMUX_BIN, "-L", "sock-x"]


def test_maintenance_tmux_calls_use_base_argv(monkeypatch):
    """maintenance の tmux 呼び出しも socket prefix を通る (= test backend の掃除が
    本番 socket の session を kill しない構造保証)。"""
    import backend.maintenance as maintenance
    import backend.terminal.runner as runner
    seen = []

    def fake_run(argv, **kwargs):
        seen.append(argv)
        class R:
            returncode = 0
            stdout = ""
            stderr = ""
        return R()
    monkeypatch.setattr(runner, "TMUX_SOCKET_NAME", "sock-y")
    monkeypatch.setattr(maintenance.subprocess, "run", fake_run)
    maintenance.cleanup_stale_tmux_sessions()
    assert seen, "tmux list-sessions が呼ばれる"
    assert all(a[:3] == [runner.TMUX_BIN, "-L", "sock-y"] for a in seen)
