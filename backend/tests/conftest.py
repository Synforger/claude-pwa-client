"""pytest 共通 setup。

- repo root を sys.path に注入することで、 test ファイル側で
  `from backend.core.usage import _parse_reset` のように backend package
  経由で import できるようにする。
- `isolated_state` fixture: state.py の module-level dict を test 内で安全に
  mutate するための snapshot / restore 仕組み。 第一弾の pure 関数 test では
  実質出番ないが、 register_session 等 global state を触る test 群で必須になる。
"""
import copy
import json
import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))


# --- minimum config fixture (= test では本物の backend/config.json を使わない) ---
# 2026-06-21 (finding backend-F-36): config.py の遅延化に伴い、 test では
# CONFIG_PATH を仮 file に向けて `get_config()` の lru_cache を毎 test 初期化する。
# これで個人 worktree / CI / sub-agent worktree でも本物の設定無しに collection
# が通る (= 旧版は import 時 open で全 test が落ちていた)。
_TEST_CONFIG = {
    "agents": {
        "agent_a": {
            "cwd": str(pathlib.Path.home()),
            "model": "Opus",
            "display_name": "Agent A",
            "launch_alias": "agent_a",
        },
    },
    "accounts": {"personal": {"display_name": "個人", "env": {}}},
    "claude_path": "/usr/bin/true",
    "cors_allow_origins": [],
}


@pytest.fixture(autouse=True)
def _stub_config(monkeypatch, tmp_path_factory):
    """全 test に minimum config を注入する。 個別 test が独自値を必要とする
    場合は `monkeypatch.setattr(backend.config, "get_config", lambda: {...})` で
    上書きする (= autouse 後に local fixture が走るので問題なし)。"""
    cfg_dir = tmp_path_factory.mktemp("backend_config")
    cfg_path = cfg_dir / "config.json"
    cfg_path.write_text(json.dumps(_TEST_CONFIG))
    import backend.config as config_mod

    monkeypatch.setattr(config_mod, "CONFIG_PATH", cfg_path)
    config_mod.get_config.cache_clear()
    yield
    config_mod.get_config.cache_clear()


# state.py の module-level に存在する dict 群。
_STATE_GLOBALS = (
    "agent_status",
    "shared_status",
    "sessions_meta",
    "stream_states",
)


@pytest.fixture
def isolated_state(monkeypatch, tmp_path):
    """state.py の global dict を deepcopy で snapshot → test 退場時に復元。
    test 間で global state が漏れて偽の pass/fail を起こさないための保険。

    あわせて永続化先 SESSION_META_PATH を tmp_path に飛ばす。 個別 test の
    monkeypatch では救えないケース (= chat_routes 側が `from backend.state import
    save_sessions_meta` で bind した参照を呼ぶと state 属性差し替えを素通りする)
    があり、 実機 backend/session_meta.json に test 用の "Chat" / "Chat fork" が
    書き込まれて UI ドロワーにゴーストタブが残る事故が起きた (2026-06-04 観測)。
    永続化先そのものを tmp に向けることで bind 経路に関係なく実機を汚さない。"""
    from backend import state

    monkeypatch.setattr(state, "SESSION_META_PATH", tmp_path / "session_meta.json")
    snapshots = {name: copy.deepcopy(getattr(state, name)) for name in _STATE_GLOBALS}
    yield state
    for name, snap in snapshots.items():
        live = getattr(state, name)
        live.clear()
        live.update(snap)
