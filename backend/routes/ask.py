"""The door a program on this machine uses to ask a tab and get its answer (`POST /sessions/{session_id}/ask`).

The work is `backend/ask/ask_turn.py`; this file reads the form and checks the values. `tabs ask` calls it.
"""
from __future__ import annotations

from fastapi import APIRouter, Form, Request

from backend._common.errors import raise_error
from backend.ask import ask_turn
from backend.routes.agent_messages import LOCAL_CLIENTS

router = APIRouter()


@router.post("/sessions/{session_id}/ask")
async def post_ask(
    request: Request,
    session_id: str,
    text: str = Form(...),
    fresh: bool = Form(False),
    timeout_sec: float = Form(ask_turn.DEFAULT_TIMEOUT_SEC),
) -> dict:
    """Type `text` into the tab (= its id or name) and answer with the last answer of that turn."""
    client_host = request.client.host if request.client else None
    if client_host not in LOCAL_CLIENTS:
        raise_error(403, "ask_local_only", "この口は同じ機械の中からだけ使えます")
    if not text.strip():
        raise_error(400, "ask_empty", "聞く文が空です")
    if not 0 < timeout_sec <= ask_turn.MAX_TIMEOUT_SEC:
        raise_error(400, "ask_bad_timeout", f"待つ秒数は 0 より大きく {ask_turn.MAX_TIMEOUT_SEC:.0f} 以下で書いてください",
                    timeout_sec=timeout_sec)
    return await ask_turn.ask(session_id, text, fresh=fresh, timeout_sec=timeout_sec)
