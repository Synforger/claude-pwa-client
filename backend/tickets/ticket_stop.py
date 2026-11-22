"""What a door of the tickets answers when the backend is asked to stop while the door waits (`_internal/stop_signal.py`).

uvicorn gives the responses 3 seconds at a stop. A door waits for the guard's command, for the other machine and for a tab to
take a line, which takes longer, so it was cut at that time: a traceback in the log and a bare 500 for `tabs`. The waits now end
at the stop (`guard_command.py`, `ticket_relay.py`, `ticket_held.py`) and `StopAnsweringRoute` answers the sender what is true of
the stage the stop came in. A door that reads is a `GET` and one that changes something is a `POST`:

- a read: `ticket_backend_stopping` (503). Nothing was changed, so the same command is sent again once the backend is back.
- a write stopped before anything was written or sent: `ticket_not_sent` (503). The ticket is as it was; send it again.
- a write stopped after a call that may have done it was made (= to the other machine, or the line that tells a tab of a
  `pass`): `ticket_unconfirmed` (500). Look with `tabs ticket show` before sending it again.

A write that reached the file is never cut: it is a few file operations, so the door waits for it and says it was done.
`params.reason` is `backend_stopping` in all three. The failures of the delivery of a message that the stop made
(`agent_message_not_sent`, `agent_message_unconfirmed`, and `agent_message_check_failed` while the backend is stopping) are
answered in the same words. Used by `routes/tickets.py`.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import HTTPException, Request, Response
from fastapi.routing import APIRoute

from backend._internal.stop_signal import BackendStopping, is_stopping

logger = logging.getLogger(__name__)

#: `params.reason` of every answer to a stop (= as the delivery of a message says it, `routes/agent_messages.py`)
STOPPING_REASON = "backend_stopping"
READ_CODE = "ticket_backend_stopping"
NOT_SENT_CODE = "ticket_not_sent"
UNCONFIRMED_CODE = "ticket_unconfirmed"
#: The codes of the delivery of a message that say, with `STOPPING_REASON`, which stage the stop came in
MESSAGE_NOT_SENT_CODE = "agent_message_not_sent"
MESSAGE_UNCONFIRMED_CODE = "agent_message_unconfirmed"
#: The code of a check that did not run, which is a stop when the backend is stopping (= the check's wait was ended by it)
MESSAGE_CHECK_FAILED_CODE = "agent_message_check_failed"

READ_MESSAGE = ("backend が止まる所です。 票は読めていません (= 読むだけなので、 何も変わっていません)。 "
                "backend が起動し直してから、 同じ命令をもう一度打ってください")
NOT_SENT_MESSAGE = ("backend が止まる所です。 票には何も書いていません。 backend が起動し直してから、 "
                    "同じ命令をそのままもう一度打ってください")
UNCONFIRMED_MESSAGE = ("backend が止まる所なので、 別の機械や宛先のタブに届いたかを待てません。 届いているかもしれません。 "
                       "もう一度打つ前に `tabs ticket show <id>` で確かめてください (= 2 度書くのを避けるため)")


class StoppedAfterSending(BackendStopping):
    """The backend was asked to stop after a call that may have done what the sender asked was made (= the call to the other
    machine whose answer was not waited for)."""


def refusal_by_stop(method: str, *, may_have_been_done: bool) -> HTTPException:
    """The answer to a stop for a door called with `method`: for a `GET` the read's, and for the others the write's."""
    if method == "GET":
        code, status, message = READ_CODE, 503, READ_MESSAGE
    elif may_have_been_done:
        code, status, message = UNCONFIRMED_CODE, 500, UNCONFIRMED_MESSAGE
    else:
        code, status, message = NOT_SENT_CODE, 503, NOT_SENT_MESSAGE
    logger.info("ticket door: the backend is stopping; %s answered %s", method, code)
    return HTTPException(status, detail={"code": code, "message": message, "params": {"reason": STOPPING_REASON}})


def _stage_of_message_failure(error: HTTPException) -> bool | None:
    """Whether the failure of the delivery of a message, which the stop made, may have been done (= the text was typed):
    None when the stop did not make it."""
    detail = error.detail if isinstance(error.detail, dict) else {}
    code, params = detail.get("code"), detail.get("params") or {}
    if code == MESSAGE_CHECK_FAILED_CODE and is_stopping():
        return False
    if params.get("reason") != STOPPING_REASON:
        return None
    return {MESSAGE_NOT_SENT_CODE: False, MESSAGE_UNCONFIRMED_CODE: True}.get(code)


class StopAnsweringRoute(APIRoute):
    """A route whose door answers a stop of the backend in the ticket's words (see the head of this file)."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def answering(request: Request) -> Response:
            try:
                return await handler(request)
            except BackendStopping as stop:
                raise refusal_by_stop(request.method, may_have_been_done=isinstance(stop, StoppedAfterSending)) from None
            except HTTPException as error:
                if (may_have_been_done := _stage_of_message_failure(error)) is None:
                    raise
                raise refusal_by_stop(request.method, may_have_been_done=may_have_been_done) from None

        return answering
