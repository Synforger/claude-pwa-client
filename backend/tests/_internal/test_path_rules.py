"""Tests of `backend/_internal/path_rules.py` and of the `/file` door that uses it."""
from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend._internal import path_rules
from backend._internal.path_rules import is_denied

ON_MACOS = sys.platform == "darwin"


@pytest.mark.parametrize("path", [
    "/home/u/.ssh/id_rsa",
    "/home/u/.SSH/config",
    "/home/u/.Aws/credentials",
    "/home/u/Library/KEYCHAINS/login.keychain-db",
    "/home/u/.ZshRC",
    "/home/u/app/.ENV",
    "/home/u/app/.Env.Production",
    "/home/u/app/Secrets/token.txt",
    "/home/u/app/SECRETS",
    "/home/u/.config/GH/hosts.yml",
], ids=lambda _: "path")
def test_the_rules_refuse_listed_names(path):
    assert is_denied(Path(path))


@pytest.mark.parametrize("path", [
    "/home/u/.s\u017fh/id_rsa",
    "/home/u/app/\u017fecrets/token.txt",
    "/home/u/.\u017fsh",
    "/home/u/.z\u017fhrc",
], ids=lambda _: "path")
def test_the_rules_refuse_listed_names_normalised(path):
    assert is_denied(Path(path))


@pytest.mark.parametrize("path", [
    "/home/u/cert.PEM",
    "/home/u/server.Key",
    "/home/u/bundle.P12",
    "/home/u/bundle.PFX",
], ids=lambda _: "path")
def test_the_rules_refuse_listed_extensions(path):
    assert is_denied(Path(path))


def test_the_rules_refuse_a_path_to_be_created(tmp_path):
    assert is_denied(tmp_path / ".SSH" / "new_key")
    assert is_denied(tmp_path / "app" / ".Zshrc")


def test_the_rules_refuse_a_normalised_path():
    decomposed = unicodedata.normalize("NFD", "/home/u/app/secrets/é.txt")
    assert is_denied(Path(decomposed))


@pytest.mark.parametrize("path", [
    "/home/u/notes/todo.md",
    "/home/u/repos/app/src/main.py",
    "/home/u/app/secrets-notes.md",
    "/home/u/app/my-secrets.txt",
    "/home/u/app/.envelope",
    "/home/u/app/.env.example",
    "/home/u/app/.ENV.SAMPLE",
    "/home/u/app/.env.template",
    "/home/u/app/keyboard.txt",
    "/home/u/.config/other/settings.json",
], ids=lambda _: "path")
def test_an_ordinary_path_or_a_similar_name_passes(path):
    assert not is_denied(Path(path))


@pytest.mark.parametrize("form", ["NFC", "NFD"])
def test_a_japanese_name_passes_in_both_forms(form):
    name = unicodedata.normalize(form, "/home/u/メモ/がぎぐ/ぱぴぷ.md")
    assert not is_denied(Path(name))


def test_the_rules_read_the_file_system_name(monkeypatch):
    monkeypatch.setattr(path_rules, "_filesystem_name", lambda path: "/home/u/.ssh/id")
    assert is_denied(Path("/home/u/harmless/id"))


def test_a_file_system_name_that_is_clean_does_not_refuse(monkeypatch):
    monkeypatch.setattr(path_rules, "_filesystem_name", lambda path: "/home/u/harmless/id")
    assert not is_denied(Path("/home/u/harmless/id"))


def test_the_rules_decide_without_a_file_system_name(monkeypatch):
    monkeypatch.setattr(path_rules, "_filesystem_name", lambda path: None)
    assert is_denied(Path("/home/u/.SSH/id"))
    assert not is_denied(Path("/home/u/harmless/id"))


@pytest.mark.skipif(not ON_MACOS, reason="the file system's own name comes from F_GETPATH")
def test_the_file_system_name_of_a_real_path_keeps_the_names_on_disk(tmp_path):
    (tmp_path / "secrets").mkdir()
    asked = tmp_path / "SECRETS" / "not-yet.txt"
    reported = path_rules._filesystem_name(asked)
    assert reported is not None
    assert reported.endswith("/secrets/not-yet.txt")


@pytest.mark.skipif(not ON_MACOS, reason="the file system's own name comes from F_GETPATH")
def test_the_rules_refuse_a_real_folder(tmp_path):
    (tmp_path / ".ssh").mkdir()
    assert is_denied(tmp_path / ".ssh" / "new_key")
    assert is_denied((tmp_path / ".SSH" / "new_key"))


@pytest.mark.skipif(not ON_MACOS, reason="the file system's own name comes from F_GETPATH")
def test_the_file_system_name_closes_the_descriptors_it_opens(tmp_path):
    (tmp_path / "a").mkdir()
    before = len(list(Path("/dev/fd").iterdir()))
    for _ in range(20):
        path_rules._filesystem_name(tmp_path / "a" / "b" / "c")
    assert len(list(Path("/dev/fd").iterdir())) == before


@pytest.fixture
def client(tmp_path, monkeypatch):
    import backend.routes.files as files_mod  # noqa: PLC0415
    from backend.main import app  # noqa: PLC0415
    monkeypatch.setattr(files_mod, "HOME", tmp_path.resolve())
    return TestClient(app)


def test_the_file_route_refuses_a_listed_read(client, tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / ".env").write_text("TOKEN=1")
    res = client.get("/file", params={"path": str(tmp_path / "app" / ".ENV")})
    assert res.status_code == 403
    res = client.get("/file", params={"path": str(tmp_path / "app" / ".env")})
    assert res.status_code == 403


def test_the_file_route_refuses_a_listed_write(client, tmp_path):
    res = client.put("/file", json={"path": str(tmp_path / ".SSH" / "new_key"), "content": "x"})
    assert res.status_code == 403
    assert not (tmp_path / ".SSH").exists()


def test_the_file_door_still_reads_and_writes_an_ordinary_file(client, tmp_path):
    target = tmp_path / "notes-secrets.md"
    res = client.put("/file", json={"path": str(target), "content": "hello"})
    assert res.status_code == 200
    res = client.get("/file", params={"path": str(target)})
    assert res.status_code == 200
    assert res.json()["content"] == "hello"


@pytest.mark.parametrize("path", [
    "/home/u/.netrc.bak",
    "/home/u/.claude.json.backup",
    "/home/u/.claude.json.tmp.12",
    "/home/u/.claude-x/backups/any-name",
    "/home/u/.claude-x/backups/.claude.json.backup.12",
    "/home/u/.claude-backup-x/projects/a/b.jsonl",
    "/home/u/.bashrc~",
    "/home/u/.zshrc.bak-20200101",
    "/home/u/keep/zshrc.before-change",
    "/home/u/keep/copy____zshrc",
    "/home/u/keep/one-claude.json.before-change",
    "/home/u/app/.env-local",
    "/home/u/app/.env~",
    "/home/u/app/env.bak",
    "/home/u/.ssh.bak/config",
    "/home/u/.credentials.json.old",
    "/home/u/app/credentials.toml",
    "/home/u/app/credentials",
    "/home/u/app/credentials.json.bak",
    "/home/u/app/secrets.toml",
    "/home/u/app/_secrets/token.txt",
    "/home/u/app/secrets_/token.txt",
    "/home/u/app/.secrets",
    "/home/u/app/secrets.bak/token.txt",
    "/home/u/keep/id_rsa.old",
    "/home/u/cert.pem.bak",
    "/home/u/server.key~",
], ids=lambda _: "path")
def test_the_rules_refuse_the_related_names(path):
    assert is_denied(Path(path))


@pytest.mark.parametrize("path", [
    "/home/u/app/.env.example",
    "/home/u/app/.env-template",
    "/home/u/app/.npmrc.example",
    "/home/u/app/secrets.example.toml",
    "/home/u/app/secrets-notes.md",
    "/home/u/app/my_secrets_manager.py",
    "/home/u/app/env.hpp",
    "/home/u/app/credentials.dart",
    "/home/u/app/credentials_test.py",
    "/home/u/sdk/credentials/__init__.py",
    "/home/u/app/.dockerignore",
    "/home/u/app/.profiles",
    "/home/u/app/id_rsa.pub",
    "/home/u/app/i18n.key.ts",
    "/home/u/app/notes.backup.md",
    "/home/u/.claude/projects/a/b.jsonl",
    "/home/u/backups/photo.png",
], ids=lambda _: "path")
def test_the_rules_pass_the_ordinary_names(path):
    assert not is_denied(Path(path))


@pytest.mark.parametrize("path", [
    "/home/u/.zlogin",
    "/home/u/.ZLogout",
    "/home/u/dots/.bash_login",
    "/home/u/.bash_logout",
    "/home/u/.tcshrc",
    "/home/u/.cshrc",
    "/home/u/.login",
    "/home/u/.xonshrc",
    "/home/u/.config/xonsh/rc.xsh",
    "/home/u/.zlogin.zwc",
    "/home/u/Library/LaunchAgents/com.example.sample.plist",
    "/home/u/repo/.git/hooks/pre-commit",
    "/home/u/repo.git/hooks/update",
    "/home/u/repo/.git/modules/sub/hooks/post-checkout",
    "/home/u/repo/.githooks/pre-push",
    "/home/u/repo/.githooks/lib/shared",
    "/home/u/.git-hooks/pre-commit",
    "/home/u/.config/git/hooks/pre-commit",
    "/home/u/repo/.husky/pre-commit",
    "/home/u/repo/.claude/hooks/check",
    "/home/u/.local/bin/sample",
    "/home/u/bin/sample",
    "/home/u/app/node_modules/.bin/sample",
    "/home/u/envs/x/bin/python3.11",
    "/home/u/.local/share/mise/shims/sample",
], ids=lambda _: "path")
def test_the_write_rules_refuse_their_names(path):
    assert path_rules.is_write_denied(Path(path))
    assert not is_denied(Path(path))    # reading them is as before


@pytest.mark.parametrize("path", [
    "/home/u/notes/memo.md",
    "/home/u/app/login.py",
    "/home/u/app/logins",
    "/home/u/app/hooks/useThing.js",
    "/home/u/app/src/hooks/README",
    "/home/u/repo/.githooks/check.sh",
    "/home/u/repo/.claude/hooks/check.py",
    "/home/u/repo/bin/run.sh",
    "/home/u/app/cabin/notes",
    "/home/u/Documents/com.example.sample.plist",
    "/home/u/.gitconfig",
    "/home/u/.tmux.conf",
    "/home/u/.config/fish/config.fish",
    "/home/u/.claude/settings.json",
    "/home/u/repo/Makefile",
    "/home/u/repo/bin/Makefile",
], ids=lambda _: "path")
def test_the_write_rules_pass_the_other_names(path):
    assert not path_rules.is_write_denied(Path(path))


def test_the_write_rules_hold_what_the_rules_refuse():
    assert path_rules.is_write_denied(Path("/home/u/.zshrc"))


def test_the_file_route_refuses_only_the_write_of_those_names(client, tmp_path):
    target = tmp_path / "bin" / "sample"
    target.parent.mkdir()
    target.write_text("as before\n")
    assert client.get("/file", params={"path": str(target)}).status_code == 200
    res = client.put("/file", json={"path": str(target), "content": "x"})
    assert res.status_code == 403
    assert target.read_text() == "as before\n"


@pytest.mark.skipif(not ON_MACOS, reason="the file system's own name is read on macOS")
def test_the_write_rules_follow_the_file_system_s_name(tmp_path):
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "sample").write_text("x")
    (tmp_path / "tools").symlink_to(tmp_path / "bin")
    assert path_rules.is_write_denied(tmp_path / "tools" / "sample")
