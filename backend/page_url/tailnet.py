"""Read how this machine serves ports on the tailnet (= `tailscale serve status --json`).

Called by `backend/routes/page_url.py`. The command is looked up on `PATH`, then inside the macOS app (= the app does not
put it on `PATH`). When it is missing, fails or prints something that is not JSON, a `PageUrlRefusal` says so.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from backend.page_url.page_url_refusal import PageUrlRefusal

#: Where the macOS app keeps the command when it is not on `PATH`.
TAILSCALE_APP_COMMAND = Path("/Applications/Tailscale.app/Contents/MacOS/Tailscale")
#: How long the local daemon may take to answer (= it answers from memory, in well under a second).
SERVE_STATUS_TIMEOUT_SEC = 10.0


def serve_status() -> dict:
    """What `tailscale serve status --json` prints, as a dict (= `{}` when nothing is served)."""
    command = tailscale_command()
    try:
        done = subprocess.run([command, "serve", "status", "--json"], capture_output=True, text=True, errors="replace",
                              timeout=SERVE_STATUS_TIMEOUT_SEC)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PageUrlRefusal("page_tailnet_unavailable", f"tailscale serve status を読めません: {error}") from None
    if done.returncode != 0:
        reason = (done.stderr or done.stdout).strip().splitlines()
        raise PageUrlRefusal("page_tailnet_unavailable",
                             f"tailscale serve status が失敗しました (exit {done.returncode}): {reason[0] if reason else ''}")
    if not done.stdout.strip():
        return {}
    try:
        status = json.loads(done.stdout)
    except ValueError:
        raise PageUrlRefusal("page_tailnet_unavailable", "tailscale serve status の出力が JSON ではありません") from None
    return status if isinstance(status, dict) else {}


def tailscale_command() -> str:
    """The `tailscale` command of this machine."""
    found = shutil.which("tailscale")
    if found:
        return found
    if TAILSCALE_APP_COMMAND.is_file():
        return str(TAILSCALE_APP_COMMAND)
    raise PageUrlRefusal("page_tailnet_unavailable", "この機械に tailscale の命令が見つかりません")
