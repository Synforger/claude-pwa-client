"""Tests of `backend/page_url/page_url.py`: the tailnet URL of a page, made from the page origin and the serve status."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.page_url.page_url import page_url, tailnet_base
from backend.page_url.page_url_refusal import PageUrlRefusal

FOLDER = Path("/agents")
PORT = 8776
HOST = "mac.tailnet.ts.net"


def serving(*listeners: tuple[str, int, str], extra_handlers: dict | None = None) -> dict:
    """A serve status with one root handler per (scheme, listening port, proxy target)."""
    tcp, web = {}, {}
    for scheme, listen, target in listeners:
        tcp[str(listen)] = {"HTTPS": True} if scheme == "https" else {"HTTP": True}
        web[f"{HOST}:{listen}"] = {"Handlers": {"/": {"Proxy": target}, **(extra_handlers or {})}}
    return {"TCP": tcp, "Web": web}


def test_the_url_is_the_listener_that_proxies_to_the_page_port_with_the_path_inside_the_folder():
    status = serving(("https", 443, "http://127.0.0.1:8766"), ("https", 8776, "http://127.0.0.1:8776"))
    assert page_url(FOLDER / "agent/pages/a b/図.html", FOLDER, PORT, status) == \
        f"https://{HOST}:8776/agent/pages/a%20b/%E5%9B%B3.html"


def test_the_default_port_is_left_out_of_the_url():
    assert tailnet_base(serving(("https", 443, "http://127.0.0.1:8776")), PORT) == f"https://{HOST}"
    assert tailnet_base(serving(("http", 80, "http://localhost:8776")), PORT) == f"http://{HOST}"


def test_an_http_listener_gives_an_http_url_with_its_port():
    assert tailnet_base(serving(("http", 8080, "http://127.0.0.1:8776")), PORT) == f"http://{HOST}:8080"


@pytest.mark.parametrize("target", ["127.0.0.1:8776", "http://127.0.0.1:8776/", "http://localhost:8776", "http://[::1]:8776"])
def test_the_proxy_target_may_be_written_in_any_local_form(target):
    assert tailnet_base(serving(("https", 8776, target)), PORT) == f"https://{HOST}:8776"


def test_of_several_listeners_the_same_port_number_wins_then_the_lowest():
    same = serving(("https", 443, "http://127.0.0.1:8776"), ("https", 8776, "http://127.0.0.1:8776"))
    assert tailnet_base(same, PORT) == f"https://{HOST}:8776"
    other = serving(("https", 9443, "http://127.0.0.1:8776"), ("https", 8443, "http://127.0.0.1:8776"))
    assert tailnet_base(other, PORT) == f"https://{HOST}:8443"


@pytest.mark.parametrize("status", [
    {},
    serving(("https", 8776, "http://127.0.0.1:8766")),
    serving(("https", 8776, "http://127.0.0.1:8776/pages")),
    serving(("https", 8776, "http://192.0.2.1:8776")),
    {"TCP": {"8776": {"HTTPS": True}}, "Web": {f"{HOST}:8776": {"Handlers": {"/agent": {"Proxy": "http://127.0.0.1:8776"}}}}},
    {"TCP": {}, "Web": {f"{HOST}:8776": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8776"}}}}},
    {"TCP": "junk", "Web": ["junk"]},
], ids=["nothing served", "another port", "a sub path", "another host", "only a sub handler", "no listener mark", "junk"])
def test_a_page_port_the_tailnet_does_not_reach_is_refused_with_the_command_that_serves_it(status):
    with pytest.raises(PageUrlRefusal) as refusal:
        tailnet_base(status, PORT)
    assert refusal.value.code == "page_not_on_tailnet"
    assert "tailscale serve --bg --https=8776 http://127.0.0.1:8776" in refusal.value.message


def test_a_file_outside_the_folder_is_refused():
    with pytest.raises(PageUrlRefusal) as refusal:
        page_url(Path("/elsewhere/page.html"), FOLDER, PORT, serving(("https", 8776, "http://127.0.0.1:8776")))
    assert refusal.value.code == "page_outside_origin"
