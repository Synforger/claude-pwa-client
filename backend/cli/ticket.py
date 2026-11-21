"""`tabs ticket`: the requests that cross tabs, kept as one ticket each that tabs only add to (`docs/reference/tickets.md`).

    tabs ticket new <title> <body file> [--operator-said] [--due YYYY-MM-DD]
                                open a ticket and print its id. --operator-said puts the operator's last words in this tab
                                into the ticket (= read from the conversation record; only when the request came from them),
                                and the ticket then comes from the operator. --due is the day it is due
    tabs ticket show <id> [--since-mine]
                                read the whole ticket by time; a line the guard does not let this tab read is one line saying so.
                                --since-mine leaves out what this tab already wrote and what came before it (= only the lines
                                after this tab's last line, with the first line (the request) and the operator's words always
                                kept), and says how many it left out. A tab that never wrote to the ticket gets all of it
    tabs ticket mine [--json] [--unsettled]
                                the tickets this tab holds that are not closed, one line each (id, state, where it came from,
                                marks, title, next step), the waiting ones counted on one line, and a machine that did not answer
                                named. --json prints what the backend answered. --unsettled lists the open tickets this tab has
                                not written to since its conversation began and that it may write to (= the ones a restart would
                                drop): it ends with 1 when there are any, 0 and nothing printed when there are none, 3 when it
                                could not look
    tabs ticket add <id> <file> [--waiting] [--due YYYY-MM-DD]
                                add what you did (= nothing is removed or reworded; the holder does not change). --waiting sets
                                the ticket aside until something happens (the text says what), and a plain add puts a waiting
                                ticket back to open. --due is the day it is due
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

`tabs.py` reads the command word and hands the rest here with its way of calling the backend and of finding this tab's
conversation record. The sender is the tab's `PWA_SID`. A failure goes to stderr as `tabs: <heading> [<code>]: <reason>` and
the command ends with 1 (`mine --unsettled` ends with 3, since 1 says it found tickets).
"""
from __future__ import annotations

import json
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
#: What `mine --unsettled` ends with when it found open tickets the tab has not written to, and when it could not look
UNSETTLED_FOUND = 1
UNSETTLED_NOT_LOOKED = 3
#: A ticket's state that is set aside (= `mine` counts these on one line) and the one `--unsettled` looks for
WAITING = "waiting"
OPEN = "open"
#: The switch of `show` that leaves out what this tab already wrote and what came before it
SINCE_MINE = "--since-mine"
#: The lines `--since-mine` always keeps: the request and the operator's words
ALWAYS_SHOWN = ("opened", "operator")
#: How `mine` names where a ticket came from, by the backend's `source`
SOURCES = {"operator": "操作者", "tab": "別のタブ", "self": "自分"}
NOT_SENT_CODE = "ticket_not_sent"
UNCONFIRMED_CODE = "ticket_unconfirmed"
KINDS = ("decide", "mac", "report")
USAGE = (
    "tabs ticket new <題> <本文の file> [--operator-said] [--due YYYY-MM-DD]\n"
    "       tabs ticket show <id> [--since-mine]\n"
    "       tabs ticket mine [--json] [--unsettled]\n"
    "       tabs ticket add <id> <file> [--waiting] [--due YYYY-MM-DD]\n"
    "       tabs ticket ask <id> --kind decide|mac|report <file> [--recommend <file>]\n"
    "       tabs ticket close <id> [<file>]\n"
    "       tabs ticket pass <id> <宛先>"
)
#: The sentence at the head of a failure, per word
HEADINGS = {"new": "票を開けませんでした", "show": "票を読めませんでした", "mine": "持っている票を読めませんでした",
            "add": "票に書き足せませんでした", "ask": "票を操作者の前に出せませんでした", "close": "票を閉じられませんでした", "pass": "票を渡せませんでした"}

#: The backend's call: (path, form, method, timeout) → (HTTP status, JSON body); status 0 when nothing answered
Call = Callable[..., tuple[int, object]]
#: How `tabs send` finds a receiver: the receiver as written → (the tab id to send to, or the receiver as it was for the
#: backend to find; a refusal as (code, reason) or None)
Resolve = Callable[[str], tuple[str, tuple[str, str] | None]]
#: How `tabs.py` finds this tab's conversation record (= the file `mine` reads the start of the conversation from), or None
FindRecord = Callable[[], Path | None]


def run(argv: list[str], call: Call, resolve: Resolve | None = None, find_record: FindRecord | None = None) -> int:
    """Run `tabs ticket <word> ...`. → 0, or 1 on a failure, or 2 when the words are not one of the forms above.
    `resolve` turns the receiver of `pass` into a tab id the way `tabs send` does (= an outward name is found here, since
    the backend knows the tabs' names but not which names this tab may see)."""
    word, rest = (argv[0], argv[1:]) if argv else ("", [])
    if word == "mine":
        return _mine(rest, call, find_record)
    since_mine = word == "show" and SINCE_MINE in rest
    rest = [w for w in rest if w != SINCE_MINE] if since_mine else rest
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
        print(_shown(word, since_mine_of(body, sender) if since_mine else body))
        return 0
    code, message = failure(status, body)
    print(f"tabs: {HEADINGS[word]} [{code}]: {message}", file=sys.stderr)
    return 1


def _plan(word: str, rest: list[str]) -> tuple[str, dict, str, dict[str, str]] | None:
    """What to call for `word` and its arguments: (path, form fields, method, {form field: file to read}). None when the
    words are not one of the forms of the usage."""
    quoted = urllib.parse.quote(rest[0], safe="") if rest else ""
    if word == "new" and (split := _split(rest, ("--operator-said",), ("--due",))) and len(split[0]) == 2:
        (title, file), on, given = split
        form = {"title": title, **({"operator_said": "true"} if on else {}), **({"due": given["--due"]} if given else {})}
        return "/tickets", form, "POST", {"text": file}
    if word == "show" and len(rest) == 1:
        return f"/tickets/{quoted}", {}, "GET", {}
    if word == "add" and (split := _split(rest, ("--waiting",), ("--due",))) and len(split[0]) == 2:
        (_ticket, file), on, given = split
        form = {**({"waiting": "true"} if on else {}), **({"due": given["--due"]} if given else {})}
        return f"/tickets/{urllib.parse.quote(split[0][0], safe='')}/entries", form, "POST", {"text": file}
    if word == "close" and len(rest) in (1, 2):
        return f"/tickets/{quoted}/close", {}, "POST", {"text": rest[1]} if len(rest) == 2 else {}
    if word == "pass" and len(rest) == 2:
        return f"/tickets/{quoted}/pass", {"to": rest[1]}, "POST", {}
    if word == "ask":
        return _ask_plan(quoted, rest)
    return None


def _split(words: list[str], switches: tuple[str, ...], valued: tuple[str, ...]) -> tuple[list[str], set[str], dict[str, str]] | None:
    """`words` as (the words that are no option, the `switches` given, the `valued` options with their value), the options
    in any order. None for an option that is not one of them, one given twice, or one left without its value."""
    plain: list[str] = []
    on: set[str] = set()
    given: dict[str, str] = {}
    while words:
        word, words = words[0], words[1:]
        if word in switches and word not in on:
            on.add(word)
        elif word in valued and words and word not in given:
            given[word], words = words[0], words[1:]
        elif word.startswith("--"):
            return None
        else:
            plain.append(word)
    return plain, on, given


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


def conversation_start(record: Path | None) -> str | None:
    """The time of the first line of this tab's conversation record that has one (= when the conversation began), as the record
    writes it; None when there is no record or no line with a time. `mine` gives it as `since`."""
    if record is None:
        return None
    try:
        with record.open(encoding="utf-8") as lines:
            for line in lines:
                try:
                    stamp = json.loads(line).get("timestamp")
                except (ValueError, AttributeError):
                    continue
                if isinstance(stamp, str) and stamp:
                    return stamp
    except OSError as error:
        print(f"tabs: この会話の記録を読めません ({record}): {error.strerror}", file=sys.stderr)
    return None


def _held_path(sender: str, since: str | None) -> str:
    query = f"tab={urllib.parse.quote(sender, safe='')}" + (f"&since={urllib.parse.quote(since, safe='')}" if since else "")
    return f"/tickets/held?{query}"


def unsettled_of(body: dict) -> list[dict]:
    """The tickets of an answer of `/tickets/held` that a restart would drop: open, not written to by this tab since its
    conversation began (`written_since` false; null, no `since`, is not false) and writable by it."""
    return [ticket for ticket in body.get("tickets") or []
            if ticket.get("status") == OPEN and ticket.get("written_since") is False and ticket.get("writable") is True]


def unsettled_text(tickets: list[dict]) -> str:
    """What is said of tickets this tab has not written to: each one's id and title, and what to do before the conversation ends."""
    lines = [f"  {ticket['id']}  {ticket.get('title') or '(題を読めません)'}" for ticket in tickets]
    return "\n".join([
        "この会話がまだ書き足していない、 動いている票があります (= 起動し直すと、 次の会話は票の続きを知りません):", *lines,
        "票ごとに `tabs ticket add <id> <file>` で今どこまで進んだかを書き (= 待つなら `--waiting`)、 渡すなら `tabs ticket pass`、"
        " 終えたなら `tabs ticket close` にしてください"])


def unsettled_refusal(call: Call, record: Path | None) -> str | None:
    """The sentence that says a restart waits for tickets this tab has not written to, or None when there is none. Called by
    `tabs rollover` before it checks the journal. When the tickets cannot be looked at (= no `PWA_SID`, no record, a backend
    that does not answer or has no such door) it says so on stderr and does not stop the restart: the restart is not
    held by a check that cannot run."""
    sender, since = os.environ.get("PWA_SID"), conversation_start(record)
    if not sender or since is None:
        return None
    status, body = call(_held_path(sender, since), None, "GET")
    if status != 200 or not isinstance(body, dict) or not body.get("ok"):
        print(f"tabs: 票を確かめられませんでした ({failure(status, body)[1][:120]})。 起動し直しは止めません", file=sys.stderr)
        return None
    found = unsettled_of(body)
    return unsettled_text(found) if found else None


def _mine(rest: list[str], call: Call, find_record: FindRecord | None) -> int:
    """`tabs ticket mine [--json] [--unsettled]` (see the head of this file)."""
    split = _split(rest, ("--json", "--unsettled"), ())
    if split is None or split[0]:
        print(f"使い方: {USAGE}", file=sys.stderr)
        return 2
    _plain, on, _given = split
    sender = os.environ.get("PWA_SID")
    if not sender:
        print("tabs: このタブの id (= PWA_SID) がありません。 PWA のタブの中から打ってください", file=sys.stderr)
        return 1
    since = conversation_start(find_record() if find_record else None)
    status, body = call(_held_path(sender, since), None, "GET")
    if status != 200 or not isinstance(body, dict) or not body.get("ok"):
        code, message = failure(status, body)
        print(f"tabs: {HEADINGS['mine']} [{code}]: {message}", file=sys.stderr)
        return UNSETTLED_NOT_LOOKED if "--unsettled" in on else 1
    if "--unsettled" in on:
        found = unsettled_of(body)
        if found:
            print(unsettled_text(found))
        return UNSETTLED_FOUND if found else 0
    print(json.dumps(body, ensure_ascii=False, indent=1) if "--json" in on else _mine_text(body))
    return 0


def _mine_line(ticket: dict) -> str:
    """`id  state  where it came from  [marks, due]  title — next step`."""
    marks = [*(ticket.get("marks") or []), *([f"期限 {ticket['due']}"] if ticket.get("due") else [])]
    parts = [str(ticket.get("id")), str(ticket.get("status")), SOURCES.get(str(ticket.get("source")), "?"),
             *([f"[{' '.join(marks)}]"] if marks else []), ticket.get("title") or "(題を読めません)"]
    step = f" — {ticket['next']}" if ticket.get("next") else ""
    return "  ".join(parts) + step


def _mine_text(body: dict) -> str:
    """What `mine` prints: the tickets that are moving (one line each), the waiting ones counted with their ids on one line, and
    each machine that did not answer on one line."""
    tickets = body.get("tickets") or []
    moving = [ticket for ticket in tickets if ticket.get("status") != WAITING]
    waiting = [str(ticket.get("id")) for ticket in tickets if ticket.get("status") == WAITING]
    lines = [_mine_line(ticket) for ticket in moving]
    if waiting:
        lines.append(f"待ち {len(waiting)} 枚: {' '.join(waiting)}")
    lines += [f"{machine} の機械が答えません (= その機械の票は出ていません)" for machine in body.get("peer_unreachable") or []]
    return "\n".join(lines) if lines else "持っている票はありません"


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


def since_mine_of(body: dict, me: str) -> dict:
    """The ticket with the lines up to this tab's last one left out, the request and the operator's words kept, and the
    number left out in `left_out`. Unchanged when this tab wrote no line."""
    entries = body.get("entries") or []
    last = max((index for index, entry in enumerate(entries) if entry.get("tab") == me), default=None)
    if last is None:
        return body
    kept = [entry for index, entry in enumerate(entries) if index > last or entry.get("kind") in ALWAYS_SHOWN]
    return {**body, "entries": kept, "left_out": len(entries) - len(kept)}


def _ticket_text(body: dict) -> str:
    wants = f" / 求める物: {body['wants']}" if body.get("wants") else ""
    home = f" ({body['home']} の機械の票)" if body.get("home") else ""
    lines = [f"票 {body.get('id')} ({body.get('status')}{wants}){home} 持ち主: {body.get('holder')}", ""]
    if body.get("left_out"):
        lines += [f"(このタブが最後に書いた件までの {body['left_out']} 件は省いています。 全部は {SINCE_MINE} を外して読む)", ""]
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
