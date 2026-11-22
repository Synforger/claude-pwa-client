"""The door a screen answers a permission window through: `POST /sessions/{id}/permission/answer`.

The body is `{"number": <the window's number>, "answer": "allow" | "deny"}`. The answer is `{"ok": true}`, or
`{"ok": false, "reason": "closed"}` when the tab has no window on its pane (or the pane shows no choices), and a 409
`permission_stale` when the number is not the window the pane shows now (= the screen answered an older window). The
windows are `permission_window/window_state.py` and the typing is `permission_window/window_answer.py`.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from backend._common.errors import raise_error
from backend._common.state import sessions_meta
from backend.permission_window import window_answer, window_state

router = APIRouter()


class PermissionAnswer(BaseModel):
    number: int
    answer: Literal["allow", "deny"]


@router.post("/sessions/{session_id}/permission/answer")
async def post_permission_answer(session_id: str, body: PermissionAnswer) -> dict:
    """Answer the permission window the tab's pane shows."""
    if session_id not in sessions_meta:
        raise_error(404, "unknown_session", "Unknown session")
    window = window_state.current_permission(session_id)
    if window is None:
        return dict(window_answer.CLOSED)
    if body.number != window.number:
        raise_error(409, "permission_stale", "その窓は閉じています。 今の窓を確かめてください", current=window.number)
    return await window_answer.answer(session_id, window, body.answer)
