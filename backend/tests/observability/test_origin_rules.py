"""Tests of the origin table (`backend/observability/origin_rules.py`), which is only observed."""
from __future__ import annotations

import asyncio
import logging

import pytest

from backend.observability import origin_rules, request_origin, served_names
from backend.observability.origin_rules import KnownNames, RequestFacts
from backend.observability.outside_rules_counter import OutsideRulesCounter
from backend.page_url.page_url_refusal import PageUrlRefusal

NAME = "pc.example.ts.net"
PORT = 8765
STATUS = {
    "TCP": {"443": {"HTTPS": True}, "8775": {"HTTPS": True}, "8443": {"HTTPS": True}},
    "Web": {
        f"{NAME}:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8765"}}},
        f"{NAME}:8775": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8775"}}},
        f"{NAME}:8443": {"Handlers": {"/ext/x": {"Proxy": "http://127.0.0.1:9000"}}},
    },
}
KNOWN = origin_rules.known_names(PORT, STATUS)


def facts(method: str = "GET", template: str = "/sessions", host: str = NAME, origin: str = "(none)",
          site: str = "(none)", mode: str = "(none)") -> RequestFacts:
    return RequestFacts(method, template, host, origin, site, mode)


@pytest.mark.parametrize("seen", [
    facts(host="127.0.0.1:8765"),
    facts(host="localhost:8765"),
    facts(host="[::1]:8765"),
    facts(host=NAME),
    facts(host=f"{NAME}:443"),
    facts(site="none", mode="navigate"),
    facts("POST"),
    facts("POST", origin=f"https://{NAME}", site="same-origin"),
    facts("POST", site="same-origin"),
    facts("POST", site="none"),
    facts("POST", host="localhost:8765", origin="http://localhost:8765"),
    facts("WS", origin=f"https://{NAME}"),
    facts("WS"),
    facts(template="/stream/unified"),
    facts(template="/stream/unified", site="same-origin", mode="cors"),
    facts(template="/stream/unified", origin=f"https://{NAME}"),
    facts(template="/file/view/{path:path}", site="same-site", mode="navigate"),
], ids=lambda _: "seen")
def test_the_known_uses_are_inside_the_table(seen):
    assert origin_rules.rows_outside(seen, KNOWN) == ()


@pytest.mark.parametrize(("seen", "rows"), [
    (facts(host="other.example:8765"), ("A",)),
    (facts(host="(none)"), ("A",)),
    (facts(host="(malformed)"), ("A",)),
    (facts(host=f"{NAME}:8775"), ("A",)),
    (facts(host=f"{NAME}:8443"), ("A",)),
    (facts(host="localhost.example:8765"), ("A",)),
    (facts("POST", origin="https://other.example"), ("B",)),
    (facts("POST", origin="null"), ("B",)),
    (facts("POST", origin=f"https://{NAME}:8775"), ("B",)),
    (facts("POST", site="cross-site"), ("B",)),
    (facts("DELETE", site="same-site"), ("B",)),
    (facts("(malformed)", origin="https://other.example"), ("B",)),
    (facts("WS", origin="https://other.example"), ("C",)),
    (facts(template="/stream/unified", origin="https://other.example"), ("D",)),
    (facts(template="/stream/unified", site="cross-site"), ("D",)),
    (facts(template="/stream/unified", site="same-origin", mode="navigate"), ("D",)),
    (facts("POST", host="other.example", origin="https://other.example"), ("A", "B")),
], ids=lambda value: "row")
def test_what_is_outside_the_table_is_named_by_its_rows(seen, rows):
    assert origin_rules.rows_outside(seen, KNOWN) == rows


def test_the_page_app_has_names_of_its_own():
    page = origin_rules.known_names(8775, STATUS)
    assert f"{NAME}:8775" in page.hosts
    assert NAME not in page.hosts
    assert f"https://{NAME}" not in page.origins


def test_configured_origins_are_known():
    known = origin_rules.known_names(PORT, STATUS, extra_origins=("http://localhost:5173",))
    assert origin_rules.rows_outside(facts("POST", origin="http://localhost:5173"), known) == ()


def test_names_not_read_yet_are_said_to_be_unread():
    known = origin_rules.known_names(PORT, None)
    assert origin_rules.rows_outside(facts(host=NAME), known) == (origin_rules.UNREAD,)
    assert origin_rules.rows_outside(facts(host="127.0.0.1:8765"), known) == ()


def test_a_failed_read_keeps_what_was_read(monkeypatch):
    names = served_names.ServedNames()
    monkeypatch.setattr(served_names, "serve_status", lambda: STATUS)
    names.refresh()
    assert NAME in names.known(PORT).hosts

    def unavailable():
        raise PageUrlRefusal("page_tailnet_unavailable", "down")

    monkeypatch.setattr(served_names, "serve_status", unavailable)
    names.refresh()
    assert NAME in names.known(PORT).hosts


def test_a_failed_first_read_is_unread(monkeypatch):
    def unavailable():
        raise PageUrlRefusal("page_tailnet_unavailable", "down")

    monkeypatch.setattr(served_names, "serve_status", unavailable)
    names = served_names.ServedNames()
    names.refresh()
    assert isinstance(names.known(PORT), KnownNames) and not names.known(PORT).is_read


def test_the_read_does_not_hold_the_loop(monkeypatch):
    on_loop: list[bool] = []

    def status():
        try:
            asyncio.get_running_loop()
            on_loop.append(True)
        except RuntimeError:
            on_loop.append(False)
        return STATUS

    monkeypatch.setattr(served_names, "serve_status", status)

    async def one_look():
        task = asyncio.create_task(served_names.ServedNames().refresh_loop())
        while not on_loop:
            await asyncio.sleep(0.01)
        task.cancel()

    asyncio.run(one_look())
    assert on_loop == [False]


def _through_middleware(headers, *, outside, counter, kind="http", method="POST"):
    names = served_names.ServedNames()
    names.replace(STATUS)
    sent = []

    async def app(_scope, _receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request"}

    middleware = request_origin.RequestOriginMiddleware(app, app_name="main", counter=counter, names=names,
                                                        outside=outside)
    scope = {"type": kind, "method": method, "path": "/private/ses_1", "query_string": b"token=1",
             "server": ("127.0.0.1", PORT), "headers": headers}
    asyncio.run(middleware(scope, receive, send))
    return sent


def test_a_request_outside_the_table_is_logged_and_goes_on_unchanged(caplog):
    caplog.set_level(logging.INFO)
    sent = _through_middleware(
        [(b"host", NAME.encode()), (b"origin", b"https://other.example"), (b"sec-fetch-mode", b"cors")],
        outside=OutsideRulesCounter(), counter=request_origin.RequestOriginCounter())
    assert [message["type"] for message in sent] == ["http.response.start", "http.response.body"]
    assert sent[0]["status"] == 200
    line = next(text for text in caplog.messages if text.startswith("request origin rules:"))
    assert "outside=B" in line and "sec_fetch_mode=cors" in line
    assert "token" not in line and "ses_1" not in line


def test_a_request_inside_the_table_leaves_no_rules_line(caplog):
    caplog.set_level(logging.INFO)
    _through_middleware([(b"host", NAME.encode())], outside=OutsideRulesCounter(),
                        counter=request_origin.RequestOriginCounter())
    assert not [text for text in caplog.messages if text.startswith("request origin rules:")]


def test_the_rules_lines_have_a_limit_of_their_own(caplog):
    caplog.set_level(logging.INFO)
    counter = request_origin.RequestOriginCounter(max_pair_count=0)
    _through_middleware([(b"host", b"other.example")], outside=OutsideRulesCounter(), counter=counter)
    assert [text for text in caplog.messages if "outside=A" in text]
