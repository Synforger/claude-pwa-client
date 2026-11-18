"""`tabs ask`: ask a tab set up for a program (= its agent has `"ask": true`) and print the last answer of the turn.

`tabs.py` reads the command word and hands the rest here with its way of calling the backend. It needs no `PWA_SID`,
so a program outside every tab (= a subprocess of it) can run it. The door is `POST /sessions/{tab}/ask`
(`backend/routes/ask.py`).
"""
from __future__ import annotations

import sys
import urllib.parse
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

DEFAULT_TIMEOUT_SEC = 180.0
#: What the call waits beyond the turn: waking a sleeping tab and starting its claude take up to about two minutes
WAKE_MARGIN_SEC = 300.0
NOT_SENT_CODE = "ask_not_sent"
UNCONFIRMED_CODE = "ask_unconfirmed"
USAGE = "tabs ask <タブの id か名前> <文の file> [--fresh] [--timeout <秒>]"

#: The backend's call: (path, form, method, timeout) → (HTTP status, JSON body); status 0 when nothing answered
Call = Callable[..., tuple[int, object]]


class AskArguments(NamedTuple):
    to: str
    file: Path
    is_fresh: bool
    timeout_sec: float


def parse(argv: list[str]) -> AskArguments | None:
    """The words after `ask`. → None when they are not `<tab> <file> [--fresh] [--timeout <seconds>]`."""
    if len(argv) < 2:
        return None
    to, file, rest = argv[0], Path(argv[1]), argv[2:]
    is_fresh, timeout_sec = False, DEFAULT_TIMEOUT_SEC
    while rest:
        if rest[0] == "--fresh" and not is_fresh:
            is_fresh, rest = True, rest[1:]
        elif rest[0] == "--timeout" and len(rest) >= 2:
            try:
                timeout_sec = float(rest[1])
            except ValueError:
                return None
            rest = rest[2:]
        else:
            return None
    return AskArguments(to, file, is_fresh, timeout_sec) if timeout_sec > 0 else None


def run(argv: list[str], call: Call) -> int:
    """Ask, print the answer on stdout and return 0; a failure goes to stderr with its code and returns 1."""
    arguments = parse(argv)
    if arguments is None:
        print(f"使い方: {USAGE}", file=sys.stderr)
        return 2
    try:
        text = arguments.file.read_text(encoding="utf-8")
    except OSError as error:
        print(f"tabs: {arguments.file} を読めません: {error}", file=sys.stderr)
        return 1
    form = {"text": text, "fresh": "true" if arguments.is_fresh else "false", "timeout_sec": str(arguments.timeout_sec)}
    path = f"/sessions/{urllib.parse.quote(arguments.to, safe='')}/ask"
    status, body = call(path, form, timeout=arguments.timeout_sec + WAKE_MARGIN_SEC)
    if status == 200 and isinstance(body, dict) and body.get("ok") and isinstance(body.get("answer"), str):
        print(body["answer"])
        return 0
    code, message = failure(status, body)
    print(f"tabs: 答えを受け取れませんでした [{code}]: {message}", file=sys.stderr)
    return 1


def failure(status: int, body: object) -> tuple[str, str]:
    """The code and the sentence of an answer that carries no answer: the backend's own, or one made from the call."""
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, dict) and detail.get("code"):
        return str(detail["code"]), str(detail.get("message", ""))
    raw = str(detail.get("message")) if isinstance(detail, dict) and detail.get("message") else str(body)[:200]
    if status == 0 and not (isinstance(detail, dict) and detail.get("may_have_arrived")):
        return NOT_SENT_CODE, f"{raw}。 何も聞いていません。 backend が起動し直している間かもしれません。 少し待って聞き直してください"
    return UNCONFIRMED_CODE, (f"backend から答えを受け取れませんでした (HTTP {status}): {raw}。 文はタブに届いているかもしれません。 "
                              "聞き直す前に、 タブの会話を確かめてください")
