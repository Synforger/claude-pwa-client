"""器の根 (`AGENT_PLATFORM_ROOT`) を渡した backend の書き込み口を一通り動かし、 根の外への書き込みを数えて JSON で出す。

`test_platform_root.py` が、 作り物の根と作り物の HOME・TMPDIR を渡した別 process として起動する
(= paths は import 時に決まるので、 試験の process の中では切り替えられない)。 書き込みは Python の
audit hook で全部拾う (= 開く・作る・消す・名前を変える・権限を変える)。
"""
import asyncio
import io
import json
import os
import sys
from pathlib import Path

ROOT = Path(os.environ["AGENT_PLATFORM_ROOT"]).resolve()
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
# 1 つ目の引数が path の、 書き換えの event
PATH_EVENTS = {"os.mkdir", "os.rmdir", "os.remove", "os.chmod", "os.truncate", "os.utime"}
# 1 つ目と 2 つ目の引数がどちらも書き換える path の event
PAIR_EVENTS = {"os.rename", "os.symlink", "os.link"}
# 2 つ目の引数 (= 写し先) だけを書き換える event
COPY_EVENTS = {"shutil.copyfile", "shutil.copy"}

outside: list[str] = []


def _inside_root(path: object) -> bool:
    if isinstance(path, bytes):
        path = os.fsdecode(path)
    if not isinstance(path, (str, os.PathLike)):
        return True
    resolved = Path(os.path.realpath(path))
    return resolved == ROOT or ROOT in resolved.parents


def audit(event: str, args: tuple) -> None:
    written: list[object] = []
    if event == "open" and isinstance(args[2], int) and args[2] & WRITE_FLAGS:
        written = [args[0]]
    elif event in PATH_EVENTS:
        written = [args[0]]
    elif event in PAIR_EVENTS:
        written = [args[0], args[1]]
    elif event in COPY_EVENTS:
        written = [args[1]]
    outside.extend(f"{event} {path}" for path in written if not _inside_root(path))


def exercise() -> dict[str, str]:
    """backend の書き込み口を 1 つずつ動かす。 返り値は、 口ごとに決まった置き場 (= 根の下に在ると試験が見る)。"""
    from fastapi import UploadFile
    from fastapi.testclient import TestClient

    import backend.main
    import backend.paths as paths
    from backend import state
    from backend.cli import device, gen_vapid
    from backend.config import RATE_LIMITS_LOG_PATH, UPLOADS_TMP, documents_settings, get_config
    from backend.core import push
    from backend.documents.store import get_store
    from backend.jsonl import history
    from backend.routes import files
    from backend.terminal.chat_content import save_to_tmp
    from backend.terminal.tab_memo import memo_path

    pages = ROOT / "pages"
    pages.mkdir(exist_ok=True)
    (pages / "page.html").write_text("<html></html>", encoding="utf-8")
    paths.CONFIG_PATH.write_text(json.dumps({
        "agents": {"agent_a": {"cwd": str(ROOT), "model": "Opus", "display_name": "A", "launch_alias": "a"}},
        "page_origin": {"folder": str(pages), "port": 18999},
    }), encoding="utf-8")
    get_config.cache_clear()

    app = TestClient(backend.main.app)
    added = app.post("/favorites", json={"path": str(pages)})
    assert added.status_code == 200, added.text

    state.save_sessions_meta()
    tab = state.register_session("agent_a", title="probe")
    noted = app.put(f"/sessions/{tab.id}/note", json={"content": "probe"})
    assert noted.status_code == 200, noted.text

    asyncio.run(save_to_tmp([UploadFile(io.BytesIO(b"probe"), filename="probe.txt", size=5)], tab.id))
    stored = TestClient(files.page_app).put("/.store/page.html", content=b"{}", headers={"content-type": "application/json"})
    assert stored.status_code == 204, stored.text

    history.record_end(tab.id, "claude-sid", None)
    push._save_subscriptions()
    gen_vapid.main()
    get_store()

    stray = os.environ.get("PROBE_STRAY")
    if stray:  # 数え方が根の外の書き込みを見つけることの確認用 (= 試験が、 根の外の path を渡す)
        Path(stray).mkdir()
        (Path(stray) / "stray.txt").write_text("stray", encoding="utf-8")

    return {
        "data": str(paths.DATA_DIR),
        "logs": str(paths.LOGS_DIR),
        "secrets": str(paths.SECRETS_DIR),
        "config": str(paths.CONFIG_PATH),
        "favorites": str(paths.FAVORITES_PATH),
        "legacy_notes": str(paths.LEGACY_NOTES_DIR),
        "memo": str(memo_path(tab.id)),
        "page_store": str(paths.PAGE_STORE_DIR),
        "uploads": str(UPLOADS_TMP),
        "document_cache": str(documents_settings()[0]),
        "device_files": str(device.FILES_DIR),
        "rate_limits_log": RATE_LIMITS_LOG_PATH,
    }


if __name__ == "__main__":
    sys.addaudithook(audit)
    placed = exercise()
    print(json.dumps({"outside": outside, "placed": placed}))
