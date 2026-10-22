"""main の _start_page_server (= ページの origin を配る 2 つ目の待ち受け) を、 本物の port で立てる test。"""
import asyncio
import json
import logging
import socket
import urllib.request

import backend._common.config as config_mod


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _main():
    """backend.main を test の中で読む (= 集める時に読むと、 設定を読む module が test の設定の前の値で残る)。"""
    import backend.main as main  # noqa: PLC0415
    return main


def _configure(tmp_path, monkeypatch, port):
    import backend.routes.files as files_mod  # noqa: PLC0415
    site = tmp_path / "pages" / "deck"
    site.mkdir(parents=True)
    (site / "index.html").write_text("<!doctype html><p>deck</p>")
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"page_origin": {"folder": str(tmp_path / "pages"), "port": port}}))
    monkeypatch.setattr(config_mod, "CONFIG_PATH", cfg)
    config_mod.get_config.cache_clear()
    monkeypatch.setattr(files_mod, "HOME", tmp_path)
    monkeypatch.setattr(files_mod, "PAGE_STORE_DIR", tmp_path / "store")


def _get(req):
    """GET を 1 本打ち、 (= 状態, 小文字の見出し, 本文) を返す (= 待ち受けと同じ loop を塞がないよう別の thread で呼ぶ)。"""
    with urllib.request.urlopen(req, timeout=5) as res:
        return res.status, {k.lower(): v for k, v in res.headers.items()}, res.read().decode()


async def _until_started(server, task):
    for _ in range(200):
        if server.started or task.done():
            return
        await asyncio.sleep(0.01)


def test_page_server_serves_with_the_scheme_the_proxy_names(tmp_path, monkeypatch):
    # 意図: Tailscale の serve が付ける X-Forwarded-Proto / Host で、 frame-ancestors が https の同じ host になる
    port = _free_port()
    _configure(tmp_path, monkeypatch, port)

    async def scenario():
        import backend.routes.files as files_mod  # noqa: PLC0415
        server, task = _main()._start_page_server()
        await _until_started(server, task)
        listening = files_mod.page_listening
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/deck/index.html",
                headers={"X-Forwarded-Proto": "https", "Host": f"box.example.ts.net:{port}"},
            )
            res = await asyncio.to_thread(_get, req)
        finally:
            server.should_exit = True
            await task
        return res, listening, files_mod.page_listening

    (status, headers, body), listening, after = asyncio.run(scenario())
    assert (listening, after) == (True, False)
    assert status == 200
    assert body == "<!doctype html><p>deck</p>"
    csp = headers["content-security-policy"]
    assert "allow-same-origin" in csp and "allow-top-navigation" not in csp
    assert f"connect-src https://box.example.ts.net:{port}/.store/;" in csp
    assert csp.endswith("frame-ancestors https://box.example.ts.net:*")


def test_page_server_on_a_busy_port_leaves_the_backend_running(tmp_path, monkeypatch, caplog):
    # 意図: port が塞がっていても uvicorn の exit は本体へ漏れず、 理由が log に残る
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        _configure(tmp_path, monkeypatch, port)

        async def scenario():
            _, task = _main()._start_page_server()
            await asyncio.wait_for(task, timeout=5)

        with caplog.at_level(logging.ERROR, logger="backend.main"):
            asyncio.run(scenario())
    assert f"could not listen on 127.0.0.1:{port}" in caplog.text
    import backend.routes.files as files_mod  # noqa: PLC0415
    assert files_mod.page_listening is False


def test_no_page_server_without_the_setting():
    assert _main()._start_page_server() is None
