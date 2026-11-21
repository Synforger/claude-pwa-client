"""`tabs ticket`: the requests that cross tabs, kept as one ticket each that tabs only add to (`docs/reference/tickets.md`).

    tabs ticket new <title> <body file> [--operator-said]
                                open a ticket and print its id. --operator-said puts the operator's last words in this tab
                                into the ticket (= read from the conversation record; only when the request came from them)
    tabs ticket show <id>       read the whole ticket by time; a line the guard does not let this tab read is one line saying so
    tabs ticket add <id> <file> add what you did (= nothing is removed or reworded; the holder does not change)
    tabs ticket ask <id> --kind decide|mac|report <file> [--recommend <file>]
                                put the ticket in front of the operator: decide = a decision, mac = something only done at the
                                Mac, report = a report. The recommendation is what the operator may take as it stands. The ticket
                                waits for the operator from here (waiting-operator)
    tabs ticket close <id> [<file>]
                                close the ticket (= it stays; nothing can be added after). <file> is the last word
    tabs ticket pass <id> <tab>   move the ticket to that tab (= its id, the outward name `tabs list` shows, or its name, found as
                                `tabs send` finds them; `<machine>:<tab>` for a tab of the other machine)
                                and tell it in one line. A ticket waiting for the operator is refused

A ticket kept on the other machine (= the machine named at the head of its id) is used with the same commands: this machine's
backend carries `show`, `add`, `close` and `pass` to it. `ask` is refused there (`ticket_ask_elsewhere`), and a machine that
does not answer is `ticket_peer_down` (= nothing was done; try again when it is back).

`tabs.py` reads the command word and hands the rest here with its way of calling the backend. The sender is the tab's
`PWA_SID`. A failure goes to stderr as `tabs: <heading> [<code>]: <reason>` and the command ends with 1.
"""
from __future__ import annotations

import os
import sys
import urllib.parse
from collections.abc import Callable
from pathlib import Path

#: What the call waits for a command that may be carried to the other machine, or wakes a tab: the backend judges the text,
#: waits for the other machine's own check, and waking a sleeping tab and starting its claude take up to about two minutes
LONG_TIMEOUT_SEC = 300.0
#: The words whose call waits that long
LONG_WORDS = ("add", "close", "pass")
NOT_SENT_CODE = "ticket_not_sent"
UNCONFIRMED_CODE = "ticket_unconfirmed"
KINDS = ("decide", "mac", "report")
USAGE = (
    "tabs ticket new <題> <本文の file> [--operator-said]\n"
    "       tabs ticket show <id>\n"
    "       tabs ticket add <id> <file>\n"
    "       tabs ticket ask <id> --kind decide|mac|report <file> [--recommend <file>]\n"
    "       tabs ticket close <id> [<file>]\n"
    "       tabs ticket pass <id> <宛先>"
)
#: The sentence at the head of a failure, per word
HEADINGS = {"new": "票を開けませんでした", "show": "票を読めませんでした", "add": "票に書き足せませんでした",
            "ask": "票を操作者の前に出せませんでした", "close": "票を閉じられませんでした", "pass": "票を渡せませんでした"}

#: The backend's call: (path, form, method, timeout) → (HTTP status, JSON body); status 0 when nothing answered
Call = Callable[..., tuple[int, object]]
#: How `tabs send` finds a receiver: the receiver as written → (the tab id to send to, or the receiver as it was for the
#: backend to find; a refusal as (code, reason) or None)
Resolve = Callable[[str], tuple[str, tuple[str, str] | None]]


def run(argv: list[str], call: Call, resolve: Resolve | None = None) -> int:
    """Run `tabs ticket <word> ...`. → 0, or 1 on a failure, or 2 when the words are not one of the forms above.
    `resolve` turns the receiver of `pass` into a tab id the way `tabs send` does (= an outward name is found here, since
    the backend knows the tabs' names but not which names this tab may see)."""
    word, rest = (argv[0], argv[1:]) if argv else ("", [])
    plan = _plan(word, rest)
    if plan is None:
        print(f"使い方: {USAGE}", file=sys.stderr)
        return 2
    sender = os.environ.get("PWA_SID")
    if not sender:
        print("tabs: このタブの id (= PWA_SID) がありません。 PWA のタブの中から打ってください", file=sys.stderr)
        return 1
    try:
        path, form, method, files = plan
        texts = {name: Path(file).read_text(encoding="utf-8") for name, file in files.items()}
    except OSError as error:
        print(f"tabs: {error.filename} を読めません: {error.strerror}", file=sys.stderr)
        return 1
    form = {**form, **texts}
    if word == "pass" and resolve is not None:
        receiver, refusal = resolve(form["to"])
        if refusal is not None:
            print(f"tabs: {HEADINGS[word]} [{refusal[0]}]: {refusal[1]}", file=sys.stderr)
            return 1
        form = {**form, "to": receiver}
    if method == "GET":
        status, body = call(f"{path}?reader={urllib.parse.quote(sender, safe='')}", None, "GET")
    else:
        timeout = LONG_TIMEOUT_SEC if word in LONG_WORDS else None
        status, body = call(path, {"from": sender, **form}, **({"timeout": timeout} if timeout else {}))
    if status == 200 and isinstance(body, dict) and body.get("ok"):
        print(_shown(word, body))
        return 0
    code, message = failure(status, body)
    print(f"tabs: {HEADINGS[word]} [{code}]: {message}", file=sys.stderr)
    return 1


def _plan(word: str, rest: list[str]) -> tuple[str, dict, str, dict[str, str]] | None:
    """What to call for `word` and its arguments: (path, form fields, method, {form field: file to read}). None when the
    words are not one of the forms of the usage."""
    quoted = urllib.parse.quote(rest[0], safe="") if rest else ""
    if word == "new" and len(rest) in (2, 3) and rest[2:] in ([], ["--operator-said"]):
        form = {"title": rest[0], **({"operator_said": "true"} if rest[2:] else {})}
        return "/tickets", form, "POST", {"text": rest[1]}
    if word == "show" and len(rest) == 1:
        return f"/tickets/{quoted}", {}, "GET", {}
    if word == "add" and len(rest) == 2:
        return f"/tickets/{quoted}/entries", {}, "POST", {"text": rest[1]}
    if word == "close" and len(rest) in (1, 2):
        return f"/tickets/{quoted}/close", {}, "POST", {"text": rest[1]} if len(rest) == 2 else {}
    if word == "pass" and len(rest) == 2:
        return f"/tickets/{quoted}/pass", {"to": rest[1]}, "POST", {}
    if word == "ask":
        return _ask_plan(quoted, rest)
    return None


def _ask_plan(quoted: str, rest: list[str]) -> tuple[str, dict, str, dict[str, str]] | None:
    """`ask <id> --kind <kind> <file> [--recommend <file>]`: the options may come in any order after the id."""
    words, kind, recommend, texts = rest[1:], None, None, []
    while words:
        if words[0] == "--kind" and len(words) >= 2 and kind is None:
            kind, words = words[1], words[2:]
        elif words[0] == "--recommend" and len(words) >= 2 and recommend is None:
            recommend, words = words[1], words[2:]
        else:
            texts, words = [*texts, words[0]], words[1:]
    if not rest or kind not in KINDS or len(texts) != 1:
        return None
    return f"/tickets/{quoted}/asks", {"kind": kind}, "POST", {"text": texts[0], **({"recommend": recommend} if recommend else {})}


def _shown(word: str, body: dict) -> str:
    """The line a success prints (= for `show`, the whole ticket)."""
    if word == "new":
        said = "操作者の発話つき" if body.get("operator_said") else "操作者の発話なし"
        left_out = body.get("operator_said_left_out")
        note = "\n操作者の発話は入りませんでした: 今の作業を始めたのが操作者の発話ではありません。 要るなら、 操作者の言葉を本文に「」で写して書き足してください" if left_out else ""
        return f"{body.get('id')} ({said})" + note
    if word == "show":
        return _ticket_text(body)
    if word == "pass":
        kept = " (宛先は口座の線で止まっています。 動ける口座ができた時に届けます)" if body.get("kept") else ""
        return f"渡しました: {body.get('id')} → {body.get('to')}{kept}"
    return f"{body.get('id')} ({body.get('status')})"


def _ticket_text(body: dict) -> str:
    wants = f" / 求める物: {body['wants']}" if body.get("wants") else ""
    home = f" ({body['home']} の機械の票)" if body.get("home") else ""
    lines = [f"票 {body.get('id')} ({body.get('status')}{wants}){home} 持ち主: {body.get('holder')}", ""]
    for entry in body.get("entries") or []:
        if entry.get("hidden"):
            lines += [f"--- {entry.get('at')} {entry.get('text')}", ""]
            continue
        title = f" 「{entry['title']}」" if entry.get("title") else ""
        asked = f" [{entry['ask_kind']}]" if entry.get("ask_kind") else ""
        passed = f" → {entry['to']}" if entry.get("to") else ""
        who = "操作者" if entry.get("kind") == "operator" else f"{entry.get('tab_title')} ({entry.get('tier') or '-'})"
        lines += [f"--- {entry.get('at')} {entry.get('kind')}{asked}{passed} {who}{title}", str(entry.get("text", "")).rstrip()]
        if entry.get("recommend"):
            lines += ["", f"推奨: {entry['recommend'].rstrip()}"]
        lines.append("")
    return "\n".join(lines).rstrip()


def failure(status: int, body: object) -> tuple[str, str]:
    """The code and the sentence of an answer that is not a success: the backend's own, or one made from the call."""
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, dict) and detail.get("code"):
        return str(detail["code"]), str(detail.get("message", ""))
    raw = str(detail.get("message")) if isinstance(detail, dict) and detail.get("message") else str(body)[:200]
    if status == 0 and not (isinstance(detail, dict) and detail.get("may_have_arrived")):
        return NOT_SENT_CODE, f"{raw}。 何も書いていません。 backend が起動し直している間かもしれません。 少し待ってやり直してください"
    return UNCONFIRMED_CODE, (f"backend から答えを受け取れませんでした (HTTP {status}): {raw}。 票に書けているかもしれません。 "
                              "やり直す前に `tabs ticket show` で確かめてください")
