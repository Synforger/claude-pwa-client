"""files_routes.py の _resolve_safe (= path injection 防御) の unit test。"""
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
])
def test_resolve_safe_denies_secret_paths(path):
    # 意図: SSH 鍵 / クラウド認証 / シェル rc / 履歴 / 証明書 は 403 で拒否される
    with pytest.raises(HTTPException) as exc_info:
        _resolve_safe(path)
    assert exc_info.value.status_code == 403


def test_resolve_safe_allows_ordinary_paths():
    # 意図: deny list に当たらない通常 path は通過する
    p = _resolve_safe(str(HOME / "repos" / "myproj" / "README.md"))
    assert str(p).endswith("README.md")


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
