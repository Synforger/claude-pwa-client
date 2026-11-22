"""The door a screen answers a permission window through: `POST /pty/{id}/permission/answer`.

It is under `/pty/`, the doors the guard closes to the agents: an agent cannot answer its own window. The body is
`{"number": <the window's number>, "answer": "allow" | "deny"}`. The answer is `{"ok": true}`; `{"ok": false, "reason":
"closed"}` when the tab shows no approval window; `"mismatch"` when it shows one that a key does not answer (it offers
more than `Yes` and `No`, the command on the screen is not the one the hook gave, or the screen has not shown it since
the last answer: it is answered at the terminal); `"not_typed"` when tmux took no key; and a 409 `permission_stale` when
the number is not the window the pane shows now (= the screen answered an older window). The windows are
`permission_window/window_state.py` and the typing is `permission_window/window_answer.py`.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from backend._common.errors import raise_error
from backend._common.state import sessions_meta
from backend.permission_window import window_answer

router = APIRouter()


class PermissionAnswer(BaseModel):
    number: int
    answer: Literal["allow", "deny"]


@router.post("/pty/{session_id}/permission/answer")
async def post_permission_answer(session_id: str, body: PermissionAnswer) -> dict:
    """Answer the permission window the tab's pane shows."""
    if session_id not in sessions_meta:
        raise_error(404, "unknown_session", "Unknown session")
    result = await window_answer.answer(session_id, body.number, body.answer)
    if result.get("reason") == "stale":
        raise_error(409, "permission_stale", "その窓は閉じています。 今の窓を確かめてください", current=result.get("current"))
    return result
