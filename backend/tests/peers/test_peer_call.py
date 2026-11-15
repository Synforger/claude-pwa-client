"""`call_peer` tells a request that could not be sent from one that was sent and got no answer (`peers/peer_call.py`)."""
from __future__ import annotations

import http.client
import urllib.error

import pytest

from backend.peers import peer_call
from backend.peers.peer_call import PeerReply, call_peer
from backend.tests.async_run import run

PEER = {"url": "http://peer.test"}


def _raises(error: BaseException):
    def call(url, payload, timeout):
        raise error
    return call


@pytest.mark.parametrize("error", [
    urllib.error.URLError(ConnectionRefusedError("refused")),
    urllib.error.URLError(TimeoutError("timed out")),  # urllib wraps a timeout while connecting
])
def test_a_request_that_could_not_be_sent_did_not_arrive(monkeypatch, error):
    monkeypatch.setattr(peer_call, "_call_peer", _raises(error))
    assert run(call_peer("home", PEER, "/x")) == PeerReply(None, connected=False)


@pytest.mark.parametrize("error", [
    TimeoutError("timed out"),                 # while reading the answer
    ConnectionResetError("reset"),
    http.client.RemoteDisconnected("closed"),
    http.client.IncompleteRead(b"par"),
])
def test_a_request_that_was_sent_and_got_no_answer_may_have_arrived(monkeypatch, error):
    monkeypatch.setattr(peer_call, "_call_peer", _raises(error))
    reply = run(call_peer("home", PEER, "/x"))
    assert (reply.status, reply.connected, reply.answered) == (None, True, False)


def test_an_answer_carries_its_status_and_body(monkeypatch):
    monkeypatch.setattr(peer_call, "_call_peer", lambda url, payload, timeout: (409, {"detail": {"code": "x"}}))
    reply = run(call_peer("home", PEER, "/x", {"a": 1}))
    assert (reply.status, reply.body, reply.connected, reply.answered) == (409, {"detail": {"code": "x"}}, True, True)


def test_a_real_refused_connection_is_one_that_did_not_arrive():
    # nothing listens on port 9 of this machine
    reply = run(call_peer("home", {"url": "http://127.0.0.1:9"}, "/x", timeout=5))
    assert (reply.status, reply.connected) == (None, False)


def test_a_machine_whose_connection_does_not_open_is_told_apart_without_waiting_for_the_whole_relay(monkeypatch):
    # A machine that sleeps lets the connection time out; the call must not wait the relay's limit for it.
    limits = []

    def no_connection(address, timeout):
        limits.append(timeout)
        raise TimeoutError("timed out")
    monkeypatch.setattr(peer_call.socket, "create_connection", no_connection)
    monkeypatch.setattr(peer_call.urllib.request, "urlopen", lambda *a, **k: pytest.fail("the request was sent"))
    reply = run(call_peer("home", {"url": "https://home.tailnet.test:8443"}, "/x", {"a": 1}))
    assert (reply.status, reply.connected) == (None, False)
    assert limits == [peer_call.CONNECT_TIMEOUT_SEC]


def test_the_connection_is_checked_on_the_port_the_url_names_or_the_scheme_s_own(monkeypatch):
    seen = []

    class Opened:
        def close(self):
            pass
    monkeypatch.setattr(peer_call.socket, "create_connection", lambda address, timeout: seen.append(address) or Opened())
    for url in ("https://home.tailnet.test:8443/x", "https://home.tailnet.test/x", "http://home.tailnet.test/x"):
        peer_call._check_connects(url)
    assert seen == [("home.tailnet.test", 8443), ("home.tailnet.test", 443), ("home.tailnet.test", 80)]
