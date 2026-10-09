"""お気に入りの口 (= GET / POST / DELETE /favorites) と、 真値の file の扱い。

真値は 1 行に 1 path のテキスト。 画面はこの口から、 エージェントは file に 1 行足して登録する。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import backend.paths as paths
import backend.routes.favorites as favorites
from backend._generated import http_endpoints as http
from backend.terminal.runner import tmux_session_env_args


@pytest.fixture
def home(tmp_path, monkeypatch):
    """作り物の HOME と、 その中の favorites.txt。"""
    home = tmp_path / "home"
    (home / "sample" / "docs").mkdir(parents=True)
    (home / "sample" / "notes.md").write_text("x", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(favorites, "HOME", home)
    monkeypatch.setattr(paths, "FAVORITES_PATH", home / ".claude-pwa-client" / "favorites.txt")
    return home


@pytest.fixture
def client(home):
    app = FastAPI()
    app.include_router(favorites.router)
    return TestClient(app)


def _file(home):
    return home / ".claude-pwa-client" / "favorites.txt"


def test_no_file_means_empty(client):
    assert client.get("/favorites").json() == {"favorites": []}


def test_add_writes_one_line_and_derives_name_and_kind(client, home):
    body = client.post("/favorites", json={"path": str(home / "sample" / "docs")}).json()
    assert body == {"favorites": [{"path": str(home / "sample" / "docs"), "name": "docs", "is_dir": True}]}
    # HOME の下は `~/...` で書く
    assert _file(home).read_text(encoding="utf-8") == "~/sample/docs\n"

    body = client.post("/favorites", json={"path": "~/sample/notes.md"}).json()
    assert [f["name"] for f in body["favorites"]] == ["docs", "notes.md"]
    assert body["favorites"][1]["is_dir"] is False
    assert _file(home).read_text(encoding="utf-8") == "~/sample/docs\n~/sample/notes.md\n"


def test_add_is_idempotent_whatever_the_spelling(client, home):
    client.post("/favorites", json={"path": "~/sample/docs"})
    client.post("/favorites", json={"path": str(home / "sample" / "docs")})
    client.post("/favorites", json={"path": "~/sample/docs/"})
    assert _file(home).read_text(encoding="utf-8") == "~/sample/docs\n"


def test_remove_takes_only_that_line(client, home):
    client.post("/favorites", json={"path": "~/sample/docs"})
    client.post("/favorites", json={"path": "~/sample/notes.md"})
    body = client.request("DELETE", "/favorites", params={"path": str(home / "sample" / "docs")}).json()
    assert [f["name"] for f in body["favorites"]] == ["notes.md"]
    assert _file(home).read_text(encoding="utf-8") == "~/sample/notes.md\n"


def test_remove_of_an_unknown_path_changes_nothing(client, home):
    client.post("/favorites", json={"path": "~/sample/docs"})
    before = _file(home).stat().st_mtime_ns
    body = client.request("DELETE", "/favorites", params={"path": "~/elsewhere"}).json()
    assert [f["name"] for f in body["favorites"]] == ["docs"]
    assert _file(home).stat().st_mtime_ns == before


def test_a_line_appended_by_hand_is_listed(client, home):
    # エージェントや人が、 末尾の改行なしで 1 行足した時
    _file(home).parent.mkdir(parents=True)
    _file(home).write_text("~/sample/docs\n" + str(home / "sample" / "notes.md"), encoding="utf-8")
    assert [f["name"] for f in client.get("/favorites").json()["favorites"]] == ["docs", "notes.md"]
    # その後に画面から足しても、 手で足した行と混ざらない
    client.post("/favorites", json={"path": "~/sample"})
    assert _file(home).read_text(encoding="utf-8").splitlines() == [
        "~/sample/docs", str(home / "sample" / "notes.md"), "~/sample",
    ]


def test_lines_that_are_not_paths_are_skipped_and_kept(client, home):
    _file(home).parent.mkdir(parents=True)
    _file(home).write_text("# 設計の資料\n\n~/sample/docs\nrelative/path\n~/sample/docs\n", encoding="utf-8")
    assert [f["path"] for f in client.get("/favorites").json()["favorites"]] == [str(home / "sample" / "docs")]
    client.post("/favorites", json={"path": "~/sample/notes.md"})
    client.request("DELETE", "/favorites", params={"path": "~/sample/docs"})
    assert _file(home).read_text(encoding="utf-8") == "# 設計の資料\n\nrelative/path\n~/sample/notes.md\n"


def test_a_missing_path_is_still_listed(client, home):
    # 消えた file も一覧から勝手に落とさない (= 外すのは利用者)
    body = client.post("/favorites", json={"path": "~/gone/file.md"}).json()
    assert body["favorites"] == [{"path": str(home / "gone" / "file.md"), "name": "file.md", "is_dir": False}]


def test_outside_home_is_listed_without_looking_at_the_disk(client, home, monkeypatch):
    seen = []
    monkeypatch.setattr(favorites.os.path, "isdir", lambda p: seen.append(p) or True)
    body = client.post("/favorites", json={"path": "/etc"}).json()
    assert body["favorites"] == [{"path": "/etc", "name": "etc", "is_dir": False}]
    assert seen == []
    assert _file(home).read_text(encoding="utf-8") == "/etc\n"


@pytest.mark.parametrize("bad", ["relative/path", "", "   ", "~/a\n~/b"])
def test_add_rejects_what_is_not_one_path(client, home, bad):
    assert client.post("/favorites", json={"path": bad}).status_code == 400
    assert not _file(home).exists()


def test_remove_rejects_what_is_not_one_path(client):
    assert client.request("DELETE", "/favorites", params={"path": "relative"}).status_code == 400


def test_responses_match_the_contract(client):
    # 契約 (= contracts/schema/http-endpoints.yaml) の生成 model は、 未知の field を拒む
    added = client.post("/favorites", json={"path": "~/sample/docs"}).json()
    http.PostFavoritesRequest.model_validate({"path": "~/sample/docs"})
    http.PostFavoritesResponse.model_validate(added)
    http.GetFavoritesResponse.model_validate(client.get("/favorites").json())
    removed = client.request("DELETE", "/favorites", params={"path": "~/sample/docs"}).json()
    http.DeleteFavoritesResponse.model_validate(removed)


# --- エージェントへ渡す環境変数 ---

def test_session_env_names_the_tab_and_the_favorites_file():
    args = tmux_session_env_args("ses_abc", None)
    assert args[:4] == ["-e", "PWA_SID=ses_abc", "-e", f"PWA_FAVORITES={paths.FAVORITES_PATH}"]


def test_session_env_keeps_the_agent_env_but_not_over_the_reserved_names():
    args = tmux_session_env_args("ses_abc", {
        "CLAUDE_CONFIG_DIR": "/x", "SKIPPED": None, "PWA_SID": "spoof", "PWA_FAVORITES": "/spoof",
    })
    assert args[:4] == ["-e", "PWA_SID=ses_abc", "-e", f"PWA_FAVORITES={paths.FAVORITES_PATH}"]
    # backend が決める変数の後ろに、 agent cfg の分だけが続く
    assert args[-2:] == ["-e", "CLAUDE_CONFIG_DIR=/x"]
    assert not any(a in ("PWA_SID=spoof", "PWA_FAVORITES=/spoof") or a.startswith("SKIPPED=") for a in args)
