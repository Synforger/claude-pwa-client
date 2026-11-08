"""Make the tailnet URL of a file in the page origin's folder (= what `tabs page-url <file>` prints).

Called by `backend/routes/page_url.py`. This file only computes: the page origin (folder and port), the file and what
`tailscale serve status --json` printed come in, and the URL comes out, or a `PageUrlRefusal` that says why there is
none. The address comes from the serve configuration itself (= the tailnet listener whose root is proxied to the page
port), not from a guess that the tailnet uses the same port number.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote, urlsplit

from backend.page_url.page_url_refusal import PageUrlRefusal

#: The ports a URL leaves out, per scheme.
DEFAULT_PORTS = {"https": 443, "http": 80}
#: The local hosts a serve handler may proxy the page port on.
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def page_url(file: Path, folder: Path, port: int, serve_status: dict) -> str:
    """The tailnet URL of `file` (= resolved) in the page origin `folder` (= resolved) served on the local `port`."""
    return f"{tailnet_base(serve_status, port)}/{quote(path_in_origin(file, folder))}"


def path_in_origin(file: Path, folder: Path) -> str:
    """The path of `file` (= resolved) inside the page origin `folder` (= resolved), as the page port serves it."""
    try:
        return file.relative_to(folder).as_posix()
    except ValueError:
        raise PageUrlRefusal("page_outside_origin",
                             f"ページの origin の folder ({folder}) の外の file です: {file}") from None


def tailnet_base(serve_status: dict, port: int) -> str:
    """The scheme, host and port on the tailnet whose root `tailscale serve` proxies to the local `port`.

    When several listeners do, the one on the same port number is taken, else the lowest port.
    """
    listeners = sorted(_listeners_of(serve_status, port), key=lambda found: (found[2] != port, found[2]))
    if not listeners:
        raise PageUrlRefusal("page_not_on_tailnet",
                             f"tailscale serve がページの port ({port}) を tailnet に出していません "
                             f"(= `tailscale serve --bg --https={port} http://127.0.0.1:{port}`)")
    scheme, host, listen_port = listeners[0]
    shown_port = "" if DEFAULT_PORTS[scheme] == listen_port else f":{listen_port}"
    return f"{scheme}://{host}{shown_port}"


def _listeners_of(serve_status: dict, port: int) -> list[tuple[str, str, int]]:
    """Every (scheme, host, listening port) whose root handler proxies to the local `port`."""
    tcp = serve_status.get("TCP") if isinstance(serve_status.get("TCP"), dict) else {}
    web = serve_status.get("Web") if isinstance(serve_status.get("Web"), dict) else {}
    found = []
    for address, config in web.items():
        host, _, listen = str(address).rpartition(":")
        handler = ((config or {}).get("Handlers") or {}).get("/") if isinstance(config, dict) else None
        if not host or not listen.isdigit() or not isinstance(handler, dict) or not _proxies_to(handler.get("Proxy"), port):
            continue
        scheme = _scheme_of(tcp.get(listen))
        if scheme is not None:
            found.append((scheme, host, int(listen)))
    return found


def _proxies_to(target: object, port: int) -> bool:
    """Whether a serve handler's proxy target is the local `port` (= its root, so paths map one to one)."""
    if not isinstance(target, str):
        return False
    if "://" not in target:
        target = f"http://{target}"
    parts = urlsplit(target)
    try:
        target_port = parts.port
    except ValueError:
        return False
    return parts.hostname in LOCAL_HOSTS and target_port == port and parts.path in ("", "/")


def _scheme_of(listener: object) -> str | None:
    """The scheme a tailnet listener speaks (= `tailscale serve` marks each listening port HTTPS or HTTP)."""
    if not isinstance(listener, dict):
        return None
    if listener.get("HTTPS"):
        return "https"
    if listener.get("HTTP"):
        return "http"
    return None
