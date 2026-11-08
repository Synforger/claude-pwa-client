"""The endpoint that answers the tailnet URL of a page (= `tabs page-url <file>`).

An agent that hands the operator a page needs the address the operator's devices open, not `localhost`. The backend
knows the page origin (= `page_origin` in the configuration, and whether its listener is open) and asks `tailscale
serve` which tailnet address proxies to it; `backend/page_url/page_url.py` puts the two together.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, Query, Request

from backend._common.config import page_origin
from backend._common.errors import raise_error
from backend.page_url.page_url import page_url, path_in_origin
from backend.page_url.page_url_refusal import PageUrlRefusal
from backend.page_url.tailnet import serve_status
from backend.routes import files as files_routes
from backend.routes.agent_messages import LOCAL_CLIENTS

logger = logging.getLogger(__name__)
router = APIRouter()

#: The HTTP status for each refusal of `backend/page_url/`.
REFUSAL_STATUS = {
    "page_outside_origin": 400,
    "page_not_on_tailnet": 409,
    "page_tailnet_unavailable": 503,
}


@router.get("/page-url")
async def get_page_url(request: Request, path: str = Query(...)) -> dict:
    """The tailnet URL where the operator's devices open the file `path`. → `{"url": <URL>}`.

    query:
        path (str): an absolute path (= `~` allowed) of a file inside the page origin's folder
    """
    client_host = request.client.host if request.client else None
    if client_host not in LOCAL_CLIENTS:
        logger.warning("page url rejected: non-local client=%s", client_host)
        raise_error(403, "page_url_local_only", "この口は同じ機械の中からだけ使えます")
    origin = page_origin()
    if origin is None:
        raise_error(409, "page_origin_unset", "client の設定に page_origin がありません (= ページを配る folder と port)")
    if not files_routes.page_listening:
        raise_error(503, "page_origin_not_listening", f"ページの port ({origin[1]}) の待ち受けが開いていません")
    file = Path(path).expanduser()
    if not file.is_absolute():
        raise_error(400, "page_path_not_absolute", f"path は絶対 path で渡してください: {path}", path=path)
    file = file.resolve()
    if not file.is_file():
        raise_error(404, "page_not_found", f"file がありません: {file}", path=str(file))
    folder, port = origin
    try:
        # the file's own fault is told before the tailnet's (= tailscale is asked only for a file it could serve)
        path_in_origin(file, folder)
        url = page_url(file, folder, port, await asyncio.to_thread(serve_status))
    except PageUrlRefusal as refusal:
        raise_error(REFUSAL_STATUS[refusal.code], refusal.code, refusal.message)
    return {"url": url}
