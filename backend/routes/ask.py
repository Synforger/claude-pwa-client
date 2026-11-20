"""The door a program on this machine uses to ask a tab and get its answer (`POST /sessions/{session_id}/ask`).

The work is `backend/ask/ask_turn.py`; this file reads the form and checks the values. `tabs ask` calls it.
"""
from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator

from fastapi import APIRouter, Form, Request
from fastapi.responses import StreamingResponse

from backend._common.errors import raise_error
from backend.ask import ask_turn
from backend.routes.agent_messages import LOCAL_CLIENTS

router = APIRouter()

#: The id of a Claude Code conversation (= a UUID, as the hooks and the record's file name carry it)
CONVERSATION_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


@router.post("/sessions/{session_id}/ask", response_model=None)
async def post_ask(
    request: Request,
    session_id: str,
    text: str = Form(...),
    fresh: bool = Form(False),
    resume: str = Form(""),
    fork: bool = Form(False),
    timeout_sec: float = Form(ask_turn.DEFAULT_TIMEOUT_SEC),
    stream: bool = Form(False),
) -> dict | StreamingResponse:
    """Type `text` into the tab (= its id or name) and answer with the last answer of that turn. With `stream` the
    answer is a stream of JSON lines: the answer so far each time it changes, then the end (= `ask_turn.ask_stream`).
    With `resume` (a conversation's id) the tab opens that conversation first, and with `fork` a branch of it."""
    client_host = request.client.host if request.client else None
    if client_host not in LOCAL_CLIENTS:
        raise_error(403, "ask_local_only", "この口は同じ機械の中からだけ使えます")
    if not text.strip():
        raise_error(400, "ask_empty", "聞く文が空です")
    if not 0 < timeout_sec <= ask_turn.MAX_TIMEOUT_SEC:
        raise_error(400, "ask_bad_timeout", f"待つ秒数は 0 より大きく {ask_turn.MAX_TIMEOUT_SEC:.0f} 以下で書いてください",
                    timeout_sec=timeout_sec)
    resume = resume.strip().lower()
    if resume and fresh:
        raise_error(400, "ask_bad_args", "--fresh と --resume は一緒に使えません (= --fresh は会話を新しくし、 --resume は別の会話を開きます)")
    if fork and not resume:
        raise_error(400, "ask_bad_args", "--fork は --resume と一緒に使います (= 開いた会話の枝に聞きます)")
    if resume and not CONVERSATION_ID.fullmatch(resume):
        raise_error(400, "ask_bad_args", "--resume には Claude の会話の id (= uuid の形) を書いてください", resume=resume)
    opening = {"resume": resume, "fork": fork} if resume else {}
    if stream:
        events = await ask_turn.ask_stream(session_id, text, fresh=fresh, timeout_sec=timeout_sec, **opening)
        return StreamingResponse(_json_lines(events), media_type="application/x-ndjson")
    return await ask_turn.ask(session_id, text, fresh=fresh, timeout_sec=timeout_sec, **opening)


async def _json_lines(events: AsyncIterator[dict]) -> AsyncIterator[str]:
    """One JSON object per line, the way the stream goes out."""
    async for event in events:
        yield json.dumps(event, ensure_ascii=False) + "\n"
