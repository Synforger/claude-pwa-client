"""The door a program on this machine uses to ask a tab and get its answer (`POST /sessions/{session_id}/ask`).

The work is `backend/ask/ask_turn.py`; this file reads the form and checks the values. `tabs ask` calls it.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Form, Request
from fastapi.responses import StreamingResponse

from backend._common.errors import raise_error
from backend.ask import ask_turn
from backend.routes.agent_messages import LOCAL_CLIENTS

router = APIRouter()


@router.post("/sessions/{session_id}/ask", response_model=None)
async def post_ask(
    request: Request,
    session_id: str,
    text: str = Form(...),
    fresh: bool = Form(False),
    timeout_sec: float = Form(ask_turn.DEFAULT_TIMEOUT_SEC),
    stream: bool = Form(False),
) -> dict | StreamingResponse:
    """Type `text` into the tab (= its id or name) and answer with the last answer of that turn. With `stream` the
    answer is a stream of JSON lines: the answer so far each time it changes, then the end (= `ask_turn.ask_stream`)."""
    client_host = request.client.host if request.client else None
    if client_host not in LOCAL_CLIENTS:
        raise_error(403, "ask_local_only", "この口は同じ機械の中からだけ使えます")
    if not text.strip():
        raise_error(400, "ask_empty", "聞く文が空です")
    if not 0 < timeout_sec <= ask_turn.MAX_TIMEOUT_SEC:
        raise_error(400, "ask_bad_timeout", f"待つ秒数は 0 より大きく {ask_turn.MAX_TIMEOUT_SEC:.0f} 以下で書いてください",
                    timeout_sec=timeout_sec)
    if stream:
        events = await ask_turn.ask_stream(session_id, text, fresh=fresh, timeout_sec=timeout_sec)
        return StreamingResponse(_json_lines(events), media_type="application/x-ndjson")
    return await ask_turn.ask(session_id, text, fresh=fresh, timeout_sec=timeout_sec)


async def _json_lines(events: AsyncIterator[dict]) -> AsyncIterator[str]:
    """One JSON object per line, the way the stream goes out."""
    async for event in events:
        yield json.dumps(event, ensure_ascii=False) + "\n"
