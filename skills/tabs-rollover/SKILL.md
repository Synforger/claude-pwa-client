---
name: tabs-rollover
description: Hand a tab over to its next session with `tabs rollover`.
when_to_use: When a closing request for a rollover arrives / close or restart the conversation of a tab.
---

## Handing a tab over: `tabs rollover`

A long conversation fills its context. The backend can ask a conversation to close at a break and start again in
the same tab (see `docs/reference/rollover.md`). The last step of the closing is

```
tabs rollover continue    # the next session carries on with the handed-over work
tabs rollover wait        # the next session greets and waits for the operator
```

with `--tier <tier>` when the tab's tier cannot be found. The command first checks that this conversation has written to every open ticket it holds
(`tabs ticket mine --unsettled`), then that the closing is done (the
handover note is written and committed, and for a child, that its memo's handover section is filled), and names
the missing step when it is not. It asks the backend to end this conversation and start the next one in the same
tier, so run it last.

Ending a conversation stops what its tools run in the background (a Bash call with `run_in_background`, a Monitor):
Claude Code sends them SIGTERM as it exits. `tabs rollover` therefore refuses while such a command runs, and names
each one (pid, how long it has run, the command). Wait for it to end (it reports when it does), or stop it if it may
stop, then update the handover and run `tabs rollover` again. A command that must outlive the conversation (a test
run of hours, a long build) is started from a plain Bash call as `nohup <command> > <log> 2>&1 &`: its call returns at
once and the command survives the end of the conversation. The backend's watch does not ask a tab to close while its
tools run such commands either.
