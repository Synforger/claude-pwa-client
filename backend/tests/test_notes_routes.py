"""タブごとのメモの口 (= GET / PUT /sessions/{sid}/note) と、 真値の file の扱い。

メモはそのタブの持ち物: 他のタブからは見えず、 タブを消すと一緒に消える。 画面はこの口から、
そのタブのエージェントは `PWA_NOTE` が指す同じ file を直に書く。
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import backend.paths as paths
from backend._generated import http_endpoints as http
from backend.config import FILE_SIZE_LIMIT
from backend.terminal.runner import tmux_session_env_args


@pytest.fixture
def tabs(tmp_path, monkeypatch, isolated_state):
    """メモの置き場を作り物にし、 タブを 2 つ登録する。"""
    monkeypatch.setattr(paths, "NOTES_DIR", tmp_path / "notes")
    monkeypatch.setattr(isolated_state, "save_sessions_meta", lambda: None)
    # AGENTS は読むたびに設定から作られる。 test 用の設定に差し替わった後 (= ここ) で読む
    from backend.config import AGENTS  # noqa: PLC0415
    aid = next(iter(AGENTS))
    return isolated_state.register_session(aid, title="A"), isolated_state.register_session(aid, title="B")


@pytest.fixture
def client(tabs):
    # メモの口はタブの口 (= routes/sessions) を読み込み、 そちらは読み込まれた時点の設定を掴む。
    # test 用の設定に差し替わった後 (= ここ) で読み込む (= 先頭で読むと、 後続の test が空の設定で動く)
    import backend.routes.notes as notes  # noqa: PLC0415
    app = FastAPI()
    app.include_router(notes.router)
    return TestClient(app)


def _file(sid):
    return paths.NOTES_DIR / f"{sid}.md"


def test_a_tab_without_a_note_reads_empty(client, tabs):
    a, _ = tabs
    assert client.get(f"/sessions/{a.id}/note").json() == {"path": str(_file(a.id)), "content": ""}
    assert not _file(a.id).exists()


def test_put_writes_the_file_of_that_tab_only(client, tabs):
    a, b = tabs
    body = client.put(f"/sessions/{a.id}/note", json={"content": "# 設計\n- 6 行で止める\n"}).json()
    assert body == {"path": str(_file(a.id)), "content": "# 設計\n- 6 行で止める\n"}
    assert _file(a.id).read_text(encoding="utf-8") == "# 設計\n- 6 行で止める\n"
    # 別のタブからは見えない
    assert client.get(f"/sessions/{b.id}/note").json()["content"] == ""
    assert not _file(b.id).exists()


def test_what_the_agent_wrote_to_the_file_is_what_the_screen_reads(client, tabs):
    a, _ = tabs
    paths.NOTES_DIR.mkdir(parents=True)
    _file(a.id).write_text("エージェントが抜き出した文\n", encoding="utf-8")
    assert client.get(f"/sessions/{a.id}/note").json()["content"] == "エージェントが抜き出した文\n"


def test_an_empty_note_removes_the_file(client, tabs):
    a, _ = tabs
    client.put(f"/sessions/{a.id}/note", json={"content": "x"})
    assert _file(a.id).exists()
    assert client.put(f"/sessions/{a.id}/note", json={"content": ""}).json()["content"] == ""
    assert not _file(a.id).exists()
    # 無い物を空にしても通る
    assert client.put(f"/sessions/{a.id}/note", json={"content": ""}).status_code == 200


def test_an_unknown_tab_is_not_found(client):
    assert client.get("/sessions/ses_nope/note").status_code == 404
    assert client.put("/sessions/ses_nope/note", json={"content": "x"}).status_code == 404
    assert not (paths.NOTES_DIR / "ses_nope.md").exists()


def test_a_note_over_the_size_limit_is_refused_both_ways(client, tabs):
    a, _ = tabs
    assert client.put(f"/sessions/{a.id}/note", json={"content": "x" * (FILE_SIZE_LIMIT + 1)}).status_code == 413
    assert not _file(a.id).exists()
    paths.NOTES_DIR.mkdir(parents=True)
    _file(a.id).write_text("x" * (FILE_SIZE_LIMIT + 1), encoding="utf-8")
    assert client.get(f"/sessions/{a.id}/note").status_code == 413


def test_responses_match_the_contract(client, tabs):
    a, _ = tabs
    http.PutSessionsSidNoteRequest.model_validate({"content": "x"})
    http.PutSessionsSidNoteResponse.model_validate(client.put(f"/sessions/{a.id}/note", json={"content": "x"}).json())
    http.GetSessionsSidNoteResponse.model_validate(client.get(f"/sessions/{a.id}/note").json())


@pytest.mark.parametrize("bad", ["", "../x", "a/b", "/abs"])
def test_note_path_refuses_what_is_not_an_id(bad):
    with pytest.raises(ValueError):
        paths.note_path(bad)


def test_deleting_the_tab_removes_its_note_and_no_other(client, tabs, monkeypatch):
    import backend.routes.sessions as sessions_routes  # noqa: PLC0415
    monkeypatch.setattr(sessions_routes, "kill_tmux_session", lambda _sid: None)
    a, b = tabs
    client.put(f"/sessions/{a.id}/note", json={"content": "a"})
    client.put(f"/sessions/{b.id}/note", json={"content": "b"})
    # 自分用の loop で回す (= 共有の loop は、 先に走った test が閉じていることがある)
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(sessions_routes.delete_session(a.id, _="ok"))
    finally:
        loop.close()
    assert not _file(a.id).exists()
    assert _file(b.id).read_text(encoding="utf-8") == "b"


# --- エージェントへ渡す環境変数 ---

def test_session_env_names_the_note_of_that_tab():
    args = tmux_session_env_args("ses_abc", {"PWA_NOTE": "/spoof"})
    assert f"PWA_NOTE={paths.NOTES_DIR / 'ses_abc.md'}" in args
    assert "PWA_NOTE=/spoof" not in args
