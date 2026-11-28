---
name: tabs
description: Find the tabs skill to read, and use the tier tabs, `tabs ask` and `tabs page-url`.
when_to_use: Before opening a tier tab again, asking a tab set up for a program, or handing the operator a page.
---

# Tabs: messages, child tabs, rollover, conversation records

Every tab of the client runs its own Claude Code conversation. The client's backend lets those conversations
reach each other, and `tabs` is the command an agent uses for it. It is installed by `task cli:install` (a link
in `~/.local/bin`) and runs only inside a tab of the client (= the tab's id is in `PWA_SID`).

`tabs` finds the agent's folder from `--agent-dir`, then `AGENT_ROOT`, then the folders under
`$AGENT_PLATFORM_ROOT/agents/` that hold the agent's launch script: the only one, or, when there are several, the one
that contains the current working folder (= a tab's Claude runs in its agent's folder or a tier below it). It reaches the backend on its port (= the
client's configuration for this machine; `PWA_PORT` when it is not the default).

## Tier tabs

An agent whose configuration has `tier_tabs: true` gets one tab per tier (`normal`, `projects/<P>`,
`projects/<P>/subprojects/<S>`, and `subprojects/<S>` below a subproject at any depth) placed in the list by the backend; a new tier folder gets its tab within a minute.
No Claude runs in a placed tab until a first message reaches it (the operator's, or a note sent with `tabs send`;
`tabs list` shows such a tab as `未起動`). The backend then starts Claude with an envelope the client writes, not
the operator's words: `Tab opened by the client for its tier (the operator did not type this):` followed by a
`<tab-open>` block with the `tier=` line. The message that arrived comes next, unchanged. Run the startup as for
a new session, then answer that message.

The backend does not place a tier tab again once it was closed. To bring one back:

```
tabs open <tier>
```

It refuses when that tier already has a tab, or when the agent has no folder for it. See
`docs/reference/tier-tabs.md`.

## Asking a tab set up for a program: `tabs ask`

A program on this machine can use a Claude Code tab as its model:

```
tabs ask <tab id or name> <text file> [--fresh | --resume <conversation id> [--fork]] [--stream | --json] [--timeout <seconds>]
```

It types the text into the tab and prints the last answer of that turn on stdout. `--fresh` types `/clear` first, so
the turn sees none of the earlier asks; `--timeout` (default 180 seconds) stops a turn that has not ended. It needs no
`PWA_SID`, so a program outside every tab runs it as a subprocess. Only tabs whose agent has `"ask": true` take it:
the text arrives as plain input, the way the operator's own words do, so the tabs agents work in refuse it
(`ask_not_allowed`). Such an agent runs without tools in an empty folder. To talk to a colleague's tab, use
`tabs send`, not this. Codes and setup: `docs/reference/ask.md`.

`--stream` prints one JSON line at a time: `partial` (the answer so far, read off the screen while the turn runs; only a
first look, not exactly the final text), then `final` (the real answer and the conversation's id) or `error`. `--json`
prints `{"answer": ..., "session": ...}`, the id of the conversation that answered. `--resume <id>` opens that earlier
conversation before asking, and `--fork` with it asks in a branch of it (the conversation it came from stays as it was);
it cannot go with `--fresh` (`ask_bad_args`), and a conversation that does not open is `ask_not_ready`.

## Handing the operator a page: `tabs page-url`

A page in the folder of the client's `page_origin` opens on the operator's devices only through the tailnet, not
through `localhost`. Never write a `localhost` or `127.0.0.1` URL for the operator; ask for the address instead:

```
tabs page-url <file>
```

It prints the URL (`https://<this machine on the tailnet>[:<port>]/<path inside the folder>`), made by the backend from
the page origin and what `tailscale serve` exposes. It stops with the reason when the file is outside the folder (or outside the `folders` it lists), when
there is no `page_origin` or its listener is closed, or when `tailscale serve` does not expose the page port (the
reason names the `tailscale serve` command that would).

## The other tab skills

- `tabs list`, `tabs send`: skill `tabs-send`
- A message that arrived, and tabs on other machines: skill `tabs-receive`
- `tabs ticket`: skill `tabs-tickets`
- `tabs new`, `children`, `close`, `rename`, `sleep`, `capacity`, `report`, and working as a child: skill `tabs-children`
- `tabs rollover`: skill `tabs-rollover`
- A tab's conversation record: skill `tabs-records`
