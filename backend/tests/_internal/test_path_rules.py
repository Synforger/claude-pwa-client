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
