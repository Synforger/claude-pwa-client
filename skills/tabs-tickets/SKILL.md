---
name: tabs-tickets
description: Keep a request that crosses tabs as a ticket, with the `tabs ticket` commands.
when_to_use: Before asking another tab to do something / when a ticket was passed to this tab / when putting a ticket in front of the operator, or closing it.
---

## Requests that cross tabs: `tabs ticket`

A request that one tab asks of another is kept as one **ticket**, a file that tabs only add to. Handing a request on by
rewriting it in every message shrinks it to a line by the fourth tab; a ticket keeps the first tab's own words (and, with
`--operator-said`, the operator's), and the message between tabs is one line: "ticket `<id>` is yours now".

```
tabs ticket new <title> <body file> [--operator-said] [--due YYYY-MM-DD]
                                                          open a ticket; prints its id
tabs ticket show <id> [--since-mine]                      read all of it, by time (--since-mine: only what came after this tab's last line)
tabs ticket mine [--json] [--unsettled]                   the tickets this tab holds that are not closed
tabs ticket add <id> <file> [--waiting] [--due YYYY-MM-DD]
                                                          add what you did (nothing is removed or reworded)
tabs ticket ask <id> --kind decide|mac|report <file> [--recommend <file>]
                                                          put the ticket in front of the operator
tabs ticket close <id> [<file>]                           close it (it stays; nothing can be added after)
tabs ticket pass <id> <tab id or name>                    move the ticket to that tab and tell it in one line (the receiver is
                                                         found as `tabs send` finds it: id, outward name, then name)
```

- Use a ticket for a request (something another tab is to do). A note that needs no reply stays a `tabs send` message.
- On receiving "ticket `<id>` was passed to you", read it with `tabs ticket show <id> --since-mine` (what this tab wrote and
  what came before it is left out, the request and the operator's words kept; a ticket this tab never wrote to comes whole), do the work, add what you did, and
  pass it on or close it. Do not copy the request into your own message: the next tab reads the ticket.
- `--operator-said` on `new` puts the operator's last words in this tab into the ticket, read by the backend from the
  conversation record; use it only when those words are what the request came from, as with `tabs send --operator-said`.
  A ticket the operator's words went into comes from the operator (`origin`); every other ticket comes from the tab.
- A ticket is `open` (moving), `waiting`, `waiting-operator` or `closed`. `add --waiting` sets a ticket aside until
  something happens (the text says what it waits for); a plain `add` puts a waiting ticket back to `open`. A ticket that
  waits for the operator stays so until the operator answers. `--due YYYY-MM-DD` (on `new` or `add`) is the day it is due.
- Marks tell a ticket needs another look: `overdue` (due day past), `due_soon` (due within 2 days), `waiting_stale`
  (waiting, the tab's last line 5 days old or more), `idle` (open, the tab's last line 14 days old or more).
- `mine` lists the tickets this tab holds that are not closed, one line each: id, state, where it came from, marks, title, next
  step. Waiting ones are counted on one line, and a machine that did not answer is named. `--json` prints what the backend
  answered. `--unsettled` lists the open tickets this tab has not written to since its conversation began and may write to,
  and ends with 1 when there are any (0 and nothing printed when there are none, 3 when it could not look).
- `tabs rollover` runs the same check first and, when it finds tickets, names them (id and title) and does not restart: add
  what you did (`--waiting` to set one aside), pass it or close it, then run it again.
- `ask` marks the ticket as waiting for the operator (`decide` = a decision, `mac` = something only done at the Mac, `report`
  = a report); a ticket waiting for the operator cannot be passed. The recommendation, when given, is what the operator may
  take as it stands.
- A failure prints `tabs: <what failed> [<code>]: <reason>`. Codes (`ticket_unknown`, `ticket_closed`, `ticket_waiting_operator`,
  `ticket_refused`, `ticket_outside_place`, ...) and the optional check commands that limit who may read and write a ticket:
  `docs/reference/tickets.md`.
