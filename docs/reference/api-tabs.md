# API tabs

An API tab is a tab with no Claude Code behind it. A program outside the client (a bot, say) calls the Anthropic
Messages API itself and appends the conversation to a file; the client reads that file and shows it as a tab. The
client never calls the API and never holds a key.

What the tab shows is the conversation (your messages, the answers, tool calls and their results) and one figure: how
much of the context the conversation holds. It shows no "thinking", "answered" or unread marks, takes no input and has
no terminal, stop button, menu, notes or voice. Where the input would be, one line says the tab is only shown.

## Declaring a tab

Add `api_tabs` to `config.json` (and, to see what the program spends, `api_accounts`):

```json
"api_accounts": {
  "api": {"display_name": "API", "spend": "/path/to/state/support-bot/spend.json"}
},
"api_tabs": {
  "support-bot": {
    "title": "Support bot",
    "agent_id": "agent_a",
    "account": "api",
    "record": "/path/to/state/support-bot/conversations/main.jsonl"
  }
}
```

| Field | Meaning |
|---|---|
| name (the key) | `[a-z0-9-]+` only. The tab's id is `api_<name>`. A row whose name uses other characters is not read, and one warning line is written to the log |
| `title` | The name the list shows (the name when left out) |
| `agent_id` | An agent of `agents`: where in the list the tab sits. A row naming an agent that is not configured is not read (a warning line is written) |
| `account` | The wallet the tab spends from (`api` when left out). The list shows it as the tab's account |
| `record` | Absolute path of the record file. The tab appears even when the file does not exist yet (the conversation is empty until it does) |

`api_accounts` is read-only: nothing is routed to a wallet. A wallet is not an account of `accounts`, so the account
fallback, the account hold and the new-conversation list never see it. The wallets are shown under the accounts in the
[settings screen](settings-screen.md), each with this month's spend against its limit. `spend` is optional.

The table is read when the backend starts and whenever the configuration is read again (the settings screen does that
after a change; otherwise restart the backend). The list, the overview, the subscription filter and the replay all use
the same table, so they cannot disagree about which tabs exist.

## The record file

The program writes one JSON object per line, appending only:

```json
{"type": "user", "uuid": "<uuid4>", "timestamp": "2026-11-18T12:00:00.000Z", "message": {"role": "user", "content": "…"}}
{"type": "assistant", "uuid": "<uuid4>", "timestamp": "2026-11-18T12:00:01.000Z", "message": {"id": "msg_…", "role": "assistant", "content": [{"type": "text", "text": "…"}], "stop_reason": "end_turn", "usage": {"input_tokens": 300, "cache_read_input_tokens": 12000, "cache_creation_input_tokens": 0, "output_tokens": 8}}}
```

- `type` is `user` or `assistant`; `uuid` is a uuid4; `timestamp` is ISO 8601. Do not write `parentUuid` (the screen
  folds rows that share a parent)
- An assistant `message` is the API's answer as it is (the `content` blocks and `usage` included) and must have an `id`
  (the screen's bubble id)
- A user `message.content` is a string, or blocks of `text` and `tool_result`. Do not start a message with an XML tag
  such as `<command-` (such rows are taken for Claude Code's internal rows and left out). A message that holds only an
  image is not drawn
- The file is append-only: never rewrite or truncate it. A last row without its newline is a write in progress, and
  the client waits for the newline before reading it. At start, if the file does not end in a newline, write one first,
  so that a row cut by a crash does not run into the next row and spoil both

**Context amount** = `input_tokens + cache_read_input_tokens + cache_creation_input_tokens` of the last assistant row
that has a `usage` (a missing count is 0). Until such a row exists there is no amount: the screen shows nothing, never 0.
It is shown as `950`, `12.3k` (a thousand and over, one decimal) in the list and in the top bar.

## The spend file

The program counts what it spends and rewrites the whole file each time (write a temporary file in the same folder,
then rename it over the file):

```json
{"month": "2026-11", "spent": 123, "limit": 1000, "currency": "JPY", "updated_at": "2026-11-18T12:00:00+09:00"}
```

The client only reads it. `month` must be this month on the machine that runs the client; a file of another month
counts as no figure, never as zero. A file that is missing, cannot be read or is not this shape also means no figure
(shown as `---`), and one line is written to the log for each reason (at most once an hour):
`api account: <name> spend unreadable: <reason>`. The top bar of an API tab shows the wallet's spend this month.

## How the client follows the record

Every 0.5 seconds the client looks at each record. Rows appended since the last look reach screens that have the tab
open within a moment (the context amount in the list follows too).

- When the backend starts it follows a record from the end of its whole rows, so a restart does not stream the whole
  conversation again. A record that appears later is followed from its first row
- When the file gets shorter (or vanishes) the client follows it from the start again and tells the screens to fetch the
  history again
- The screen reads the history through the usual window (the latest rows), so the size of the file does not slow it down

Log lines: `api tab: loaded <id> record=<path> exists=<bool>` at load, `api tab: skipped <name>: <reason>` for a row that
was not read, and `api tab: <id> line <n> skipped: <reason>` for a row of a record that is not JSON (the same reason at
most once a minute).

## What an API tab does not take part in

| | |
|---|---|
| Patrols (account moves, stops at a line, continue after a limit, sleep, rollover, child watch, tier tabs) | None of them reach it: the tab is not among the tabs they walk |
| Messages between tabs | `tabs send` to an API tab (by id or title, from this machine or relayed from another) is refused with `agent_message_api_tab`: nobody reads it |
| Terminal, send, restart, fork, account move, rename, notification mode, notes, voice, rollover | Not offered; their endpoints answer 404 for it. Remove a tab by deleting its row from `api_tabs` |
| `tabs list` | Shows it with the state `API` and the tier `-` |
| iPhone widgets and Siri | The tab is not offered as a destination |

The row of an API tab in `GET /sessions` and the overview has `kind: "api"` and `context_tokens`; the status channel
gives it a row of its own kind (`kind`, `context_tokens`, `spend`) and none of a Claude tab's 5h / 7d / context figures
(see `contracts/schema/http-endpoints.yaml`).
