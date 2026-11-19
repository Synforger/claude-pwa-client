"""Reaches a speech engine and its resident service: whether the engine takes a connection, starting and stopping the
service through launchd, and one warm-up sentence that makes the engine load its voice. Blocking; callers on the event
loop run these in a thread. Used by `wake_patrol.py`.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import urllib.parse
import urllib.request

# How long a connection to the engine may take to be taken (= on this machine, refused at once when it is down)
CONNECT_TIMEOUT_SEC = 0.5
# How long one launchctl call may take
LAUNCHCTL_TIMEOUT_SEC = 10.0
# How long the warm-up sentence may take (= the first synthesis loads the voice: 2.7 s measured, ten times that)
WARM_TIMEOUT_SEC = 30.0
WARM_TEXT = "はい。"


def answers(url: str) -> bool:
    """Whether the engine at `url` takes a connection."""
    parts = urllib.parse.urlsplit(url)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        with socket.create_connection((parts.hostname or "127.0.0.1", port), timeout=CONNECT_TIMEOUT_SEC):
            return True
    except OSError:
        return False


def start(label: str) -> str:
    """Start the resident service `label` of this user. → "" when launchd took it, else why not."""
    return _launchctl("kickstart", f"gui/{os.getuid()}/{label}")


def stop(label: str) -> str:
    """Stop the resident service `label` of this user (= SIGTERM; a service declared without keep-alive stays down).
    → "" when launchd took it, else why not."""
    return _launchctl("kill", "SIGTERM", f"gui/{os.getuid()}/{label}")


def warm(url: str, speaker: object) -> bool:
    """Have the engine speak one short sentence, so that the voice is loaded before the first real one. → whether it
    did."""
    asked = urllib.parse.urlencode({"speaker": speaker, "text": WARM_TEXT}, quote_via=urllib.parse.quote)
    try:
        query = _post(f"{url}/audio_query?{asked}", None)
        _post(f"{url}/synthesis?speaker={urllib.parse.quote(str(speaker))}", json.loads(query))
    except (OSError, ValueError):
        return False
    return True


def _post(url: str, body: object) -> bytes:
    data = json.dumps(body).encode() if body is not None else b""
    request = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=WARM_TIMEOUT_SEC) as response:  # noqa: S310 (= url is the config's)
        return response.read()


def _launchctl(*arguments: str) -> str:
    try:
        done = subprocess.run(["launchctl", *arguments], capture_output=True, text=True,
                              timeout=LAUNCHCTL_TIMEOUT_SEC, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        return str(error)
    if done.returncode == 0:
        return ""
    return (done.stderr or done.stdout).strip() or f"launchctl exited {done.returncode}"
