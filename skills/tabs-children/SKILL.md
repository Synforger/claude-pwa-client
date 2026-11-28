---
name: tabs-children
description: Hand work to child tabs, and work as a child tab.
when_to_use: When a tab starts as a child tab (AGENT_CHILD=1), also after a restart / hand a piece of work to a child tab, or finish as a child tab / rename, close or put to sleep a child tab.
---

## Child tabs

A child tab is a normal tab that a parent tab opens to hand work over. It keeps its own conversation, so it keeps
running when the parent restarts. Use `tabs` from the parent:

```
tabs new <title> <task file>      open a child; the task becomes its first message
         [--model <name>] [--effort <level>]   the child's model and effort (the agent's launch script takes only values it allows)
tabs children [--summary]         list the children this tab opened (id, memo state, what its Claude is doing, title)
tabs close <child id> [--force]   close a child and clear its memo and untouched top page; a child still working needs --force
tabs rename <child id> <title>    give a child the title of the work it holds now
tabs sleep <child id>             put a child's Claude to sleep now; a message wakes it in the same conversation
tabs capacity [--json]            how much this machine holds now: the child limit, the claudes and their memory, the
                                  machine's memory and each account's usage (plain numbers; no line is drawn)
```

**Name the child by its work alone** (`tabs new "<what it does>" …`). The list shows a child under its parent and in its
parent's folder, so a prefix of the tier, the project or the parent's name only repeats what the list already shows.
When you hand a child other work, rename it (`tabs rename <child id> "<what it does now>"`), so the list says what it does.

The child starts in the same tier as the parent. A child cannot open children (`tabs new` refuses); work that
should be split further goes into its report. `tabs new` also writes the task into the child's memo
(`pages/<child id>/memo.md` in the tier folder) so the child can read it again after it restarts. There is no
limit on the number of children by default: split the work by what does not overlap and open one child per piece. Close
the ones that have reported. A positive `child_sessions_max` in the client's configuration stops `tabs new` at that
number.
Read `tabs capacity` before opening several children at once: it shows how many more claudes the free memory holds
and how much of each account is used, and the children share the parent's account.
A child that has reported but will take the next piece of the same work can wait asleep instead of closed: `tabs
sleep <child id>` ends its Claude and frees its memory at once, without the quiet minutes of the sleep patrol, and
the next `tabs send` to it reopens the same conversation. A message the parent delivers to a child that has reported
sets its memo back to `作業中`, since the child holds work again; it reports again when that work is done. A message
that hands no work (an acknowledgement, "no reply needed") goes with `tabs send <child> <file> --no-work`, which leaves
the memo as the report left it. It waits up to a minute for the child to finish its last
answer and names the reason when the child cannot sleep (a scheduled wake-up, a voice call, a rollover). A sleeping
child still counts towards `child_sessions_max` when one is set.

`tabs children` prints, per child: its id, the state in its memo (`作業中` / `完了` / `詰まり`), what its Claude is doing,
and its title. The Claude column has five words: `作業中` (answering), `裏の仕事待ち` (not answering, but waiting for a
command it started in the background, a wake-up, a cron job or a tool result: it goes on by itself when that ends),
`入力待ち` (at a break, waiting for a message), `眠り` (asleep) and `Claude なし`. A child whose memo still says `作業中`
while its Claude is `入力待ち` ends the line with `← 報告なしで止まっている`, and `--summary` counts such children as
`静か`; this is the same judgement as the watch that tells the parent.

A child that stops without reporting is not silent for long: the client looks over the children every minute and, when
one is at a break on two looks in a row (nothing answering, running or scheduled), sends the parent one message for that
stop. Its first line is the client's own opening line, its block is `<child-stopped child="…" title="…" reason="…">`, and
`reason` is `limit` (a usage limit stopped it and Claude Code will carry on by itself once the limit is over) or `idle`
(it waits for input and has not reported). Look at the end of its conversation, then send it a message or close it.

### Working as a child

Recognise a child by `AGENT_CHILD=1`, whatever its first message is. The first message of a new child starts with a
`<child-start>` block (the tier) followed by the task; after a restart it is an envelope of the client instead (see
*A child that starts again*). A child works like a sub-agent with its own conversation:

1. Say in three lines, before starting: its role, what it may write, what it may only read. If the scope is unclear,
   ask the parent (`tabs report stuck`) rather than guess.
2. Work only inside the folders and branch the task names. Commit there; opening a pull request and merging are the
   parent's.
3. Report when done or stuck. Write the report to a file and run

   ```
   tabs report done  <report file>
   tabs report stuck <report file>
   ```

   The report reaches the parent's current conversation even if the parent restarted, and the memo's state line
   becomes done or stuck. After reporting, wait for the parent's reply; the parent closes the tab.
   A done report says what was done, what was not, what the parent must check, and the branch, commits and test
   state. A stuck report says the symptom, the cause (file and line) and anything else relevant.
4. A decision that needs design judgement goes back as `stuck`, not as a guess.

### A child that starts again

After a rollover, a child's first message is `<session-rollover phase="start">`; after the operator's ⟳ it is
`<tab-open>`, followed by the message that woke it. Both carry `child=1` and, while the parent's tab exists,
`parent=<id>`. The journal of the tier and the requests in it are the parent's: do not run a parent's startup and do
not act on them, even when the agent's general startup steps say that a rollover starts like any session.

Read the memo (the file in `PWA_NOTE`): the section with the task and `## 引き継ぎ`, which is the newer where the two
differ. Then:

| The envelope | The memo | What the child does |
|---|---|---|
| rollover, `mode=continue` | working, and the handover names a next step | carry on from that step |
| any other rollover | working, or no memo to read | `tabs report stuck <file>` saying what it waits for, then wait |
| any other rollover | done or stuck | wait for the parent's message |
| `<tab-open>` | any | start no step of the memo by itself; follow the message that comes next |
| either, with no `parent=` line | any | start no work from the memo; say so in the reply and wait for the operator |

### A child that has to restart

When the closing request arrives (`<session-rollover phase="close">`), bring the work to a break, commit what is
half written, and rewrite the `## 引き継ぎ` section of the memo (the file in `PWA_NOTE`) with where the work is,
the next step, and what it waits for; leave no step that is already done, since the next conversation acts on it.
Do not delete the section with the task. The heading is the literal the command looks for. Then run
`tabs rollover continue` (`wait` when there is nothing to carry on); it refuses until the conversation has written
that section.
