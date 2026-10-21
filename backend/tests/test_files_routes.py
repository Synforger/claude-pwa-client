"""files_routes.py の _resolve_safe (= path injection 防御) の unit test。"""
import pathlib

import pytest
from fastapi import HTTPException

from backend.config import HOME
from backend.routes.files import _resolve_safe


def test_resolve_safe_inside_home():
    # 意図: HOME 配下のパスは resolve されてそのまま返る
    p = _resolve_safe(str(HOME / "x" / "y"))
    assert str(p).startswith(str(HOME))


def test_resolve_safe_tilde_expansion():
    # 意図: "~/foo" は HOME 配下に展開される
    p = _resolve_safe("~/foo.txt")
    assert p == HOME / "foo.txt"


def test_resolve_safe_outside_home_raises():
    # 意図: /etc/passwd 等 HOME 外は 403 (path injection 防御)
    with pytest.raises(HTTPException) as exc_info:
        _resolve_safe("/etc/passwd")
    assert exc_info.value.status_code == 403


def test_resolve_safe_dotdot_escape_raises():
    # 意図: HOME 配下から .. で抜けようとしても resolve 後の prefix 判定で止まる
    with pytest.raises(HTTPException) as exc_info:
        _resolve_safe(str(HOME) + "/../../etc")
    assert exc_info.value.status_code == 403


# --- deny list (= 秘密ファイルの読み書き阻止) ---

@pytest.mark.parametrize("path", [
    "~/.ssh/id_rsa",
    "~/.ssh/authorized_keys",
    "~/.ssh/config",
    "~/.aws/credentials",
    "~/.gnupg/private-keys-v1.d",
    "~/.kube/config",
    "~/.docker/config.json",
    "~/.netrc",
    "~/.zshrc",
    "~/.zshenv",
    "~/.bashrc",
    "~/.bash_profile",
    "~/.zsh_history",
    "~/.bash_history",
    "~/somewhere/key.pem",
    "~/somewhere/cert.p12",
    "~/something/id_ed25519",
    "~/.config/gh/hosts.yml",
    # token を平文で持つ設定 (= ホームの直下に限らず、 repo やアプリの中に在る)
    "~/somewhere/.envrc",
    "~/somewhere/.env",
    "~/somewhere/.env.local",
    "~/somewhere/.env.production",
    "~/somewhere/secrets/vapid.json",
    "~/.claude/.credentials.json",
    "~/.claude-work/.credentials.json",
    "~/.claude.json",
    "~/.npmrc",
    "~/.pypirc",
    "~/.git-credentials",
    "~/.pgpass",
    "~/.azure/accessTokens.json",
    "~/.config/gcloud/credentials.db",
    "~/Library/Keychains/login.keychain-db",
])
def test_resolve_safe_denies_secret_paths(path):
    # 意図: SSH 鍵 / クラウド認証 / token を持つ設定 / シェル rc / 履歴 / 証明書 は 403 で拒否される
    with pytest.raises(HTTPException) as exc_info:
        _resolve_safe(path)
    assert exc_info.value.status_code == 403


def test_resolve_safe_allows_ordinary_paths():
    # 意図: deny list に当たらない通常 path は通過する
    p = _resolve_safe(str(HOME / "repos" / "myproj" / "README.md"))
    assert str(p).endswith("README.md")


@pytest.mark.parametrize("path", [
    "~/somewhere/.env.example",
    "~/somewhere/.env.sample",
    "~/somewhere/.env.template",
    "~/somewhere/environment.md",
    "~/somewhere/secrets_manager.py",
    "~/somewhere/secrets-handling.md",
    "~/.claude/settings.json",
    "~/somewhere/config.json",
])
def test_resolve_safe_allows_what_only_looks_like_a_secret(path):
    # 意図: 雛形の .env と、 名前に secret を含むだけの file は読める (= 名前の一致は「その名前そのもの」 だけ)
    assert _resolve_safe(path)


# --- /task-output (= background task の出力ログ専用経路) ---

def _task_output_client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import backend.routes.files as files_routes
    app = FastAPI()
    app.include_router(files_routes.router)
    return TestClient(app)


def test_task_output_reads_tmp_task_file(tmp_path, monkeypatch):
    # 意図: /tmp/claude-<uid>/.../tasks/<id>.output の中身を読める (= HOME 外でも専用経路で許可)
    import backend.routes.files as files_routes
    real = tmp_path / "claude-501" / "proj" / "sess" / "tasks" / "abc123.output"
    real.parent.mkdir(parents=True)
    real.write_text("task log here\nexit 0\n")
    # 実 path の代わりに tmp_path を許可するよう regex を差し替えて隔離テスト
    monkeypatch.setattr(
        files_routes, "_TASK_OUTPUT_RE",
        __import__("re").compile(rf"^{tmp_path}/claude-\d+/[^/]+/[^/]+/tasks/[A-Za-z0-9._-]+\.output$"),
    )
    client = _task_output_client()
    res = client.get("/task-output", params={"path": str(real)})
    assert res.status_code == 200
    assert "task log here" in res.json()["content"]


def test_task_output_rejects_non_task_path():
    # 意図: tasks 出力パターン以外 (= /etc/passwd 等) は 403
    client = _task_output_client()
    res = client.get("/task-output", params={"path": "/etc/passwd"})
    assert res.status_code == 403


def test_task_output_rejects_traversal():
    # 意図: .. で tasks ディレクトリから抜けようとしても resolve 後の再検査で 403
    client = _task_output_client()
    res = client.get(
        "/task-output",
        params={"path": "~/x/p/s/tasks/../../../../etc/passwd"},
    )
    assert res.status_code == 403


def test_task_transcript_parses_subagent_jsonl_via_symlink(tmp_path, monkeypatch):
    # 意図: /task-transcript は symlink 追跡後が subagent jsonl なら parse して events を返す
    # (= /sessions 経路が claude_sid drift で 404 になる履歴 task を救う)。
    import backend.routes.files as files_routes
    fake_home = tmp_path / "home"
    projects = fake_home / ".claude" / "projects" / "-Users-x-proj" / "sid-abc"
    subagents = projects / "subagents"
    subagents.mkdir(parents=True)
    real_jsonl = subagents / "agent-a123.jsonl"
    real_jsonl.write_text(
        '{"type":"user","isSidechain":true,"message":{"role":"user","content":"hi"}}\n'
    )
    tasks_dir = tmp_path / "claude-501" / "-Users-x-proj" / "sid-abc" / "tasks"
    tasks_dir.mkdir(parents=True)
    symlink_src = tasks_dir / "a123.output"
    symlink_src.symlink_to(real_jsonl)
    monkeypatch.setattr(files_routes, "HOME", fake_home)
    client = _task_output_client()
    res = client.get("/task-transcript", params={"path": str(symlink_src)})
    assert res.status_code == 200
    body = res.json()
    assert body["agentId"] == "agent-a123"
    assert isinstance(body["events"], list)
    assert len(body["events"]) >= 1  # user 行が最低 1 個 event 化される


def test_task_transcript_404_for_non_subagent_output(tmp_path, monkeypatch):
    # 意図: /task-transcript は Monitor / Bash 由来の raw .output ファイル (subagent jsonl でない) には 404
    # を返し、 frontend は /task-output raw 経路に fallback する。
    import backend.routes.files as files_routes
    real = tmp_path / "claude-501" / "proj" / "sess" / "tasks" / "abc123.output"
    real.parent.mkdir(parents=True)
    real.write_text("plain task log\n")
    monkeypatch.setattr(
        files_routes, "_TASK_OUTPUT_RE",
        __import__("re").compile(rf"^{tmp_path}/claude-\d+/[^/]+/[^/]+/tasks/[A-Za-z0-9._-]+\.output$"),
    )
    client = _task_output_client()
    res = client.get("/task-transcript", params={"path": str(real)})
    assert res.status_code == 404


def test_task_output_follows_symlink_to_subagent_jsonl(tmp_path, monkeypatch):
    # 意図: Claude Code 側の仕様で .output が ~/.claude/projects/<proj>/<sid>/subagents/agent-<id>.jsonl
    # への symlink になった場合、 resolve 後の実体が subagent jsonl なら通す (= UID check は維持)。
    import backend.routes.files as files_routes
    # HOME を tmp_path に差し替えて、 実 HOME を汚さず「~/.claude/projects/.../subagents/agent-X.jsonl」 を作る
    fake_home = tmp_path / "home"
    projects = fake_home / ".claude" / "projects" / "-Users-x-proj" / "sid-abc"
    subagents = projects / "subagents"
    subagents.mkdir(parents=True)
    real_jsonl = subagents / "agent-a123.jsonl"
    real_jsonl.write_text('{"type":"user","message":{"content":"hi"}}\n')
    # /tmp 側 symlink source (= claude harness の output-file が指す先)
    tasks_dir = tmp_path / "claude-501" / "-Users-x-proj" / "sid-abc" / "tasks"
    tasks_dir.mkdir(parents=True)
    symlink_src = tasks_dir / "a123.output"
    symlink_src.symlink_to(real_jsonl)
    monkeypatch.setattr(files_routes, "HOME", fake_home)
    client = _task_output_client()
    res = client.get("/task-output", params={"path": str(symlink_src)})
    assert res.status_code == 200
    assert "hi" in res.json()["content"]


# --- /file/raw (= 画像プレビュー) ---

_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def _raw_client(tmp_path, monkeypatch):
    """HOME を tmp_path に差し替えた app の client (= HOME 配下判定を test 用の場所で行う)。"""
    from fastapi.testclient import TestClient  # noqa: PLC0415
    import backend.routes.files as files_mod  # noqa: PLC0415
    from backend.main import app  # noqa: PLC0415
    monkeypatch.setattr(files_mod, "HOME", tmp_path)
    return TestClient(app), files_mod


def test_file_raw_returns_image_bytes_with_its_type(tmp_path, monkeypatch):
    client, _ = _raw_client(tmp_path, monkeypatch)
    (tmp_path / "shot.PNG").write_bytes(_PNG_BYTES)
    res = client.get("/file/raw", params={"path": str(tmp_path / "shot.PNG")})
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.content == _PNG_BYTES


@pytest.mark.parametrize("name", ["logo.svg", "notes.txt", "noext"])
def test_file_raw_refuses_non_images_and_svg(tmp_path, monkeypatch, name):
    client, _ = _raw_client(tmp_path, monkeypatch)
    (tmp_path / name).write_text("<svg onload='alert(1)'/>")
    res = client.get("/file/raw", params={"path": str(tmp_path / name)})
    assert res.status_code == 415


def test_file_raw_keeps_the_home_and_deny_list_boundaries(tmp_path, monkeypatch):
    client, _ = _raw_client(tmp_path, monkeypatch)
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh" / "key.png").write_bytes(_PNG_BYTES)
    assert client.get("/file/raw", params={"path": str(tmp_path / ".ssh" / "key.png")}).status_code == 403
    assert client.get("/file/raw", params={"path": "/etc/hosts.png"}).status_code == 403


def test_file_raw_missing_and_too_large(tmp_path, monkeypatch):
    client, files_mod = _raw_client(tmp_path, monkeypatch)
    assert client.get("/file/raw", params={"path": str(tmp_path / "gone.png")}).status_code == 404
    monkeypatch.setattr(files_mod, "IMAGE_SIZE_LIMIT", 8)
    (tmp_path / "big.png").write_bytes(_PNG_BYTES)
    assert client.get("/file/raw", params={"path": str(tmp_path / "big.png")}).status_code == 413


# --- /file/open と /file/view (= HTML を隣の file ごとブラウザで開く) ---

def _site(tmp_path):
    """index.html と、 それが相対 path で読む画像とスクリプト (= 渡される図解の形)。"""
    site = tmp_path / "pages" / "deck"
    (site / "cam").mkdir(parents=True)
    (site / "index.html").write_text("<!doctype html><img src='cam/a.png'><script src='draw.js'></script>")
    (site / "cam" / "a.png").write_bytes(_PNG_BYTES)
    (site / "draw.js").write_text("var drawn = 1;")
    return site


def test_file_open_sends_a_tilde_path_to_the_view_of_its_absolute_path(tmp_path, monkeypatch):
    client, _ = _raw_client(tmp_path, monkeypatch)
    site = _site(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    res = client.get("/file/open", params={"path": "~/pages/deck/index.html"}, follow_redirects=False)
    assert res.status_code == 307
    assert res.headers["location"] == "view/" + str(site / "index.html").lstrip("/")
    page = client.get("/file/open", params={"path": str(site / "index.html")})
    assert page.status_code == 200
    assert page.headers["content-type"] == "text/html; charset=utf-8"


def test_file_view_serves_the_page_and_its_relative_files_all_sandboxed(tmp_path, monkeypatch):
    client, files_mod = _raw_client(tmp_path, monkeypatch)
    site = _site(tmp_path)
    base = "/file/view" + str(site)
    for rel, kind in [("index.html", "text/html; charset=utf-8"), ("cam/a.png", "image/png"),
                      ("draw.js", "text/javascript; charset=utf-8")]:
        res = client.get(f"{base}/{rel}")
        assert res.status_code == 200, rel
        assert res.headers["content-type"] == kind
        csp = res.headers["content-security-policy"]
        assert csp == files_mod.VIEW_CSP
        assert csp.startswith("sandbox allow-scripts;") and "allow-same-origin" not in csp
        assert "connect-src 'none'" in csp
        assert "frame-ancestors 'self'" in csp
        assert res.headers["x-content-type-options"] == "nosniff"


def test_file_view_keeps_the_home_and_deny_list_boundaries(tmp_path, monkeypatch):
    client, _ = _raw_client(tmp_path, monkeypatch)
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh" / "page.html").write_text("<p>x</p>")
    assert client.get("/file/view" + str(tmp_path / ".ssh" / "page.html")).status_code == 403
    assert client.get("/file/view/etc/hosts.html").status_code == 403
    assert client.get("/file/view" + str(tmp_path) + "/../../etc/x.html").status_code in (403, 404)
    assert client.get("/file/open", params={"path": "/etc/x.html"}).status_code == 403


@pytest.mark.parametrize("name", ["notes.rst", "run.sh", "noext", "data.bin"])
def test_file_view_refuses_types_it_does_not_serve(tmp_path, monkeypatch, name):
    client, _ = _raw_client(tmp_path, monkeypatch)
    (tmp_path / name).write_text("x")
    assert client.get("/file/view" + str(tmp_path / name)).status_code == 415


def test_file_open_takes_html_only(tmp_path, monkeypatch):
    client, _ = _raw_client(tmp_path, monkeypatch)
    (tmp_path / "pic.png").write_bytes(_PNG_BYTES)
    assert client.get("/file/open", params={"path": str(tmp_path / "pic.png")}).status_code == 415
    assert client.get("/file/open", params={"path": str(tmp_path / "missing.html")}).status_code == 404


# --- ページの origin (= config の page_origin の folder を、 sandbox を外して別の port から配る) ---

_PAGE_PORT = 8799


def _with_config(monkeypatch, cfg):
    """backend の設定を cfg にする (= 仮の config.json を書いて読ませる)。"""
    import json  # noqa: PLC0415
    import tempfile  # noqa: PLC0415
    import backend.config as config_mod  # noqa: PLC0415
    path = pathlib.Path(tempfile.mkdtemp(prefix="cpc-page-origin-")) / "config.json"
    path.write_text(json.dumps(cfg))
    monkeypatch.setattr(config_mod, "CONFIG_PATH", path)
    config_mod.get_config.cache_clear()


def _with_page_origin(monkeypatch, folder, port=_PAGE_PORT, listening=True):
    import backend.routes.files as files_mod  # noqa: PLC0415
    _with_config(monkeypatch, {"page_origin": {"folder": str(folder), "port": port}})
    monkeypatch.setattr(files_mod, "page_listening", listening)


def test_file_open_sends_a_page_in_the_folder_to_its_own_port(tmp_path, monkeypatch):
    client, _ = _raw_client(tmp_path, monkeypatch)
    site = _site(tmp_path)
    _with_page_origin(monkeypatch, tmp_path / "pages")
    res = client.get("/file/open", params={"path": str(site / "index.html")}, follow_redirects=False)
    assert res.status_code == 307
    assert res.headers["location"] == f"http://testserver:{_PAGE_PORT}/deck/index.html"
    # host は要求の物 (= Tailscale の名前で開けば、 別の port もその名前で開く。 scheme は test_main_page_server)
    named = client.get("/file/open", params={"path": str(site / "index.html")}, follow_redirects=False,
                       headers={"host": "box.example.ts.net"})
    assert named.headers["location"] == f"http://box.example.ts.net:{_PAGE_PORT}/deck/index.html"
    v6 = client.get("/file/open", params={"path": str(site / "index.html")}, follow_redirects=False,
                    headers={"host": "[::1]:8765"})
    assert v6.headers["location"] == f"http://[::1]:{_PAGE_PORT}/deck/index.html"


def test_file_open_keeps_pages_outside_the_folder_on_the_sandboxed_view(tmp_path, monkeypatch):
    client, _ = _raw_client(tmp_path, monkeypatch)
    site = _site(tmp_path)
    (tmp_path / "other").mkdir()
    _with_page_origin(monkeypatch, tmp_path / "other")
    res = client.get("/file/open", params={"path": str(site / "index.html")}, follow_redirects=False)
    assert res.headers["location"] == "view/" + str(site / "index.html").lstrip("/")


def test_file_open_keeps_the_sandboxed_view_while_the_port_is_not_listening(tmp_path, monkeypatch):
    # 意図: 待ち受けを開けなかった時 (= port が塞がっている) は、 folder の中のページも開ける口へ回す
    client, _ = _raw_client(tmp_path, monkeypatch)
    site = _site(tmp_path)
    _with_page_origin(monkeypatch, tmp_path / "pages", listening=False)
    res = client.get("/file/open", params={"path": str(site / "index.html")}, follow_redirects=False)
    assert res.headers["location"] == "view/" + str(site / "index.html").lstrip("/")


def _page_client(tmp_path, monkeypatch, folder):
    from fastapi.testclient import TestClient  # noqa: PLC0415
    import backend.routes.files as files_mod  # noqa: PLC0415
    monkeypatch.setattr(files_mod, "HOME", tmp_path)
    monkeypatch.setattr(files_mod, "PAGE_STORE_DIR", tmp_path / "store")
    _with_page_origin(monkeypatch, folder)
    return TestClient(files_mod.page_app), files_mod


def test_page_origin_serves_the_page_and_its_relative_files_on_an_origin_of_its_own_that_cannot_move_the_top_screen(tmp_path, monkeypatch):
    site = _site(tmp_path)
    client, files_mod = _page_client(tmp_path, monkeypatch, tmp_path / "pages")
    for rel, kind in [("deck/index.html", "text/html; charset=utf-8"), ("deck/cam/a.png", "image/png"),
                      ("deck/draw.js", "text/javascript; charset=utf-8")]:
        res = client.get(f"/{rel}")
        assert res.status_code == 200, rel
        assert res.headers["content-type"] == kind
        csp = res.headers["content-security-policy"]
        # backend と別の origin のまま (= allow-same-origin。 localStorage が残る) で、 上の画面を別の頁へ移す権限だけ渡さない
        assert files_mod._PAGE_SANDBOX in csp and "allow-same-origin" in csp
        assert "allow-top-navigation" not in csp
        assert csp.startswith(files_mod._PAGE_POLICY)
        assert "form-action 'none'" in csp
        assert f"connect-src http://testserver:{_PAGE_PORT}/.store/;" in csp
        assert csp.endswith("frame-ancestors http://testserver:*")
        assert res.headers["x-content-type-options"] == "nosniff"
    assert client.get("/deck/cam/a.png").content == (site / "cam" / "a.png").read_bytes()


def test_page_origin_keeps_the_folder_and_deny_list_boundaries(tmp_path, monkeypatch):
    _site(tmp_path)
    (tmp_path / "outside.html").write_text("<p>x</p>")
    (tmp_path / "pages" / ".ssh").mkdir()
    (tmp_path / "pages" / ".ssh" / "page.html").write_text("<p>x</p>")
    (tmp_path / "pages" / "link.html").symlink_to(tmp_path / "outside.html")
    client, _ = _page_client(tmp_path, monkeypatch, tmp_path / "pages")
    assert client.get("/../outside.html").status_code in (403, 404)
    assert client.get("/%2E%2E/outside.html").status_code in (403, 404)
    assert client.get("/link.html").status_code == 403
    assert client.get("/.ssh/page.html").status_code == 403
    assert client.get("/deck/run.sh").status_code == 415
    assert client.get("/deck/gone.html").status_code == 404


def test_page_origin_serves_nothing_without_the_setting(tmp_path, monkeypatch):
    _site(tmp_path)
    client, _ = _page_client(tmp_path, monkeypatch, tmp_path / "pages")
    _with_config(monkeypatch, {})
    assert client.get("/deck/index.html").status_code == 404


@pytest.mark.parametrize("raw, problem", [
    ("~/pages", "must be an object"),
    ({"port": 8799}, "folder must be a path"),
    ({"folder": "~", "port": "8799"}, "port must be a port number"),
    ({"folder": "~", "port": True}, "port must be a port number"),
    ({"folder": "~", "port": 70000}, "port must be a port number"),
    ({"folder": "/no/such/folder", "port": 8799}, "is not a directory"),
])
def test_page_origin_setting_mistakes_are_reported_and_ignored(monkeypatch, raw, problem):
    import backend.config as config_mod  # noqa: PLC0415
    _with_config(monkeypatch, {"page_origin": raw})
    value, problems = config_mod._scan_page_origin()
    assert value is None
    assert len(problems) == 1 and problem in problems[0]


def test_page_origin_setting_resolves_the_folder(tmp_path, monkeypatch):
    (tmp_path / "real").mkdir()
    (tmp_path / "alias").symlink_to(tmp_path / "real")
    import backend.config as config_mod  # noqa: PLC0415
    _with_page_origin(monkeypatch, tmp_path / "alias")
    assert config_mod.page_origin() == ((tmp_path / "real").resolve(), _PAGE_PORT)
    _with_config(monkeypatch, {})
    assert config_mod.page_origin() is None


# --- 保存箱 (= ページの origin の `/.store/<ページの path>`) ---

_JSON = {"content-type": "application/json"}


def test_page_store_starts_empty_and_keeps_what_a_page_puts(tmp_path, monkeypatch):
    _site(tmp_path)
    client, _ = _page_client(tmp_path, monkeypatch, tmp_path / "pages")
    empty = client.get("/.store/deck/index.html")
    assert empty.status_code == 200 and empty.json() is None
    assert empty.headers["cache-control"] == "no-store"
    put = client.put("/.store/deck/index.html", content=b'{"done": [1, 3]}', headers=_JSON)
    assert put.status_code == 204
    got = client.get("/.store/deck/index.html")
    assert got.json() == {"done": [1, 3]}
    assert got.headers["etag"] == put.headers["etag"] != empty.headers["etag"]


def test_page_store_is_one_per_page(tmp_path, monkeypatch):
    # 意図: 箱はページの実体ごと (= 別のページは別の箱、 symlink で同じページを指す path は同じ箱)
    site = _site(tmp_path)
    (site / "map.html").write_text("<p>map</p>")
    (site / "alias.html").symlink_to(site / "map.html")
    client, _ = _page_client(tmp_path, monkeypatch, tmp_path / "pages")
    client.put("/.store/deck/map.html", content=b'{"page": "map"}', headers=_JSON)
    assert client.get("/.store/deck/index.html").json() is None
    assert client.get("/.store/deck/alias.html").json() == {"page": "map"}


def test_page_store_refuses_a_write_over_one_it_has_not_read(tmp_path, monkeypatch):
    # 意図: If-Match が今の ETag と違えば (= 別の画面が先に書いた) 書かずに 412 と今の中身を返す
    _site(tmp_path)
    client, _ = _page_client(tmp_path, monkeypatch, tmp_path / "pages")
    seen = client.get("/.store/deck/index.html").headers["etag"]
    first = client.put("/.store/deck/index.html", content=b'{"by": "phone"}', headers={**_JSON, "if-match": seen})
    assert first.status_code == 204
    stale = client.put("/.store/deck/index.html", content=b'{"by": "mac"}', headers={**_JSON, "if-match": seen})
    assert stale.status_code == 412
    assert stale.json() == {"by": "phone"} and stale.headers["etag"] == first.headers["etag"]
    again = client.put("/.store/deck/index.html", content=b'{"by": "mac"}',
                       headers={**_JSON, "if-match": stale.headers["etag"]})
    assert again.status_code == 204
    assert client.get("/.store/deck/index.html").json() == {"by": "mac"}


def test_page_store_takes_json_only_and_up_to_the_limit(tmp_path, monkeypatch):
    _site(tmp_path)
    client, files_mod = _page_client(tmp_path, monkeypatch, tmp_path / "pages")
    url = "/.store/deck/index.html"
    assert client.put(url, content=b'{"a": 1}', headers={"content-type": "text/plain"}).status_code == 415
    assert client.put(url, content=b"not json", headers=_JSON).status_code == 400
    monkeypatch.setattr(files_mod, "FILE_SIZE_LIMIT", 16)
    assert client.put(url, content=b'{"a": "' + b"x" * 20 + b'"}', headers=_JSON).status_code == 413
    assert client.put(url, content=b'{"a": 1}', headers=_JSON).status_code == 204
    assert client.get(url).json() == {"a": 1}


def test_page_store_is_only_for_pages_in_the_folder(tmp_path, monkeypatch):
    _site(tmp_path)
    (tmp_path / "outside.html").write_text("<p>x</p>")
    (tmp_path / "pages" / ".ssh").mkdir()
    (tmp_path / "pages" / ".ssh" / "page.html").write_text("<p>x</p>")
    client, _ = _page_client(tmp_path, monkeypatch, tmp_path / "pages")
    for page, status in [("deck/cam/a.png", 404), ("deck/draw.js", 404), ("deck/gone.html", 404),
                         ("%2E%2E/outside.html", 403), (".ssh/page.html", 403)]:
        assert client.get("/.store/" + page).status_code == status, page
        assert client.put("/.store/" + page, content=b"{}", headers=_JSON).status_code == status, page
    assert not (tmp_path / "store").exists()
