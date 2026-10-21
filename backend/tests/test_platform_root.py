"""器の根 (`AGENT_PLATFORM_ROOT`) の置き場の決め方。

paths は import 時に決まるので、 どの確認も別 process で行う。 根を渡さない確認は repo の写し (paths.py と
config.py だけの作り物の repo) を使う (= 本物の repo に data/ や logs/ を作らない)。
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROBE = REPO_ROOT / "backend" / "tests" / "platform_root_probe.py"
TOOL = "claude-pwa-client"

# paths と config が決めた置き場を JSON で出す
SHOW = """
import json
import backend.paths as paths
from backend.config import RATE_LIMITS_LOG_PATH, UPLOADS_TMP, documents_settings
print(json.dumps({
    "data": str(paths.DATA_DIR), "logs": str(paths.LOGS_DIR), "secrets": str(paths.SECRETS_DIR),
    "config": str(paths.CONFIG_PATH), "favorites": str(paths.FAVORITES_PATH), "notes": str(paths.NOTES_DIR),
    "page_store": str(paths.PAGE_STORE_DIR), "backups": str(paths.BACKUPS_DIR), "uploads": str(UPLOADS_TMP),
    "document_cache": str(documents_settings()[0]), "rate_limits_log": RATE_LIMITS_LOG_PATH,
}))
"""


@pytest.fixture
def sandbox(tmp_path):
    """paths.py と config.py だけを写した作り物の repo と、 作り物の HOME。"""
    repo, home = tmp_path / "repo", tmp_path / "home"
    (repo / "backend").mkdir(parents=True)
    home.mkdir()
    for name in ("__init__.py", "paths.py", "config.py"):
        shutil.copy(REPO_ROOT / "backend" / name, repo / "backend" / name)
    return repo.resolve(), home.resolve()


def run_show(repo: Path, home: Path, **env: str) -> dict[str, str]:
    """作り物の repo で SHOW を回す。 環境は PATH と HOME と `env` だけ (= CPC_* と器の根は `env` で渡した物だけ)。"""
    done = subprocess.run(
        [sys.executable, "-c", SHOW], cwd=repo, capture_output=True, text=True, timeout=60,
        env={"PATH": os.environ["PATH"], "HOME": str(home), "PYTHONPATH": str(repo), "PYTHONDONTWRITEBYTECODE": "1", **env},
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_without_a_root_every_place_is_where_it_was(sandbox):
    repo, home = sandbox
    user = home / ".claude-pwa-client"
    assert run_show(repo, home) == {
        "data": str(repo / "backend" / "data"),
        "logs": str(repo / "logs"),
        "secrets": str(repo / "backend" / "secrets"),
        "config": str(repo / "backend" / "config.json"),
        "favorites": str(user / "favorites.txt"),
        "notes": str(user / "notes"),
        "page_store": str(user / "page-store"),
        "backups": str(user / "backups"),
        "uploads": str(user / "uploads" / "tmp"),
        "document_cache": str(user / "document-cache"),
        "rate_limits_log": "",
    }


def test_a_root_places_each_thing_under_its_role(sandbox, tmp_path):
    repo, home = sandbox
    root = tmp_path / "root"
    state, config = root / "state" / TOOL, root / "config" / TOOL
    assert run_show(repo, home, AGENT_PLATFORM_ROOT=str(root)) == {
        "data": str(state / "data"),
        "logs": str(state / "logs"),
        "secrets": str(root / "secrets" / TOOL),
        "config": str(config / "config.json"),
        "favorites": str(config / "favorites.txt"),
        "notes": str(state / "notes"),
        "page_store": str(state / "page-store"),
        "backups": str(state / "backups"),
        "uploads": str(state / "uploads"),
        "document_cache": str(root / "cache" / TOOL / "document-cache"),
        "rate_limits_log": str(root / "state" / "statusline" / "rate-limits.jsonl"),
    }


def test_a_specific_variable_beats_the_root(sandbox, tmp_path):
    repo, home = sandbox
    root, elsewhere = tmp_path / "root", tmp_path / "elsewhere"
    placed = run_show(
        repo, home, AGENT_PLATFORM_ROOT=str(root),
        CPC_DATA_DIR=str(elsewhere / "data"), CPC_LOGS_DIR=str(elsewhere / "logs"),
        CPC_SECRETS_DIR=str(elsewhere / "secrets"), CPC_CONFIG_PATH=str(elsewhere / "config.json"),
        CPC_USER_DIR=str(elsewhere / "user"),
    )
    assert placed["data"] == str(elsewhere / "data")
    assert placed["logs"] == str(elsewhere / "logs")
    assert placed["secrets"] == str(elsewhere / "secrets")
    assert placed["config"] == str(elsewhere / "config.json")
    for key, name in [("favorites", "favorites.txt"), ("notes", "notes"), ("page_store", "page-store"),
                      ("backups", "backups"), ("document_cache", "document-cache"), ("uploads", "uploads/tmp")]:
        assert placed[key] == str(elsewhere / "user" / name), key


def test_the_config_file_beats_the_root_for_the_places_it_names(sandbox, tmp_path):
    repo, home = sandbox
    root = tmp_path / "root"
    config = root / "config" / TOOL / "config.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({
        "uploads_tmp": str(tmp_path / "up"), "rate_limits_log": str(tmp_path / "rate.jsonl"),
        "documents": {"cache_dir": str(tmp_path / "docs")},
    }))
    placed = run_show(repo, home, AGENT_PLATFORM_ROOT=str(root))
    assert placed["uploads"] == str(tmp_path / "up")
    assert placed["rate_limits_log"] == str(tmp_path / "rate.jsonl")
    assert placed["document_cache"] == str((tmp_path / "docs").resolve())


def test_the_tab_gets_the_root_only_when_the_backend_has_one(monkeypatch, tmp_path):
    from backend.terminal import runner  # noqa: PLC0415
    monkeypatch.setattr(runner, "PLATFORM_ROOT", None)
    assert not any(a.startswith("AGENT_PLATFORM_ROOT=") for a in runner.tmux_session_env_args("ses_abc", None))

    monkeypatch.setattr(runner, "PLATFORM_ROOT", tmp_path)
    args = runner.tmux_session_env_args("ses_abc", {"AGENT_PLATFORM_ROOT": "/spoof", "OTHER": "1"})
    assert ["-e", f"AGENT_PLATFORM_ROOT={tmp_path}"] == args[6:8]
    assert "AGENT_PLATFORM_ROOT=/spoof" not in args and args[-2:] == ["-e", "OTHER=1"]


def tree(folder: Path) -> set[str]:
    return {str(p.relative_to(folder)) for p in folder.rglob("*")}


def repo_files() -> set[str]:
    """repo の file の一覧 (= 環境と履歴と node の置き場は除く)。"""
    found = set()
    for here, folders, files in os.walk(REPO_ROOT):
        folders[:] = [f for f in folders if f not in {".git", ".venv", "node_modules"}]
        found.update(str(Path(here, f).relative_to(REPO_ROOT)) for f in files)
    return found


def run_probe(home: Path, scratch: Path, **env: str) -> dict:
    """根を HOME の下に置いて probe を回し、 その JSON を返す。 器は HOME の下に在る (= ページの口は HOME の外の file を開かない)。"""
    done = subprocess.run(
        [sys.executable, str(PROBE)], cwd=REPO_ROOT, capture_output=True, text=True, timeout=180,
        env={"PATH": os.environ["PATH"], "HOME": str(home), "TMPDIR": str(scratch), "PYTHONPATH": str(REPO_ROOT),
             "PYTHONDONTWRITEBYTECODE": "1", "AGENT_PLATFORM_ROOT": str(home / "agent-platform"), **env},
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


@pytest.fixture
def houses(tmp_path):
    home, scratch = tmp_path / "home", tmp_path / "tmp"
    (home / "agent-platform").mkdir(parents=True)
    scratch.mkdir()
    return home, scratch


def test_nothing_is_written_outside_the_root(houses):
    home, scratch = houses
    root = home / "agent-platform"
    before = repo_files()
    result = run_probe(home, scratch)

    assert result["outside"] == []
    assert {name for name in tree(home) if not name.startswith("agent-platform")} == set()
    assert tree(scratch) == set()
    assert repo_files() == before
    for key, place in result["placed"].items():
        if key != "rate_limits_log":
            assert Path(place).resolve().is_relative_to(root.resolve()), (key, place)
    tool_state, tool_config = root / "state" / TOOL, root / "config" / TOOL
    for written in (tool_config / "favorites.txt", tool_config / "config.json", root / "secrets" / TOOL / "vapid.json",
                    tool_state / "data" / "session_meta.json", tool_state / "data" / "subscriptions.json",
                    tool_state / "data" / "session_history.json", tool_state / "logs" / "backend.error.log"):
        assert written.is_file(), written
    assert any((tool_state / "page-store").glob("*.json"))
    assert any((tool_state / "notes").glob("*.md"))
    assert any((tool_state / "uploads").glob("*.txt"))


def test_the_count_sees_a_write_outside_the_root(houses):
    home, scratch = houses
    stray = home / "stray"
    result = run_probe(home, scratch, PROBE_STRAY=str(stray))
    assert [line.split(" ", 1)[0] for line in result["outside"]] == ["os.mkdir", "open"]
    assert all(str(stray) in line for line in result["outside"])


def test_setup_puts_the_config_example_where_the_root_says(tmp_path):
    root, home = tmp_path / "root", tmp_path / "home"
    home.mkdir()
    env = {"PATH": os.environ["PATH"], "HOME": str(home), "PYTHONPATH": str(REPO_ROOT),
           "PYTHONDONTWRITEBYTECODE": "1", "AGENT_PLATFORM_ROOT": str(root)}
    run = [sys.executable, "-m", "backend.cli.init_config"]
    first = subprocess.run(run, cwd=REPO_ROOT, capture_output=True, text=True, timeout=60, env=env)
    config = root / "config" / TOOL / "config.json"
    assert first.returncode == 0 and "created" in first.stdout, first.stderr
    assert config.read_text() == (REPO_ROOT / "backend" / "config.example.json").read_text()
    config.write_text("{}")
    second = subprocess.run(run, cwd=REPO_ROOT, capture_output=True, text=True, timeout=60, env=env)
    assert "skip" in second.stdout and config.read_text() == "{}"
    assert tree(home) == set()
