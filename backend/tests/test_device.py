"""iPhone の app との中継 (= backend/device/hub.py)、 その口 (= backend/routes/device.py)、 命令 (= backend/cli/device.py)。"""
from __future__ import annotations

import asyncio
import base64
import importlib.util
import json
import os
import threading
from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from backend.device.hub import DeviceFailed, DeviceHub, DeviceOffline, DeviceTimeout, UnknownOp

CATALOG = [
    {"name": "health.steps", "kind": "read", "summary": "steps per day", "timeout_s": 5,
     "params": [{"name": "days", "type": "int", "required": False, "description": "how many days back"}]},
    {"name": "camera.take", "kind": "act", "summary": "take a photo", "foreground": True, "params": []},
]
HELLO = {"type": "hello", "device": "iPhone", "app": "1.9.0 (4)", "catalog": CATALOG}


def _run(coro):
    """asyncio.run は loop を閉じて外したまま返すので、 後に走る test (= get_event_loop を使う物) が loop を持てない。
    新しい loop で回し、 終わったら別の新しい loop を置き直す (= test_unified_stream の _run と同じ)。"""
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.run_until_complete(asyncio.sleep(0))
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


def _hub(tmp_path: Path) -> DeviceHub:
    return DeviceHub(catalog_path=tmp_path / "catalog.json", files_dir=tmp_path / "files")


# --- 中継 ---------------------------------------------------------------------------------------------------

def test_a_call_goes_to_the_app_and_returns_its_answer(tmp_path):
    hub = _hub(tmp_path)
    sent: list[dict] = []

    async def scenario():
        async def send(message):
            sent.append(message)
            hub.receive({"type": "result", "id": message["id"], "ok": True, "result": {"steps": [1200, 8000]}})

        hub.attach(send, HELLO)
        return await hub.call("health.steps", {"days": 2})

    assert _run(scenario()) == {"steps": [1200, 8000]}
    assert sent == [{"type": "call", "id": "1", "op": "health.steps", "args": {"days": 2}}]


def test_files_in_an_answer_are_written_and_named_by_path(tmp_path):
    hub = _hub(tmp_path)
    photo = base64.b64encode(b"jpeg-bytes").decode()

    async def scenario():
        async def send(message):
            hub.receive({"type": "result", "id": message["id"], "ok": True, "result": {"width": 4},
                         "files": [{"name": "../photo 1.jpg", "mime": "image/jpeg", "data": photo}]})

        hub.attach(send, HELLO)
        return await hub.call("camera.take", {})

    result = _run(scenario())
    assert result["width"] == 4
    [path] = result["files"]
    assert Path(path).parent == tmp_path / "files"     # (= app が付けた名前で外へ出ない)
    assert Path(path).read_bytes() == b"jpeg-bytes"


def test_without_the_app_a_call_says_it_is_not_connected_and_the_last_list_is_kept(tmp_path):
    hub = _hub(tmp_path)

    async def scenario():
        async def send(message):
            pass

        link = hub.attach(send, HELLO)
        hub.detach(link)
        with pytest.raises(DeviceOffline):
            await hub.call("health.steps", {})

    _run(scenario())
    status = hub.status()
    assert status["connected"] is False
    assert [op["name"] for op in status["catalog"]] == ["health.steps", "camera.take"]


def test_an_operation_the_app_does_not_list_is_refused_before_it_is_sent(tmp_path):
    hub = _hub(tmp_path)
    sent: list[dict] = []

    async def scenario():
        async def send(message):
            sent.append(message)

        hub.attach(send, HELLO)
        with pytest.raises(UnknownOp):
            await hub.call("photos.delete", {})

    _run(scenario())
    assert sent == []


def test_a_call_without_an_answer_times_out_and_a_failure_is_passed_on(tmp_path):
    hub = _hub(tmp_path)

    async def scenario():
        async def silent(message):
            pass

        hub.attach(silent, HELLO)
        with pytest.raises(DeviceTimeout):
            await hub.call("health.steps", {}, timeout_s=0.05)

        async def refuse(message):
            hub.receive({"type": "result", "id": message["id"], "ok": False, "error": "Health access denied"})

        hub.attach(refuse, HELLO)
        with pytest.raises(DeviceFailed, match="Health access denied"):
            await hub.call("health.steps", {})

    _run(scenario())


def test_a_waiting_call_ends_when_the_app_goes_and_a_newer_app_takes_over(tmp_path):
    hub = _hub(tmp_path)

    async def scenario():
        async def silent(message):
            pass

        old = hub.attach(silent, HELLO)
        waiting = asyncio.ensure_future(hub.call("health.steps", {}))
        await asyncio.sleep(0)
        hub.attach(silent, {**HELLO, "device": "newer"})
        with pytest.raises(DeviceOffline, match="another app connected"):
            await waiting
        hub.detach(old)                      # (= 替わった後の古い app が切れても、 新しい app は残る)
        assert hub.status()["device"] == "newer"

    _run(scenario())


# --- 口 -----------------------------------------------------------------------------------------------------

@pytest.fixture
def device_app(tmp_path, monkeypatch):
    from backend.device.screen import ScreenStore
    from backend.routes import device

    monkeypatch.setattr(device, "hub", _hub(tmp_path))
    monkeypatch.setattr(device, "screen", ScreenStore(tmp_path / "files"))
    app = FastAPI()
    app.include_router(device.router)
    return app, device


def test_the_ops_and_catalog_take_only_calls_from_this_mac(device_app):
    app, _ = device_app
    with TestClient(app) as client:
        assert client.get("/device/catalog").status_code == 403
        assert client.post("/device/ops", json={"op": "health.steps"}).status_code == 403
        local = TestClient(app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50000))
        assert local.get("/device/catalog").json()["connected"] is False


def test_an_app_on_the_socket_answers_a_call_made_on_this_mac(device_app, monkeypatch):
    app, device = device_app
    monkeypatch.setattr(device, "_ensure_localhost", lambda request: None)
    with TestClient(app) as client, client.websocket_connect("/device/ws") as ws:
        ws.send_text(json.dumps(HELLO))
        answer: dict = {}

        def ask():
            answer.update(client.post("/device/ops", json={"op": "health.steps", "args": {"days": 1}}).json())

        thread = threading.Thread(target=ask)
        thread.start()
        call = json.loads(ws.receive_text())
        assert call["op"] == "health.steps" and call["args"] == {"days": 1}
        ws.send_text(json.dumps({"type": "result", "id": call["id"], "ok": True, "result": [9000]}))
        thread.join(5)
        assert answer == {"ok": True, "result": [9000]}
        assert client.get("/device/catalog").json()["device"] == "iPhone"


def test_a_socket_that_does_not_say_hello_is_closed(device_app):
    app, _ = device_app
    with TestClient(app) as client, client.websocket_connect("/device/ws") as ws:
        ws.send_text(json.dumps({"type": "result"}))
        with pytest.raises(Exception):
            ws.receive_text()


# --- 画面の配信 ---------------------------------------------------------------------------------------------

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 100


def test_the_screen_keeps_the_last_frame_and_says_whether_it_is_live(device_app):
    app, device = device_app
    local = TestClient(app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50000))
    assert local.get("/device/screen").json()["path"] is None
    with TestClient(app) as phone:   # (= iPhone は tailnet から送る)
        assert phone.post("/device/screen/state", json={"live": True}).json() == {"live": True}
        assert phone.post("/device/screen", content=JPEG, headers={"Content-Type": "image/jpeg"}).json() == {"bytes": len(JPEG)}
        assert phone.post("/device/screen", content=JPEG + b"1").status_code == 200
    status = local.get("/device/screen").json()
    assert status["live"] is True and status["bytes"] == len(JPEG) + 1
    assert Path(status["path"]).read_bytes() == JPEG + b"1"
    with TestClient(app) as phone:
        phone.post("/device/screen/state", json={"live": False})
    assert local.get("/device/screen").json()["live"] is False


def test_the_screen_refuses_what_is_not_a_jpeg_and_is_read_only_on_this_mac(device_app):
    app, device = device_app
    with TestClient(app) as phone:
        assert phone.post("/device/screen", content=b"<html>").status_code == 400
        assert phone.post("/device/screen", content=b"\xff\xd8" + b"0" * (5 * 1024 * 1024)).status_code == 400
        assert phone.post("/device/screen/state", json={"live": "yes"}).status_code == 400
        assert phone.get("/device/screen").status_code == 403


def test_screen_settings_take_the_config_over_the_defaults_and_drop_bad_values(device_app, monkeypatch):
    from backend.device import screen as screen_module

    app, _ = device_app
    monkeypatch.setattr("backend.config.DEVICE_SCREEN", {
        "interval_s": 2, "quality": 1.5, "max_side": "big", "unknown": 3}, raising=False)
    with TestClient(app) as phone:
        got = phone.get("/device/screen/settings").json()
    assert got == {**screen_module.SETTINGS_DEFAULT, "interval_s": 2.0}
    assert screen_module.settings(None) == screen_module.SETTINGS_DEFAULT


def test_a_frame_older_than_the_stale_limit_is_not_live(tmp_path, monkeypatch):
    import os
    import time

    from backend.device import screen as screen_module

    store = screen_module.ScreenStore(tmp_path)
    store.receive(JPEG)
    old = time.time() - screen_module.STALE_S - 1
    os.utime(store.path, (old, old))
    assert store.status()["live"] is False


# --- 命令 ---------------------------------------------------------------------------------------------------

def _cli():
    path = Path(__file__).resolve().parents[1] / "cli" / "device.py"
    spec = importlib.util.spec_from_file_location("device_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_command_turns_flags_into_typed_arguments_by_the_list():
    cli = _cli()
    args, timeout = cli._args(["--days", "7", "--json", '{"kind": "steps"}', "--timeout", "90"], CATALOG[0])
    assert args == {"days": 7, "kind": "steps"} and timeout == 90.0
    with pytest.raises(cli.Stop):
        cli._args(["--days", "seven"], CATALOG[0])


def test_the_command_lists_operations_by_type_and_calls_one(monkeypatch, capsys):
    cli = _cli()
    calls: list[tuple] = []

    def request(method, path, body=None, timeout=600):
        calls.append((method, path, body))
        if path == "/device/catalog":
            return {"connected": True, "device": "iPhone", "app": "1.9.0", "catalog": CATALOG}
        return {"ok": True, "result": {"steps": [8000]}}

    monkeypatch.setattr(cli, "_request", request)
    assert cli.main([]) == 0
    listing = capsys.readouterr().out
    assert "health" in listing and "steps" in listing and "camera" in listing
    assert cli.main(["health", "steps", "--days", "3"]) == 0
    assert json.loads(capsys.readouterr().out) == {"steps": [8000]}
    assert calls[-1] == ("POST", "/device/ops", {"op": "health.steps", "args": {"days": 3}})


def test_the_command_exits_with_a_number_that_says_why(monkeypatch, capsys):
    cli = _cli()

    def offline(method, path, body=None, timeout=600):
        if path == "/device/catalog":
            return {"connected": False, "catalog": CATALOG}
        raise cli.Stop("offline", "the iPhone app is not connected")

    monkeypatch.setattr(cli, "_request", offline)
    assert cli.main(["health", "steps"]) == 3
    assert "not connected" in capsys.readouterr().err


def test_the_command_shows_the_screen(monkeypatch, capsys):
    cli = _cli()
    monkeypatch.setattr(cli, "_request", lambda method, path, body=None, timeout=600:
                        {"live": True, "path": "/data/device-files/screen.jpg", "age_s": 0.4} if path == "/device/screen" else None)
    assert cli.main(["screen"]) == 0
    assert json.loads(capsys.readouterr().out)["path"].endswith("screen.jpg")


def test_the_cpc_command_hands_device_to_the_device_command_even_through_a_link(tmp_path):
    import subprocess
    from pathlib import Path

    cpc = Path(__file__).resolve().parents[2] / "bin" / "cpc"
    link = tmp_path / "cpc"
    link.symlink_to(cpc)
    # backend の住所を必ず届かない所へ向ける (= 動いている backend に頼らない)。 device が実体へ渡れば、 実体が
    # 「backend に届かない」 (= 7) で終わる
    env = {**os.environ, "CPC_URL": "http://127.0.0.1:9"}
    device = subprocess.run([str(link), "device"], capture_output=True, text=True, timeout=30, env=env)
    assert device.returncode == 7 and device.stderr.startswith("cpc device:")
    unknown = subprocess.run([str(link), "nothing"], capture_output=True, text=True, timeout=30, env=env)
    assert unknown.returncode == 2 and "usage: cpc device" in unknown.stderr
