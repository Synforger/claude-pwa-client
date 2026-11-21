"""`tabs ask`: ask a tab set up for a program (= its agent has `"ask": true`) and print the last answer of the turn.

    tabs ask <to> <file> [--fresh | --resume <conversation id> [--fork]] [--stream | --json] [--timeout <seconds>]
                                type the text of <file> into the tab <to> and print the last answer of that turn.
                                --fresh types /clear first. --stream prints one JSON per line (= `partial` while the answer
                                is written, then `final` or `error`); --json prints `{"answer": ..., "session": ...}` (= the
                                answer and the id of its conversation). --resume opens that conversation first, and --fork
                                asks a branch of it (= the conversation itself stays; not with --fresh). It waits 180
                                seconds by default and stops the turn after that

`tabs.py` reads the command word and hands the rest here with its way of calling the backend. It needs no `PWA_SID`,
so a program outside every tab (= a subprocess of it) can run it. The door is `POST /sessions/{tab}/ask`
(`backend/routes/ask.py`). With `--stream` the door answers a line of JSON at a time, and each line is printed as it
arrives (= the answer so far while the turn runs, then the end); with `--json` the answer is printed as
`{"answer": ..., "session": ...}` (= the id of the conversation it was given in); `--resume` opens an earlier
conversation first (and `--fork` a branch of it).
"""
from __future__ import annotations

import http.client
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

DEFAULT_TIMEOUT_SEC = 180.0
#: What the call waits beyond the turn: waking a sleeping tab and starting its claude take up to about two minutes
WAKE_MARGIN_SEC = 300.0
NOT_SENT_CODE = "ask_not_sent"
UNCONFIRMED_CODE = "ask_unconfirmed"
USAGE = ("tabs ask <タブの id か名前> <文の file> [--fresh | --resume <会話の id> [--fork]] [--stream | --json] "
         "[--timeout <秒>]")
FLAGS = ("--fresh", "--stream", "--json", "--fork")

#: The backend's call: (path, form, method, timeout) → (HTTP status, JSON body); status 0 when nothing answered
Call = Callable[..., tuple[int, object]]


class AskArguments(NamedTuple):
    to: str
    file: Path
    is_fresh: bool
    timeout_sec: float
    is_stream: bool = False
    is_json: bool = False
    resume: str | None = None
    is_fork: bool = False


def parse(argv: list[str]) -> AskArguments | None:
    """The words after `ask`. → None when they are not `<tab> <file>` with the options of `USAGE`: `--fork` needs
    `--resume`, and `--fresh` and `--resume` are not asked together."""
    if len(argv) < 2:
        return None
    to, file, rest = argv[0], Path(argv[1]), argv[2:]
    flags: set[str] = set()
    resume, timeout_sec = None, DEFAULT_TIMEOUT_SEC
    while rest:
        if rest[0] in FLAGS and rest[0] not in flags:
            flags.add(rest[0])
            rest = rest[1:]
        elif rest[0] == "--resume" and resume is None and len(rest) >= 2 and not rest[1].startswith("-"):
            resume, rest = rest[1], rest[2:]
        elif rest[0] == "--timeout" and len(rest) >= 2:
            try:
                timeout_sec = float(rest[1])
            except ValueError:
                return None
            rest = rest[2:]
        else:
            return None
    if timeout_sec <= 0 or ("--fork" in flags and resume is None) or ("--fresh" in flags and resume is not None):
        return None
    return AskArguments(to, file, "--fresh" in flags, timeout_sec, "--stream" in flags, "--json" in flags, resume,
                        "--fork" in flags)


def run(argv: list[str], call: Call, base_url: str) -> int:
    """Ask, print the answer on stdout and return 0; a failure goes to stderr with its code and returns 1.
    `call` is the backend's call (= one answer), `base_url` its address for the stream."""
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
    if arguments.resume is not None:
        form.update({"resume": arguments.resume, "fork": "true" if arguments.is_fork else "false"})
    path = f"/sessions/{urllib.parse.quote(arguments.to, safe='')}/ask"
    timeout_sec = arguments.timeout_sec + WAKE_MARGIN_SEC
    if arguments.is_stream:
        return run_stream(base_url + path, {**form, "stream": "true"}, timeout_sec)
    status, body = call(path, form, timeout=timeout_sec)
    if status == 200 and isinstance(body, dict) and body.get("ok") and isinstance(body.get("answer"), str):
        print(json.dumps({"answer": body["answer"], "session": body.get("session")}, ensure_ascii=False)
              if arguments.is_json else body["answer"])
        return 0
    code, message = failure(status, body)
    print(f"tabs: 答えを受け取れませんでした [{code}]: {message}", file=sys.stderr)
    return 1


def run_stream(url: str, form: dict[str, str], timeout_sec: float) -> int:
    """Ask for the stream and print each of its lines as it comes (= the lines are JSON, as the door writes them).
    → 0 when the stream ends with the answer; 1 when it ends with the failure (also on stderr, as without `--stream`)
    or ends without either (= the connection broke, and the turn may have gone on in the tab)."""
    request = urllib.request.Request(url, data=urllib.parse.urlencode(form).encode(), method="POST")
    ended: dict | None = None
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            for raw in response:
                line = raw.decode("utf-8").rstrip("\n")
                if not line:
                    continue
                print(line, flush=True)
                event = _event(line)
                if event.get("type") in ("final", "error"):
                    ended = event
    except urllib.error.HTTPError as error:
        code, message = failure(error.code, _json_body(error.read()))
        print(f"tabs: 答えを受け取れませんでした [{code}]: {message}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException) as error:
        cause = error.reason if isinstance(error, urllib.error.URLError) else error
        if ended is None:
            code, message = failure(0, {"detail": {"message": f"backend に繋がりません ({url}): {error}",
                                                   "may_have_arrived": not isinstance(cause, ConnectionRefusedError)}})
            print(f"tabs: 答えを受け取れませんでした [{code}]: {message}", file=sys.stderr)
            return 1
    if ended is not None and ended.get("type") == "final":
        return 0
    if ended is not None:
        print(f"tabs: 答えを受け取れませんでした [{ended.get('code')}]: {ended.get('message', '')}", file=sys.stderr)
        return 1
    code, message = failure(200, {"detail": {"message": "答えの流れが終わりの行なしで切れました"}})
    print(f"tabs: 答えを受け取れませんでした [{code}]: {message}", file=sys.stderr)
    return 1


def _event(line: str) -> dict:
    body = _json_body(line.encode("utf-8"))
    return body if isinstance(body, dict) else {}


def _json_body(raw: bytes) -> object:
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError:
        return {}


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
