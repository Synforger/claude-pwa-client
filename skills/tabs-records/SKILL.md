---
name: tabs-records
description: Find a tab's conversation record and read the dialogue in it.
when_to_use: Read what another tab's conversation said from its record.
---

## Finding a tab's conversation record

A conversation is a `.jsonl` file under `~/.claude*/projects/<folder-hash>/<claude session id>.jsonl`. To find the
record of a tab, and not another one:

1. Read the client's `jsonl_bindings.json` (`$AGENT_PLATFORM_ROOT/state/claude-pwa-client/data/`) and take the
   entries with `confirmed: true`: the tab id and the record's path.
2. Check that each path exists.
3. Read the **first user message** of the record: it is the most reliable sign of which conversation it is.
4. For "the latest", sort by modification time, but leave out the record of the conversation you are in; it is
   being written right now.

Do not decide by the working folder (many tabs of one agent start in the same folder), by the tab's title (the
binding does not hold it), or by an old table of tab-to-conversation pairs (they change on every restart). A
Claude Desktop conversation has no binding and no `pwa-*` tmux session: it is not a tab.

A record is read as what its conversation read. The record of a tab that works in a boundary this tab does not know
(`別の境界` in `tabs list`) is refused by the guard before it is read, and the refusal names the outward name of a
tab that may read it. Do not look for another way to open it: send the question with `tabs send` to that tab, or to
the tab whose record it is, and let it answer from its own record.

To read the dialogue, parse the file line by line as JSON, keep rows whose `type` is `user` or `assistant`, and
collect the `text` blocks of `message.content` (a string or a list). Skip `tool_use` and `tool_result` blocks.

What the operator types while Claude is working has no `user` row. When Claude takes it in the middle of its work,
it is a row with `type` `attachment` whose `attachment.type` is `queued_command`; the text is `attachment.prompt`.
Keep those rows too, or every interruption is missing. (The `queue-operation` rows with `operation` `enqueue` also
hold each typed text in `content`, but a message that waited for the next turn is then written again as a `user`
row, so reading them as well counts it twice.)
