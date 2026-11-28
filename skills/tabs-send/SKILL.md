---
name: tabs-send
description: Send a message to another tab of the client with `tabs send`, carry the operator's yes to another tab, and act on the error a send prints.
when_to_use: Before sending a note to another tab or answering one / when the operator's yes given in one tab has to reach another / when `tabs send` fails with a code.
---

## Sending a message to another tab

Send when something concerns what another tab owns: a defect in a tool it maintains, a fixed version it should
pick up, a decision that affects it. Do not wait for the operator to carry it.

1. Pick the receiver.

   ```
   tabs list
   ```

   One line per tab: id, tier, account, state, boundaries read, name. The account of a sleeping tab is the one it
   runs on once woken.
   A tab with no running Claude has the state
   `未起動` (a message starts it) or `起こせない` (it cannot be started). Tabs of another agent show `別の agent`
   instead of a tier. A tab that works in a boundary this tab does not know shows `別の境界` as its tier and
   `(別の境界のタブ)` as its name; when the guard gives its tier an outward name this tab may see, the name cell
   shows that name instead (the tier stays `別の境界`, which is how you tell it from a tab's own name). When several tabs own the same thing, choose by the tab's
   name. When the name does not decide it, send to the nearest one and carry on.

2. Write the body to a file and send it.

   ```
   tabs send <tab id, outward name or name> <body file>
   ```

   The receiver is resolved in this order: the tab's id; then an outward name from `tabs list` (the tab working in
   that name's folder; when several do, the one placed for that tier; when none is placed, the only one that is not
   a child); then the tab's name. Outward names exist only when the guard answers `--roles`; without it every
   receiver is an id or a name, as before. If that still leaves several tabs, or the outward name is also the name
   of a tab you can see, nothing is sent and the reason and the ids are listed: choose by id. An outward name with no tab says so; `tabs open` does not apply to it.

   `届きました` means the note is in the receiver's terminal; a receiver in the middle of work reads it at its
   next break. A tab with no running Claude is started first, the way the operator's action would start it: without
   a tmux session, or with only a shell left in the pane, its last conversation is reopened (a child too). A new
   conversation starts in its tier (`normal` when it has none) only when there is no conversation to reopen or the
   operator restarted the tab with ⟳. A tab put to sleep is woken and its conversation reopened, which takes about
   two minutes; `tabs send` waits for it. From a Bash tool call, set its timeout to 300 seconds or run the command in
   the background, because the tool's default of two minutes can cut the call off while the message is still on its way.
   A call cut off that way may have delivered the message: see `agent_message_unconfirmed` below before sending again.

3. Write the body so it stands alone: the request, the facts from the sender's side, and what the receiver is free
   to decide. Give a reproduction in terms of a sample, not of material the receiver is not allowed to see.

`tabs send <to> <file> --operator-said` also attaches the operator's last utterance in the sender's tab. Use it
only when that utterance is what caused this message ("tell them to fix it"). Never for a message the sender
decided to send, a reply, or a report: the receiver reads the attached text as the operator's own words in its tab.
The backend reads that text from the conversation record; the sender cannot write it. It is the utterance that began
the sender's current work, even when another tab's message was queued into that work afterwards. When the words could
not go (the work began with another tab's message, the check refused them, or the receiver is on another machine),
`tabs send` says so in a line after `届きました`; copy the operator's words into the body in quotes if they are needed.

If the guard that screens messages stops one, the reason line names what it objected to. Rewrite the body in
your own words without the quoted material and send again.

### Carrying the operator's yes from another tab

The operator may answer in another tab than the one that asks. Tab B waits for the operator's yes to a call the guard
holds, and the operator is looking at tab A. Then A carries the yes to B:

1. A shows the call B will type, character for character the same, in a fenced block labelled `guard`.
2. The operator types only `はい` (yes) in A.
3. In that same turn, A sends B the message with `tabs send <B> <body file> --operator-said`. The body says which
   call B is to type, unchanged.
4. B types that call inside the turn the message opened. It passes.

One block is passed once, for the two tabs together. It cannot be used when the operator types anything else after the
yes, and it does not pass from another machine. The conditions in full are the guard's, not this skill's: read the
section *A message relayed with the operator's answer* in `$AGENT_PLATFORM_ROOT/tools/guard-dispatcher/README.md`.

### Errors of `tabs send`

A failed send prints `[<code>]: <what to do>`. Every failure has a code; a send whose result the command could not
learn at all (the backend's answer is missing or has no code) prints `agent_message_not_sent` or
`agent_message_unconfirmed` too.

| Code | Meaning and what to do |
|---|---|
| `agent_message_refused` | The body contains material the receiver may not read. Rewrite it in your own words. |
| `agent_message_unknown_receiver` | No tab has that id or name, or the tab was closed. Run `tabs list` for the tab that owns the thing now and send again to it. |
| `agent_message_ambiguous_receiver` | Several tabs share the name, or an outward name has several tabs, or an outward name is also a tab's name. Use the id from `tabs list` (the message lists them). |
| `agent_message_to_self` | The receiver is this tab. |
| `agent_message_empty` | The body is empty. |
| `agent_message_unknown_sender` | This tab's id (`PWA_SID`) is not a tab of the backend. Send the client's tab the command, the code and the time, as a defect of the client. |
| `agent_message_receiver_not_running` | No Claude runs in the receiver's tab and the message could not start one. Start it yourself instead of asking the operator to open the tab: run `tabs list`, and if the tab is listed send the same message once more; if it is not, run `tabs open <tier>` and send. If it still does not arrive, send the client's tab the command, the code and the time, as a defect of the client. |
| `agent_message_receiver_not_ready` | Nothing was typed: the receiver's Claude did not start in time, or did not take input, or its conversation has not begun. Send once more. |
| `agent_message_not_taken` | The receiver's Claude was started for this message, and its conversation record shows no message after the wait and one rescue. Send once more. |
| `agent_message_not_sent` | An error nobody foresaw stopped the send before anything was typed (the backend was restarting, or its answer was a bare error). Nothing reached the receiver. Send once more; if it repeats, send the client's tab the command, the code and the time. |
| `agent_message_unconfirmed` | The message was typed, or the call was cut off after it was made, and its arrival is not known: it may be in the receiver's conversation. **Do not send it again at once**, because that can deliver it twice. Look at the receiver (`tabs list`, or its conversation record as the last section describes, in skill `tabs-records`) and send again only if the message is not there. If it repeats, send the client's tab the command, the code and the time. |
| `agent_message_check_failed` | The screening did not run. Send once more; if it repeats, tell the operator. |
| `agent_message_local_only` | The door was called from another machine. Send from a tab of this machine. |
| `agent_message_bad_id` | The message id is not 32 lowercase hex digits. `tabs send` makes its own, so this is a defect of the client: send the command and the code to the client's tab. |
| `agent_message_peer_offline` | The other machine is off the tailnet (asleep, no power or no network). Only when the message could not be kept either; see Tabs on other machines in skill `tabs-receive`. |
| `agent_message_peer_unreachable` | The other machine is on the tailnet (or that cannot be told) but its backend does not answer. Only when the message could not be kept either. |
