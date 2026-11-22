"""The words that tell a child tab's new conversation that it is a child, and what it holds.

A child's first task says it by itself (= `<child-start>`). Every other new conversation of a child begins with an
envelope of the client, and an agent that reads only that envelope would take itself for the parent: it starts in the
parent's tier, whose journal holds the parent's requests. So the envelopes carry these lines.

The agent's launch script reads `key=value` lines inside an envelope, so no line of prose here holds `=`, and none
names a tag of an envelope.

Pure: no file, no call. Used by `routes/rollover.py` (the rollover), `terminal/first_message.py` (the `<tab-open>` of
a child) and `cli/tabs.py` (the headings of the memo).
"""
from __future__ import annotations

from collections.abc import Container

#: The memo's section with the work the parent handed
HANDED = "## 渡された仕事"
#: The memo's section the child writes before its rollover and reads after it
CARRY = "## 引き継ぎ"

_ROLE = ("This tab is a child tab. The journal of its tier and the requests written there are the parent's: do not "
         "run the startup of a parent tab and do not act on them. This tab's own work is in its memo (the file in "
         f"PWA_NOTE): `{HANDED}` is what the parent handed, `{CARRY}` is what this tab left for itself and is the "
         "newer where the two differ.")
_AFTER_ROLLOVER = ("If the mode above is continue, the memo's state is 作業中 and the handover names a next step, "
                   "carry on from that step. In every other case start no work and wait for the parent's message; "
                   "when the memo's state is 作業中 or the memo cannot be read, first send `tabs report stuck <file>` "
                   "saying what this tab waits for.")
_AFTER_OPENING = ("Read the memo, if there is one, and start none of its steps by yourself: the next message says "
                  "what to do.")
_NO_PARENT = ("The parent tab is gone: start no work from the memo, say so in your reply, and wait for the "
              "operator.")
CLOSE_HANDOVER = (f"This tab is a child tab: hand over in the `{CARRY}` section of its memo (the file in PWA_NOTE), "
                  "not in a journal. Rewrite that section to the work as it stands now, with no step that is already "
                  "done, then run `tabs rollover continue` (or `tabs rollover wait` when there is nothing to carry on).")


def known_parent(parent_id: str | None, tabs: Container[str]) -> str | None:
    """The parent's id while that tab is still among `tabs`."""
    return parent_id if parent_id and parent_id in tabs else None


def rollover_lines(parent: str | None) -> list[str]:
    """The lines for the first message after a child's rollover. `parent` is None when that tab is gone."""
    return _lines(parent, _AFTER_ROLLOVER)


def opening_lines(parent: str | None) -> list[str]:
    """The lines for the `<tab-open>` that starts a child's new conversation ahead of the message that caused it."""
    return _lines(parent, _AFTER_OPENING)


def _lines(parent: str | None, next_step: str) -> list[str]:
    if parent is None:
        return ["child=1", f"{_ROLE} {_NO_PARENT}"]
    return ["child=1", f"parent={parent}", f"{_ROLE} {next_step}"]
